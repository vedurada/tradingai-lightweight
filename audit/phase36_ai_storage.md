# Historical AI Storage Verification — Phase 36
Generated: 2026-09-17

## ai_outlooks Table
- **Total records**: 26,028
- **Columns**: id, symbol, timestamp, outlook, data_quality
- **Latest**: COALINDIA, 2026-09-17T10:29:35Z, GOOD quality

### Field Mapping (ai_outlooks payload)
| Required Field | Present | Actual Field Name |
|---------------|---------|-------------------|
| timestamp | PRESENT | timestamp |
| instrument | MISSING | symbol |
| spot | MISSING | Not stored |
| direction | MISSING | directional_bias |
| confidence | PRESENT | confidence |
| regime | MISSING | market_structure |
| factors | MISSING | supporting_factors |
| support | MISSING | key_levels.supports |
| resistance | MISSING | key_levels.resistances |
| VWAP | MISSING | indicators.vwap |
| CPR | MISSING | Not stored |
| VIX | MISSING | vix_regime |
| options | MISSING | options_data_state |
| strategy | MISSING | preferred_strategy |
| entry | MISSING | entry_trigger |
| stop | MISSING | invalidation |
| target | MISSING | target_zone |

### Assessment
The ai_outlooks payload contains RICH data but uses non-standard field names.
All critical information is present but under different keys. The structure
is valid but doesn't match the required field names from Phase 36 Step 11.

## market_outlooks Table
- **Total records**: 202 (limited — backfill in progress)
- **Columns**: id, date, symbol, payload, created_at
- **Latest**: NIFTY 2026-09-17, created 2026-09-17 09:30:10

### Field Mapping (market_outcomes payload)
| Required Field | Present | Path |
|---------------|---------|------|
| date | PRESENT | date |
| instrument | PRESENT | symbol |
| confidence | PRESENT | confidence |
| regime | PRESENT | regime.primary |
| direction | MISSING | bias.label |
| factors | PRESENT | Multiple nested |
| support | PRESENT | key_levels.supports |
| resistance | PRESENT | key_levels.resistances |
| VWAP | PRESENT | indicators.vwap |
| CPR | MISSING | Not stored |
| VIX | PRESENT | vix (object) |
| options | PRESENT | Multiple nested |
| strategy | PRESENT | strategies[0].name |
| entry | PRESENT | strategies[0].entry |
| stop | PRESENT | strategies[0].risk |
| target | PRESENT | strategies[0].exit |

### Assessment
market_outcomes has comprehensive data with standard-ish naming. 202 records
is insufficient for 30-day analysis per instrument (need ~30 × 4 = 120 minimum).
CPR is the only truly missing field.

## Recommendation
Document field name differences but do NOT redesign yet (per Phase 36 instructions).
The data exists and is accessible via /api/market-outlooks and /api/market-outlook.
Field name standardization is a Phase 37+ concern.
