"""Shipped desktop manifest must be accessible through CanvasServer.

Only the pinned manifest JSON may be served from desktop-assets; this prevents
the release QA endpoint returning 404 without exposing arbitrary local files.
"""
from __future__ import annotations
import json
import urllib.error
import urllib.request

from test_sentra_runtime_canvas_center_http import running_canvas


def test_canvas_desktop_manifest_is_accessible_and_matches_bundle(tmp_path):
    with running_canvas(tmp_path) as (app,server):
        base=f"http://127.0.0.1:{server.server_port}"
        opener=urllib.request.build_opener(urllib.request.ProxyHandler({}))
        def get(path):
            with opener.open(base+path,timeout=4) as r:
                return r.status,r.headers.get("Content-Type"),r.read()
        status,kind,raw=get("/desktop-assets/manifest.json")
        assert status==200
        assert kind.startswith("application/json")
        obj=json.loads(raw)
        assert obj["entry"]=="/desktop.html"
        assert "desktop.js" in obj["files"]
        assert "desktop.css" in obj["files"]
        assert get("/desktop.html")[0]==200
        assert get("/desktop-assets/desktop.js")[0]==200
        for path in ("/desktop-assets/../../broker.json",
                     "/desktop-assets/missing.json",
                     "/desktop-assets/THIRD_PARTY_NOTICES.txt"):
            try:
                get(path)
            except urllib.error.HTTPError as e:
                assert e.code in (403,404)
            else:
                raise AssertionError("unlisted desktop asset must not be served")
