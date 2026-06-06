"""
Quick TDX connectivity diagnostic.
Run: python debug_tdx.py
"""
import json, os, ssl, urllib.parse, urllib.request

def _load_env():
    try:
        with open(".env", encoding="utf-8-sig") as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    k, v = line.split("=", 1)
                    os.environ.setdefault(k.strip(), v.strip())
    except FileNotFoundError:
        print("ERROR: .env file not found")
        return

_load_env()

client_id = os.environ.get("TDX_CLIENT_ID", "")
client_secret = os.environ.get("TDX_CLIENT_SECRET", "")
print(f"TDX_CLIENT_ID     : {'SET (' + client_id[:6] + '...)' if client_id else 'NOT SET'}")
print(f"TDX_CLIENT_SECRET : {'SET' if client_secret else 'NOT SET'}")

_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode    = ssl.CERT_NONE

# ── Step 1: token ─────────────────────────────────────────────────────────────
print("\n--- Step 1: token fetch ---")
token = None
try:
    data = urllib.parse.urlencode({
        "grant_type":    "client_credentials",
        "client_id":     client_id,
        "client_secret": client_secret,
    }).encode()
    req = urllib.request.Request(
        "https://tdx.transportdata.tw/auth/realms/TDXConnect/protocol/openid-connect/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=15, context=_SSL) as r:
        body = json.loads(r.read())
    token = body["access_token"]
    print(f"OK — token: {token[:20]}...")
except urllib.error.HTTPError as e:
    print(f"FAILED — HTTP {e.code}: {e.reason}")
    print(f"  Response body: {e.read().decode()}")
except Exception as e:
    print(f"FAILED — {type(e).__name__}: {e}")

if not token:
    print("\nCannot proceed without a token.")
    raise SystemExit(1)

# ── Step 2: Metro Line endpoint ───────────────────────────────────────────────
print("\n--- Step 2: /Rail/Metro/Line/TRTC ---")
for base in [
    "https://tdx.transportdata.tw/api/basic/v2",
    "https://tdx.transportdata.tw/api/basic/v3",
]:
    url = f"{base}/Rail/Metro/Line/TRTC?$top=10&$format=JSON"
    print(f"  trying {url}")
    try:
        req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
        with urllib.request.urlopen(req, timeout=15, context=_SSL) as r:
            data = json.loads(r.read())
        print(f"  OK — {len(data)} items, first keys: {list(data[0].keys()) if data else '(empty)'}")
        break
    except urllib.error.HTTPError as e:
        body = e.read().decode()
        print(f"  FAILED — HTTP {e.code}: {body[:200]}")
    except Exception as e:
        print(f"  FAILED — {type(e).__name__}: {e}")
