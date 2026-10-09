"""Shared loopback-only JSON transport for opt-in policy decisions.

Never follows redirects or system proxy rules; never sends authorization tokens
to non-loopback destinations. No production TLS/remote federation is provided.
"""
from __future__ import annotations
import http.client
import json
import ssl
from urllib.parse import urlsplit, urlencode


class PolicyTransportUnavailable(PermissionError):
    pass


def strict_json(raw: bytes) -> dict:
    def pairs(items):
        data = {}
        for key, value in items:
            if key in data:
                raise PolicyTransportUnavailable("duplicate policy JSON field")
            data[key] = value
        return data
    try:
        obj = json.loads(raw.decode("utf-8"), object_pairs_hook=pairs,
                         parse_constant=lambda _: (_ for _ in ()).throw(
                             PolicyTransportUnavailable("nonfinite policy JSON")))
    except (ValueError, UnicodeError) as exc:
        raise PolicyTransportUnavailable("invalid policy JSON") from exc
    if not isinstance(obj, dict):
        raise PolicyTransportUnavailable("policy response is not an object")
    return obj


class LoopbackPolicyHTTP:
    def __init__(self, *, base: str, token: str, timeout_s: float = 1.5):
        value = urlsplit(base)
        if (value.scheme != "http" or value.hostname != "127.0.0.1"
                or value.username or value.password or value.query or value.fragment
                or value.path not in ("", "/") or value.port is None):
            raise ValueError("policy endpoint must be literal HTTP loopback + port")
        if (not isinstance(token, str) or not 24 <= len(token) <= 4096
                or any(c in token for c in "\r\n\x00")):
            raise ValueError("explicit trusted policy bearer secret required")
        if not 0 < timeout_s <= 10:
            raise ValueError("invalid policy timeout")
        self.port, self.token, self.timeout_s = value.port, token, timeout_s

    def post(self, path: str, payload: dict) -> dict:
        return self.request("POST",path,payload=payload)

    def get(self,path,*,params=None): return self.request("GET",path,params=params)
    def put(self,path,payload): return self.request("PUT",path,payload=payload,expected=(200,204))

    def request(self,method,path,*,payload=None,params=None,expected=(200,)):
        if (not isinstance(path, str) or not path.startswith("/")
                or "?" in path or "#" in path or ".." in path):
            raise ValueError("untrusted policy path")
        try:
            data = None if payload is None else json.dumps(payload, ensure_ascii=False, sort_keys=True,
                              allow_nan=False, separators=(",", ":")).encode()
            if data is not None and len(data) > 16_384:
                raise ValueError("oversized policy request")
        except (TypeError, OverflowError, RecursionError) as exc:
            raise ValueError("invalid policy request") from exc
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=self.timeout_s)
        try:
            connection.request(method, path+("?"+urlencode(params) if params else ""), body=data, headers={
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.token,
                "Accept": "application/json",
            })
            response = connection.getresponse()
            raw = response.read(32_769)
            if response.status not in expected or len(raw) > 32_768:
                raise PolicyTransportUnavailable("policy authority denied or unavailable")
            if not raw and response.status==204: return {}
            return strict_json(raw)
        except (OSError, TimeoutError, http.client.HTTPException) as exc:
            raise PolicyTransportUnavailable("policy authority unreachable") from exc
        finally:
            connection.close()


class PolicyHTTPStatus(PolicyTransportUnavailable):
    def __init__(self,status): self.status=status; super().__init__("identity/policy HTTP status "+str(status))


class PinnedProviderHTTP:
    """Explicit TLS or literal loopback HTTP; no proxy, redirects or retry.

    Construction performs no I/O. Every endpoint remains under the configured
    origin/path prefix. OAuth forms and response bodies never appear in errors.
    """
    def __init__(self,*,base,enabled=False,token=None,allow_loopback=False,timeout_s=3,max_response=1_000_000,tls_context=None):
        url=urlsplit(base)
        if (not enabled or url.scheme not in {"https","http"} or not url.hostname or url.username or url.password
            or url.query or url.fragment or ".." in url.path or url.scheme=="http" and
            (not allow_loopback or url.hostname not in {"127.0.0.1","::1"}) or not 0<timeout_s<=30
            or type(max_response) is not int or not 1024<=max_response<=8_000_000):
            raise ValueError("explicit pinned TLS/loopback provider required")
        if token is not None and (not isinstance(token,str) or not token or any(c in token for c in "\r\n\0")):
            raise ValueError("invalid provider bearer")
        self.base,self.url,self.token,self.timeout_s,self.max_response=base.rstrip("/"),url,token,timeout_s,max_response
        self.tls_context=tls_context or ssl.create_default_context()
        if self.tls_context.verify_mode!=ssl.CERT_REQUIRED or not self.tls_context.check_hostname:
            raise ValueError("provider TLS validation cannot be disabled")

    def request(self,method,path,*,payload=None,form=None,params=None,expected=(200,),bearer=None):
        if (method not in {"GET","POST","PUT"} or not isinstance(path,str) or not path.startswith("/")
            or any(c in path for c in "?#\r\n\0") or ".." in path or "\\" in path or payload is not None and form is not None):
            raise ValueError("invalid pinned provider request")
        headers={"Accept":"application/json"}
        secret=self.token if bearer is None else bearer
        if secret is not None:
            if not isinstance(secret,str) or any(c in secret for c in "\r\n\0"): raise ValueError("invalid bearer")
            headers["Authorization"]="Bearer "+secret
        body=None
        if payload is not None:
            body=json.dumps(payload,ensure_ascii=False,allow_nan=False,separators=(",",":")).encode()
            headers["Content-Type"]="application/json"
        if form is not None:
            if not isinstance(form,dict): raise ValueError("OAuth form must be an object")
            body=urlencode(form).encode(); headers["Content-Type"]="application/x-www-form-urlencoded"
        if body is not None and len(body)>1_000_000: raise ValueError("provider request exceeds bound")
        target=self.url.path.rstrip("/")+path+("?"+urlencode(params) if params else "")
        connection=(http.client.HTTPSConnection(self.url.hostname,self.url.port or 443,timeout=self.timeout_s,context=self.tls_context)
            if self.url.scheme=="https" else http.client.HTTPConnection(self.url.hostname,self.url.port or 80,timeout=self.timeout_s))
        try:
            connection.request(method,target,body=body,headers=headers)
            response=connection.getresponse(); raw=response.read(self.max_response+1)
            if response.status not in expected: raise PolicyHTTPStatus(response.status)
            if len(raw)>self.max_response: raise PolicyTransportUnavailable("provider response exceeds bound")
            if not raw and response.status in {200,204}: return {}
            return strict_json(raw)
        except (OSError,TimeoutError,http.client.HTTPException) as exc:
            raise PolicyTransportUnavailable("pinned provider unavailable; request not automatically replayed") from exc
        finally: connection.close()

    def post(self,path,payload): return self.request("POST",path,payload=payload)
    def get(self,path,*,params=None): return self.request("GET",path,params=params)
    def put(self,path,payload): return self.request("PUT",path,payload=payload,expected=(200,204))
