# TradingAI — Unattended Monitor Hardening: Nginx Permission Investigation

## Phase
#TradingAI — Unattended Monitor Hardening, Validation & Enablement Readiness

## Finding
- `nginx -t` failed: `cannot load certificate "/etc/letsencrypt/live/tradingai.in/fullchain.pem": Permission denied`.
- Directive: TLS certificate include/load.
- Path: /etc/letsencrypt/live/tradingai.in/fullchain.pem (+ privkey).
- Service state: `nginx` is `active` (running); config test as current user failed on cert read.

## Status
INVESTIGATED (NOT_CHANGED)
