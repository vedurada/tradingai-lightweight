# TokenException Diagnosis (2026-10-30)
Exception: TokenException — Incorrect api_key or access_token
Evidence: historical_data(256265, 2026-10-29, 2026-10-30, 5minute) with real credentials returned TokenException.
Likely causes evaluated:
- Access token expired/invalid (most likely; token was configured previously, not freshly generated)
- Incorrect api_key/access_token pairing (credentials verified against master load; master worked)
- Token generated for different application (possible; requires fresh login to confirm)
- System timestamp out of sync (possible; not verified)
- API entitlement limitation (possible; historical endpoint often requires fresh session)
Not caused by: SDK bug (method exists and works; error is server-side auth rejection), missing SDK, incorrect method call.
Resolution required: Official login/token refresh via configured redirect URL (https://tradingai.in) using generate_session() with request_token.
No retries performed without fresh token.
