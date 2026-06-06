"""
TDX (Transport Data eXchange) authentication and HTTP helper.
Credentials are read from environment variables:
    TDX_CLIENT_ID
    TDX_CLIENT_SECRET
"""
import json
import os
import ssl
import time
import urllib.parse
import urllib.request

TDX_TOKEN_URL = "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token"
TDX_BASE      = "https://tdx.transportdata.tw/api/basic/v2"

# TDX's cert chain has a non-critical Basic Constraints extension that
# Python 3.14's stricter OpenSSL rejects.
_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode    = ssl.CERT_NONE

_token_cache: dict = {"token": None, "expires_at": 0.0}


def get_token() -> str:
    if time.time() < _token_cache["expires_at"] - 60:
        return _token_cache["token"]

    data = urllib.parse.urlencode({
        "grant_type":    "client_credentials",
        "client_id":     os.environ["TDX_CLIENT_ID"],
        "client_secret": os.environ["TDX_CLIENT_SECRET"],
    }).encode()
    req = urllib.request.Request(
        TDX_TOKEN_URL, data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=15, context=_SSL) as r:
        body = json.loads(r.read())

    _token_cache["token"]      = body["access_token"]
    _token_cache["expires_at"] = time.time() + body.get("expires_in", 86400)
    return _token_cache["token"]


def get(path: str, top: int = 5000) -> list:
    """GET a TDX endpoint, return parsed JSON list."""
    url = f"{TDX_BASE}{path}?$top={top}&$format=JSON"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {get_token()}"})
    with urllib.request.urlopen(req, timeout=30, context=_SSL) as r:
        return json.loads(r.read())
