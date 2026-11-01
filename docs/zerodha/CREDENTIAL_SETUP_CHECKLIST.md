# Secure Credential Setup — Zeroda Kite Connect (Phase 4C)

## Required protected variables (exact names; do NOT show values)
- KITE_API_KEY
- KITE_API_SECRET
- KITE_ACCESS_TOKEN (if using token-based session)
- ZERODHA_MODE = SHADOW (must remain SHADOW until separate authorization)

## File location (protected, never in Git)
- /opt/tradingai/.env.zerodha

## Setup steps (offline, no secrets in chat)
1. Obtain real credentials from Zerodha Kite Connect developer portal.
2. Create /opt/tradingai/.env.zerodha with correct format.
3. Set file permissions: chmod 600
4. Verify .env.zerodha is excluded from Git (check .gitignore).
5. Restart SHADOW engine; authenticate.
6. Validate instrument master access.
7. Only after 3 full SHADOW sessions and explicit approval, consider PAPER activation.

## Security rules
- Never print values.
- Never commit file.
- Never invent fake values.
- Never attempt auth with fabricated credentials.
