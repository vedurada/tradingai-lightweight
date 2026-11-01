#!/usr/bin/env bash
# Temporary Phase 5 evidence collection wrapper.
# Tag: PHASE5_ENTRY_CAPTURE_CRON
set -u

PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
export TZ=Asia/Kolkata

SCRIPT="/opt/tradingai/scripts/phase5_audit.py"
EXPECTED_SHA="e9b5eb03dc07bde7612f3370f159ed9adecabdcbeefa5f6496c655df4031d0bd"
DEFAULT_OUT_DIR="/opt/tradingai/reports"
LOG_DIR="/opt/tradingai/logs/phase5_cron"
LOCK_FILE="${LOG_DIR}/phase5_cron.lock"

DATE=""
STAGE=""
OUT_DIR="${DEFAULT_OUT_DIR}"
DRY_RUN=0

usage() {
    echo "Usage: $0 --stage pre|post|daily [--date YYYY-MM-DD] [--out-dir DIR] [--dry-run]" >&2
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        --date) DATE="${2:-}"; shift 2 ;;
        --stage) STAGE="${2:-}"; shift 2 ;;
        --out-dir) OUT_DIR="${2:-}"; shift 2 ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) echo "Unknown argument: $1" >&2; usage; exit 2 ;;
    esac
done

mkdir -p "${LOG_DIR}"
LOG_FILE="${LOG_DIR}/phase5_cron.log"
RUN_ID="$(date '+%Y%m%dT%H%M%S')-${STAGE:-unknown}-$$"
TMP_OUT="${LOG_DIR}/.${RUN_ID}.out"
: > "${TMP_OUT}"

log() {
    printf '%s %s\n' "$(date '+%Y-%m-%dT%H:%M:%S%z')" "$*" >> "${LOG_FILE}"
}

finish() {
    local rc="$1"
    {
        printf '%s FINISH run=%s stage=%s date=%s exit_code=%s\n' \
            "$(date '+%Y-%m-%dT%H:%M:%S%z')" "${RUN_ID}" "${STAGE:-unknown}" "${DATE:-unset}" "${rc}"
        printf '%s\n' "----- output begin -----"
        cat "${TMP_OUT}"
        printf '%s\n' "----- output end -----"
    } >> "${LOG_FILE}"
    rm -f "${TMP_OUT}"
    exit "${rc}"
}

log "START run=${RUN_ID} stage=${STAGE:-unset} date=${DATE:-unset} dry_run=${DRY_RUN} out_dir=${OUT_DIR}"

# Timezone check.
if [[ "$(date +%Z)" != "IST" ]]; then
    echo "Timezone check failed: expected IST, got $(date +%Z)" >> "${TMP_OUT}"
    log "FAIL run=${RUN_ID} reason=timezone_check_failed actual=$(date +%Z)"
    finish 1
fi

# Default to today's IST date when not supplied.
if [[ -z "${DATE}" ]]; then
    DATE="$(date '+%Y-%m-%d')"
fi

# Date syntax and exact Phase 5 window.
if [[ ! "${DATE}" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]]; then
    echo "Invalid date: ${DATE}" >> "${TMP_OUT}"
    log "FAIL run=${RUN_ID} reason=invalid_date date=${DATE}"
    finish 2
fi
if [[ "${DATE}" < "2026-11-02" || "${DATE}" > "2026-11-06" ]]; then
    echo "Date outside Phase 5 window: ${DATE}" >> "${TMP_OUT}"
    log "SKIP run=${RUN_ID} reason=date_outside_phase5_window date=${DATE}"
    finish 0
fi

# Stage validation.
case "${STAGE}" in
    pre|post|daily) ;;
    *)
        echo "Invalid stage: ${STAGE}" >> "${TMP_OUT}"
        log "FAIL run=${RUN_ID} reason=invalid_stage stage=${STAGE}"
        finish 2
        ;;
esac

# Audit script hash check.
ACTUAL_SHA="$(sha256sum "${SCRIPT}" | awk '{print $1}')"
if [[ "${ACTUAL_SHA}" != "${EXPECTED_SHA}" ]]; then
    echo "Audit script hash mismatch: expected ${EXPECTED_SHA}, got ${ACTUAL_SHA}" >> "${TMP_OUT}"
    log "FAIL run=${RUN_ID} reason=script_hash_mismatch expected=${EXPECTED_SHA} actual=${ACTUAL_SHA}"
    finish 1
fi

# Expected destination and no-overwrite check.
DAY_COMPACT="${DATE//-/}"
case "${STAGE}" in
    pre)
        EXPECTED_FILE="${OUT_DIR}/phase5_counts_${DAY_COMPACT}_pre.json"
        ;;
    post)
        EXPECTED_FILE="${OUT_DIR}/phase5_counts_${DAY_COMPACT}_post.json"
        ;;
    daily)
        EXPECTED_MD="${OUT_DIR}/phase5_daily_${DAY_COMPACT}.md"
        EXPECTED_JSON="${OUT_DIR}/phase5_daily_${DAY_COMPACT}.json"
        ;;
esac

if [[ "${STAGE}" == "daily" ]]; then
    if [[ -e "${EXPECTED_MD}" || -e "${EXPECTED_JSON}" ]]; then
        echo "Existing daily evidence preserved: ${EXPECTED_MD} or ${EXPECTED_JSON}" >> "${TMP_OUT}"
        log "SKIP run=${RUN_ID} reason=existing_daily_evidence md=${EXPECTED_MD} json=${EXPECTED_JSON}"
        finish 0
    fi
else
    if [[ -e "${EXPECTED_FILE}" ]]; then
        echo "Existing snapshot preserved: ${EXPECTED_FILE}" >> "${TMP_OUT}"
        log "SKIP run=${RUN_ID} reason=existing_snapshot file=${EXPECTED_FILE}"
        finish 0
    fi
fi

# Concurrency lock.
exec 9>"${LOCK_FILE}"
if ! flock -n 9; then
    echo "Another Phase 5 cron run is in progress; skipping" >> "${TMP_OUT}"
    log "SKIP run=${RUN_ID} reason=concurrent_run lock=${LOCK_FILE}"
    finish 0
fi

if [[ "${DRY_RUN}" -eq 1 ]]; then
    echo "Dry-run validation passed; no collection executed" >> "${TMP_OUT}"
    echo "date=${DATE} stage=${STAGE} out_dir=${OUT_DIR}" >> "${TMP_OUT}"
    log "DRY-RUN run=${RUN_ID} validation=passed date=${DATE} stage=${STAGE}"
    finish 0
fi

# Build and execute the exact read-only audit command.
case "${STAGE}" in
    pre)
        CMD=(/usr/bin/python3 "${SCRIPT}" --date "${DATE}" --snapshot pre --out-dir "${OUT_DIR}")
        ;;
    post)
        CMD=(/usr/bin/python3 "${SCRIPT}" --date "${DATE}" --snapshot post --out-dir "${OUT_DIR}")
        ;;
    daily)
        CMD=(/usr/bin/python3 "${SCRIPT}" --date "${DATE}" --out-dir "${OUT_DIR}")
        ;;
esac

log "EXEC run=${RUN_ID} command=${CMD[*]}"
set +e
"${CMD[@]}" > "${TMP_OUT}" 2>&1
RC=$?
set -e

if [[ "${RC}" -ne 0 ]]; then
    echo "Collection command failed with exit code ${RC}" >> "${TMP_OUT}"
    log "FAIL run=${RUN_ID} reason=collection_failed exit_code=${RC}"
else
    log "SUCCESS run=${RUN_ID} exit_code=0"
fi

finish "${RC}"
