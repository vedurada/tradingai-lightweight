#!/usr/bin/env bash
# Remove only uniquely tagged Phase 5 cron entries.
# Tag: PHASE5_ENTRY_CAPTURE_CRON
set -u

PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export TZ=Asia/Kolkata
LOG_DIR="/opt/tradingai/logs/phase5_cron"
TAG="PHASE5_ENTRY_CAPTURE_CRON"

mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/phase5_cron_cleanup.log"

# The cleanup is intentionally one-time for 2026-11-07.
if [[ "$(date '+%Y-%m-%d')" != "2026-11-07" ]]; then
    printf '%s SKIP cleanup date=%s (not 2026-11-07)\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$(date '+%Y-%m-%d')" >> "${LOG_FILE}"
    exit 0
fi

CURRENT="$(mktemp "${LOG_DIR}/.crontab.XXXXXX")"
FILTERED="$(mktemp "${LOG_DIR}/.crontab.filtered.XXXXXX")"
trap 'rm -f "${CURRENT}" "${FILTERED}"' EXIT

if ! crontab -l > "${CURRENT}" 2>/dev/null; then
    printf '%s SKIP no crontab for current user\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" >> "${LOG_FILE}"
    exit 0
fi

# Remove every cron line containing the unique Phase 5 tag.
grep -v -F "${TAG}" "${CURRENT}" > "${FILTERED}" || true

# Preserve unrelated entries. If filtering fails to produce a valid file, do nothing.
if [[ ! -f "${FILTERED}" ]]; then
    printf '%s FAIL filtered crontab missing\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" >> "${LOG_FILE}"
    exit 1
fi

REMOVED_COUNT="$(grep -F -c "${TAG}" "${CURRENT}" || true)"
crontab "${FILTERED}"
printf '%s SUCCESS removed_tagged_entries=%s preserved_other_entries=%s\n' \
    "$(date '+%Y-%m-%dT%H:%M:%S%z')" "${REMOVED_COUNT}" "$(wc -l < "${FILTERED}")" >> "${LOG_FILE}"
exit 0
