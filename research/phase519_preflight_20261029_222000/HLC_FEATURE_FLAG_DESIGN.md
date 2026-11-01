# Phase 5.19 — HLC Feature Flag Design (Not Implemented)

## Flag: HLC_ONLY_MODE

### Specification
- Name: HLC_ONLY_MODE
- Default: false (CPR-driven)
- Type: Boolean string
- Source: Environment variable (primary) or config/settings.json (fallback)
- Missing → false
- Invalid → false
- Unreadable → false

### Fail-Safe Behavior
- Default to CPR behavior on any failure
- Log warning, continue operation
- No error raised

### Mode Behavior
- false: _cpr_book_signal() for new decisions (current)
- true: _hlc_book_signal() for new decisions (future)

### One Trade-Initiation Path Per Mode
- Only one engine initiates new trades in each mode
- No second independent path

### Existing Trades
- Remain manageable during mode switch
- monitor() handles both scalp and CPR branches
- Exit logic determined by scenario field, not flag

### Broker Execution
- Remains unavailable in both modes
- Paper trading only

### Startup Validation
- Read flag at startup
- Log mode selection
- Validate configuration

### Rollback
- Set flag to false, restart gunicorn
- CPR resumes as default
- No trade history deleted
