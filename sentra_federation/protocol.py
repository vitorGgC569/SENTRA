"""Signed envelopes and the websocket frame codec used on the mutual TLS channel."""
from __future__ import annotations

import base64
import hashlib
import json
import os

from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives import hashes

from .errors import FederationDenied, FederationUncertain
from .identity import fingerprint_of_pem

GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
KINDS = {"hello", "pair.confirm", "chat", "canvas", "delegate", "review", "reconcile", "revoke"}
SECRET_MARKERS = ("begin private key", "begin openssh private key", "begin rsa private key")
MAX_FRAME = 65536


def canonical(value) -> bytes:
    try:
        return json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise FederationDenied("frame is not a bounded document") from exc


def confirmation_code(left: str, right: str) -> str:
    if not isinstance(left, str) or not isinstance(right, str) or len(left) != 64 or len(right) != 64:
        raise FederationDenied("confirmation requires both fingerprints")
    digest = hashlib.sha256("\n".join(sorted((left, right))).encode("ascii")).hexdigest()
    return "-".join(digest[i:i + 4] for i in range(0, 16, 4))


def reject_secrets(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise FederationDenied("forbidden field")
            lowered = key.lower()
            if any(word in lowered for word in ("sqlite", "private_key", "password", "api_key", "secret", "credential", "token")):
                raise FederationDenied("forbidden field")
            reject_secrets(item)
        return value
    if isinstance(value, list):
        if len(value) > 64:
            raise FederationDenied("frame is not a bounded document")
        for item in value:
            reject_secrets(item)
        return value
    if isinstance(value, str):
        lowered = value.lower()
        if any(marker in lowered for marker in SECRET_MARKERS) or ".sqlite" in lowered:
            raise FederationDenied("forbidden material")
        return value
    if value is None or type(value) in (int, float, bool):
        return value
    raise FederationDenied("frame is not a bounded document")


def signed_frame(identity, fields, clock):
    body = dict(fields)
    body["schema"] = 1
    body["from"] = identity.node_id
    body["sent_at"] = int(clock())
    if body.get("kind") not in KINDS:
        raise FederationDenied("unknown message kind")
    unsigned = canonical(body)
    if len(unsigned) > MAX_FRAME:
        raise FederationDenied("frame exceeds limit")
    body["signature"] = identity.sign(unsigned)
    return body


def verify_frame(frame, *, clock, skew_seconds=300):
    if not isinstance(frame, dict) or set(frame) < {"schema", "kind", "from", "sent_at", "signature"}:
        raise FederationDenied("unsigned frame")
    if frame.get("schema") != 1 or frame.get("kind") not in KINDS:
        raise FederationDenied("unknown message kind")
    if type(frame.get("sent_at")) is not int or abs(int(clock()) - frame["sent_at"]) > skew_seconds:
        raise FederationDenied("stale frame")
    signature = frame.get("signature")
    if not isinstance(signature, str) or not 64 <= len(signature) <= 200:
        raise FederationDenied("unsigned frame")
    unsigned = {key: value for key, value in frame.items() if key != "signature"}
    reject_secrets({key: value for key, value in unsigned.items() if key != "body"})
    if "body" in unsigned:
        reject_secrets(unsigned["body"])
    raw = canonical(unsigned)
    material = (unsigned.get("body") or {}) if isinstance(unsigned.get("body"), dict) else {}
    pem = material.get("cert_pem") if unsigned["kind"] == "hello" else None
    return raw, signature, pem


def verify_signature(raw, signature, cert):
    try:
        cert.public_key().verify(base64.b64decode(signature, validate=True), raw, ec.ECDSA(hashes.SHA256()))
    except Exception as exc:
        raise FederationDenied("peer signature rejected") from exc


def node_id_for(fingerprint: str) -> str:
    return "sentra-" + fingerprint[:32]


def presented_identity(frame, *, clock):
    raw, signature, pem = verify_frame(frame, clock=clock)
    if frame["kind"] == "hello":
        fingerprint, cert = fingerprint_of_pem(pem)
        if frame.get("body", {}).get("fingerprint") != fingerprint:
            raise FederationDenied("identity binding")
    else:
        raise FederationDenied("identity binding")
    if frame["from"] != node_id_for(fingerprint):
        raise FederationDenied("identity binding")
    verify_signature(raw, signature, cert)
    return fingerprint, cert


def verify_known(frame, cert_pem, *, clock):
    raw, signature, _pem = verify_frame(frame, clock=clock)
    fingerprint, cert = fingerprint_of_pem(cert_pem)
    if frame["from"] != node_id_for(fingerprint):
        raise FederationDenied("identity binding")
    verify_signature(raw, signature, cert)
    return fingerprint


class FrameReader:
    def __init__(self, sock, limit=MAX_FRAME + 64):
        self.sock = sock
        self.buf = b""
        self.limit = limit

    def _pull(self, size):
        while len(self.buf) < size:
            chunk = self.sock.recv(min(8192, max(1, size - len(self.buf))))
            if not chunk:
                raise FederationUncertain("link closed")
            self.buf += chunk
            if len(self.buf) > self.limit:
                raise FederationDenied("frame exceeds limit")

    def read_until(self, marker, limit):
        while marker not in self.buf:
            chunk = self.sock.recv(1024)
            if not chunk:
                raise FederationUncertain("link closed")
            self.buf += chunk
            if len(self.buf) > limit:
                raise FederationDenied("handshake exceeds limit")
        index = self.buf.index(marker) + len(marker)
        data, self.buf = self.buf[:index], self.buf[index:]
        return data

    def read(self, size):
        self._pull(size)
        data, self.buf = self.buf[:size], self.buf[size:]
        return data


def encode_frame(payload: bytes, *, mask: bool) -> bytes:
    if len(payload) > MAX_FRAME:
        raise FederationDenied("frame exceeds limit")
    header = bytearray([0x81])
    mask_bit = 0x80 if mask else 0
    length = len(payload)
    if length < 126:
        header.append(mask_bit | length)
    else:
        header.append(mask_bit | 126)
        header.extend(length.to_bytes(2, "big"))
    if mask:
        key = os.urandom(4)
        header.extend(key)
        payload = bytes(byte ^ key[index % 4] for index, byte in enumerate(payload))
    return bytes(header) + payload


def decode_frame(reader: FrameReader, *, expect_mask: bool) -> bytes:
    first = reader.read(2)
    if first[0] != 0x81:
        raise FederationDenied("only a single text frame is accepted")
    masked = bool(first[1] & 0x80)
    if masked != expect_mask:
        raise FederationDenied("websocket mask rejected")
    length = first[1] & 0x7F
    if length == 127:
        raise FederationDenied("frame exceeds limit")
    if length == 126:
        length = int.from_bytes(reader.read(2), "big")
    if length > MAX_FRAME:
        raise FederationDenied("frame exceeds limit")
    key = reader.read(4) if masked else b""
    payload = reader.read(length)
    if masked:
        payload = bytes(byte ^ key[index % 4] for index, byte in enumerate(payload))
    return payload


def accept_key(key: str) -> str:
    digest = hashlib.sha1((key + GUID).encode("ascii")).digest()
    return base64.b64encode(digest).decode("ascii")


def message_target(path: str) -> None:
    if type(path) is not str or path != "/sentra-peer" or "sqlite" in path.lower():
        raise FederationDenied("peer gateway serves only the message channel")
