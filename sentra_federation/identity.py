"""Cryptographic installation identity.

The private key stays in the installation directory. Public material is the
certificate and its fingerprint. Nothing in this module listens or serves a file.
"""
from __future__ import annotations

import base64
import datetime
import hashlib
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from .errors import FederationDenied


def _now():
    return datetime.datetime.now(datetime.timezone.utc)


class InstallationIdentity:
    def __init__(self, key, cert, *, cert_path, key_path):
        self._key = key
        self.cert = cert
        self._cert_path = Path(cert_path)
        self._key_path = Path(key_path)
        self.cert_der = cert.public_bytes(serialization.Encoding.DER)
        self.cert_pem = cert.public_bytes(serialization.Encoding.PEM).decode("ascii")
        self.fingerprint = hashlib.sha256(self.cert_der).hexdigest()
        self.node_id = "sentra-" + self.fingerprint[:32]

    @property
    def cert_path(self):
        return self._cert_path

    @property
    def key_path(self):
        return self._key_path

    def sign(self, payload: bytes) -> str:
        signature = self._key.sign(payload, ec.ECDSA(hashes.SHA256()))
        return base64.b64encode(signature).decode("ascii")

    def public_material(self):
        return {
            "node_id": self.node_id,
            "fingerprint": self.fingerprint,
            "cert_pem": self.cert_pem,
        }

    @classmethod
    def generate(cls, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        key = ec.generate_private_key(ec.SECP256R1())
        # Distinct self-signed issuers and key identifiers let OpenSSL select
        # the correct certificate when several paired peers share one listener.
        # A common issuer name with no AKI caused a third peer to break mTLS
        # validation of an already paired first peer.
        public_key = key.public_key()
        key_id = x509.SubjectKeyIdentifier.from_public_key(public_key)
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "sentra-peer-" + key_id.digest.hex()[:32])])
        moment = _now()
        cert = (
            x509.CertificateBuilder()
            .subject_name(name)
            .issuer_name(name)
            .public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(moment - datetime.timedelta(minutes=5))
            .not_valid_after(moment + datetime.timedelta(days=365))
            .add_extension(x509.BasicConstraints(ca=True, path_length=0), critical=True)
            .add_extension(key_id, critical=False)
            .add_extension(x509.AuthorityKeyIdentifier.from_issuer_subject_key_identifier(key_id), critical=False)
            .add_extension(
                x509.KeyUsage(
                    digital_signature=True, content_commitment=False, key_encipherment=False,
                    data_encipherment=False, key_agreement=False, key_cert_sign=True,
                    crl_sign=False, encipher_only=False, decipher_only=False,
                ),
                critical=True,
            )
            .add_extension(
                x509.ExtendedKeyUsage([
                    x509.oid.ExtendedKeyUsageOID.SERVER_AUTH,
                    x509.oid.ExtendedKeyUsageOID.CLIENT_AUTH,
                ]),
                critical=False,
            )
            .add_extension(
                x509.SubjectAlternativeName([x509.UniformResourceIdentifier("sentra://peer")]),
                critical=False,
            )
            .sign(key, hashes.SHA256())
        )
        cert_path = directory / "cert.pem"
        key_path = directory / "key.pem"
        cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
        key_path.write_bytes(key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
        return cls(key, cert, cert_path=cert_path, key_path=key_path)

    @classmethod
    def load_or_create(cls, directory):
        directory = Path(directory)
        cert_path = directory / "cert.pem"
        key_path = directory / "key.pem"
        if cert_path.exists() != key_path.exists():
            raise RuntimeError("installation identity is incomplete")
        if not cert_path.exists():
            return cls.generate(directory)
        key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        return cls(key, cert, cert_path=cert_path, key_path=key_path)


def fingerprint_of_pem(pem: str):
    if not isinstance(pem, str) or len(pem) > 8192 or "BEGIN CERTIFICATE" not in pem:
        raise FederationDenied("peer certificate missing")
    if "PRIVATE" in pem:
        raise FederationDenied("peer certificate missing")
    try:
        cert = x509.load_pem_x509_certificate(pem.encode("ascii"))
    except (ValueError, UnicodeError) as exc:
        raise FederationDenied("peer certificate missing") from exc
    moment = _now()
    start = getattr(cert, "not_valid_before_utc", None)
    end = getattr(cert, "not_valid_after_utc", None)
    if start is None:
        start = cert.not_valid_before.replace(tzinfo=datetime.timezone.utc)
    if end is None:
        end = cert.not_valid_after.replace(tzinfo=datetime.timezone.utc)
    if start > moment or end < moment:
        raise FederationDenied("peer certificate is not valid")
    return hashlib.sha256(cert.public_bytes(serialization.Encoding.DER)).hexdigest(), cert
