"""Observed account usage is stale/unknown on account changes, not billing ledger."""
import hashlib

import pytest

from sentra_mcp.services.web_history_usage import WebQuotaObservations, WebQuotaConflict


def test_quota_account_separation_stale_reset_restart(tmp_path):
    now=[1_800_000_000.]
    store=WebQuotaObservations(tmp_path,clock=lambda:now[0])
    account=hashlib.sha256(b"opaque-account-one").hexdigest()
    other=hashlib.sha256(b"opaque-account-two").hexdigest()
    args=dict(owner="quota-owner",workspace="project-workspace",
              account_fingerprint=account,quota_bucket="gpt-web",
              remaining_percent=65,observed_at=now[0]-10,
              resets_at=now[0]+300,collector_ref="collector-12345")
    first=store.observe(**args)
    assert first["status"]=="fresh"
    assert first["remaining_percent"]==65
    assert first["trusted_account_proof"] is False
    assert first["sentra_token_ledger_equivalent"] is False
    with pytest.raises(WebQuotaConflict):
        store.observe(**{**args,"observed_at":now[0]-20})
    with pytest.raises(WebQuotaConflict):
        store.observe(**{**args,"remaining_percent":20})
    assert store.latest(args["owner"],args["workspace"],other,"gpt-web")["status"]=="unknown"
    restarted=WebQuotaObservations(tmp_path,clock=lambda:now[0])
    assert restarted.latest(args["owner"],args["workspace"],account,"gpt-web")["remaining_percent"]==65
    now[0]+=120
    assert restarted.latest(args["owner"],args["workspace"],account,"gpt-web",max_age_s=30)["status"]=="stale"
    now[0]+=250
    assert restarted.latest(args["owner"],args["workspace"],account,"gpt-web")["status"]=="stale"


def test_quota_input_validation(tmp_path):
    store=WebQuotaObservations(tmp_path,clock=lambda:1_800_000_000.)
    args=dict(owner="owner",workspace="workspace",
              account_fingerprint="a"*64,quota_bucket="standard",
              remaining_percent=70.0,observed_at=1_800_000_000.,
              resets_at=None,collector_ref="collector-123")
    with pytest.raises(ValueError):
        store.observe(**{**args,"account_fingerprint":"user@example.com"})
    with pytest.raises(ValueError):
        store.observe(**{**args,"remaining_percent":float("nan")})
    with pytest.raises(ValueError):
        store.observe(**{**args,"remaining_percent":101.0})
    with pytest.raises(ValueError):
        store.observe(**{**args,"observed_at":1_900_000_000.})
    with pytest.raises(ValueError):
        store.observe(**{**args,"source":"sentra_budget"})
