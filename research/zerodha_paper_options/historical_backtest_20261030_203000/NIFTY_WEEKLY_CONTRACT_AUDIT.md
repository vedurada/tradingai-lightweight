# NIFTY Weekly Option Contract Audit (2026-10-30)
Instrument master (NSE) accessible via SDK with valid auth.
NIFTY 50 EQ token identified: 256265.
Option contracts: master contains NIFTY option listings but exact tradingsymbol filter requires precise format (strike-included symbol may vary by master format).
Nearest expiry: not confirmed without precise option master filter.
CE/PE contracts: not definitively mapped without exact symbol verification.
Recommendation: After token refresh, filter master using exact option symbol patterns (e.g., "NIFTY 50" + strike + CE/PE) or request master for specific instrument tokens to identify nearest weekly expiry.
No contracts downloaded; no fabricated contracts.
