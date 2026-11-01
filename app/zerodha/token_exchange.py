"""Official Kite Connect token exchange - server-side only"""
import os, sys
with open("/opt/tradingai/.env.zerodha") as f:
    cfg = {}
    for line in f:
        if "=" in line and not line.startswith("#"):
            k,v = line.strip().split("=",1)
            cfg[k]=v
try:
    with open("/tmp/request_token.txt") as f:
        request_token = f.read().strip()
except Exception:
    print("ERROR: /tmp/request_token.txt missing. Complete browser login first.")
    sys.exit(1)
from kiteconnect import KiteConnect
kc = KiteConnect(api_key=cfg["KITE_API_KEY"])
try:
    data = kc.generate_session(request_token, cfg["KITE_API_SECRET"])
    new_token = data.get("access_token")
    if not new_token:
        print("ERROR: no access_token")
        sys.exit(1)
    with open("/opt/tradingai/.env.zerodha", "w") as out:
        out.write("ZERODHA_MODE=SHADOW\n")
        key = cfg["KITE_API_KEY"]
        secret = cfg["KITE_API_SECRET"]
        out.write("KITE_API_KEY=" + key + "\n")
        out.write("KITE_API_SECRET=" + secret + "\n")
        out.write("KITE_ACCESS_TOKEN=" + new_token + "\n")
        out.write("REDIRECT_URL=https://tradingai.in\n")
    os.chmod("/opt/tradingai/.env.zerodha", 0o600)
    print("OK: New access token stored securely (value hidden)")
except Exception as e:
    print("ERROR: generate_session failed", type(e).__name__)
    sys.exit(1)
