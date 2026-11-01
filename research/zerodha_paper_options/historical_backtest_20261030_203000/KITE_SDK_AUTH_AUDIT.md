# SDK Auth Audit (2026-10-30)
SDK: kiteconnect 5.2.2 (verified import)
Methods verified: KiteConnect(), historical_data(), instruments(), generate_session(), renew_access_token(), login_url(), set_access_token(), access_token, session_expiry_hook
Constructor: KiteConnect(api_key)
Session: set_access_token(access_token)
Historical: historical_data(instrument_token, from_date, to_date, interval, continuous, oi)
Exception class: TokenException (verified on historical call)
No fabricated methods used.
