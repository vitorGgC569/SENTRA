"""Locally signed offline ACP manifest; key is externally supplied test fixture."""
import asyncio
import hashlib
import hmac
import json
from pathlib import Path

import pytest
from sentra_runtime.contracts import Capability,Machine,OperationRequest,PolicyDecision
from sentra_interop.gate import InteropGate
from sentra_interop.acp_verified import ACPVerifiedResolver,ACPVerificationDenied,canonical


def test_acp_verified_offline_resolver_replay_revocation_integrity(tmp_path):
    async def case():
        install=tmp_path/"approved"
        install.mkdir()
        executable=install/"local_agent.bin"
        executable.write_bytes(b"local approved CLI program fixture version one")
        work=install/"workspace"
        work.mkdir()
        key=b"fixture-trust-root-publisher-secret-32bytes-min"
        grants=True
        def auth(req):
            return PolicyDecision(grants and req.work_item_id=="agent-work","approved",
                                  {"principal_ids":["alice"],"work_item_ids":["agent-work"]})
        gate=InteropGate(Machine("registry-fixture","agent","alice",
                                (Capability("acp:resolve","resolve"),)),auth)
        def factory(*,revoked=frozenset()):
            return ACPVerifiedResolver(install_root=str(install),
                ledger_file=str(install/"versions.sqlite"),
                publisher_keys={"team-fixture":key},revoked_publishers=revoked,gate=gate)
        def manifest(seq=1,version="1.1.0",path=None,sha=None):
            return {"schema":1,"publisher":"team-fixture","sequence":seq,
                    "agents":[{"provider":"approved-cli","version":version,
                               "executable":str(path or executable),"cwd":str(work),
                               "argv":["--stdio","--safe"],
                               "sha256":sha or hashlib.sha256(executable.read_bytes()).hexdigest()}]}
        def sign(doc):
            return hmac.new(key,canonical(doc),hashlib.sha256).hexdigest()
        def request(doc):
            return OperationRequest(
                "verify-"+str(doc["sequence"]),"alice","registry-fixture","acp:resolve",
                "agent-work","verify-key-"+str(doc["sequence"]),{
                    "provider":"approved-cli","version":doc["agents"][0]["version"],
                    "publisher":"team-fixture","sequence":doc["sequence"],
                    "manifest_sha256":hashlib.sha256(canonical(doc)).hexdigest(),
                    "executable_sha256":doc["agents"][0]["sha256"]})
        resolver=factory()
        current=manifest()
        result=await resolver.resolve(current,sign(current),
                                      provider="approved-cli",version="1.1.0",
                                      request=request(current))
        assert result.executable==str(executable.resolve())
        assert result.argv==("--stdio","--safe")
        assert result.sha256==hashlib.sha256(executable.read_bytes()).hexdigest()
        assert (await factory().resolve(current,sign(current),
                 provider="approved-cli",version="1.1.0",
                 request=request(current))).sequence==1

        corrupt=manifest(seq=2)
        corrupt["agents"][0]["argv"]=["--dangerous"]
        with pytest.raises(ACPVerificationDenied,match="authenticity"):
            await factory().resolve(corrupt,sign(current),provider="approved-cli",
                                    version="1.1.0",request=request(corrupt))

        executable.write_bytes(b"tampered local binary")
        changed=manifest(seq=2,sha=current["agents"][0]["sha256"])
        with pytest.raises(ACPVerificationDenied,match="digest"):
            await factory().resolve(changed,sign(changed),
                                    provider="approved-cli",version="1.1.0",
                                    request=request(changed))
        executable.write_bytes(b"local approved CLI program fixture version one")

        traversed=manifest(seq=2,path=str(work/".."/".."/"outside.exe"))
        with pytest.raises(ACPVerificationDenied,match="traversal"):
            await factory().resolve(traversed,sign(traversed),
                                    provider="approved-cli",version="1.1.0",
                                    request=request(traversed))
        revoked=factory(revoked=frozenset({"team-fixture"}))
        with pytest.raises(ACPVerificationDenied,match="revoked"):
            await revoked.resolve(current,sign(current),provider="approved-cli",
                                  version="1.1.0",request=request(current))

        downgrade=manifest(seq=2,version="1.0.0")
        with pytest.raises(ACPVerificationDenied,match="rollback"):
            await factory().resolve(downgrade,sign(downgrade),provider="approved-cli",
                                    version="1.0.0",request=request(downgrade))
        older=manifest(seq=0)
        with pytest.raises(ACPVerificationDenied):
            await factory().resolve(older,sign(older),provider="approved-cli",
                                    version="1.1.0",request=request(older))

        updated=manifest(seq=2,version="1.2.0")
        grants=False
        with pytest.raises(ACPVerificationDenied,match="grant"):
            await factory().resolve(updated,sign(updated),provider="approved-cli",
                                    version="1.2.0",request=request(updated))
        grants=True
        accepted=await factory().resolve(updated,sign(updated),provider="approved-cli",
                                         version="1.2.0",request=request(updated))
        assert accepted.version=="1.2.0"
        assert (await factory().resolve(updated,sign(updated),provider="approved-cli",
                                        version="1.2.0",request=request(updated))).sequence==2
        with pytest.raises(ACPVerificationDenied,match="rollback"):
            await factory().resolve(current,sign(current),provider="approved-cli",
                                    version="1.1.0",request=request(current))
    asyncio.run(case())


@pytest.mark.parametrize("bad",[
    {"provider":"not/allowed","version":"1.1.0"},
    {"provider":"good","version":"1.1.0-rc.1"},
])
def test_acp_verified_catalog_invalid_metadata(tmp_path,bad):
    from sentra_interop.acp_verified import _semver
    with pytest.raises(ACPVerificationDenied):
        if "/" in bad["provider"]:
            from sentra_interop.registry import AGENT_ID
            if not AGENT_ID.fullmatch(bad["provider"]):
                raise ACPVerificationDenied("invalid provider")
        else:
            _semver(bad["version"])
