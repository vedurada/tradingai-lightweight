# Phase 42A — Research Exports Design

**Date**: 2026-09-17
**Phase 41**: FROZEN

---

## Design Requirements

1. Research data must be exportable for analysis
2. Raw research tables must NOT be publicly accessible
3. Exports must be controlled and read-only
4. CSV or SQLite format
5. All records must retain source IDs
6. Export must be reproducible

## Export Mechanism

### Backend API (Read-Only Research Endpoints)

| Endpoint | Description | Access |
|----------|-------------|--------|
| /api/research/data-health | Research data health summary | Internal |
| /api/research/coverage | Dataset coverage report | Internal |
| /api/research/ai-history | AI call history | Internal |
| /api/research/setups | Setup identity records | Internal |
| /api/research/reentries | Re-entry log | Internal |
| /api/research/outcomes | Outcome tracking | Internal |
| /api/research/manifest | Dataset manifest | Internal |
| /api/research/summary | Overall summary | Internal |

### Local Export Scripts

Research data can also be exported locally for analysis:
- SQLite dump of research tables
- CSV export per table
- JSON export per record set

## Research Datasets

| Dataset | Source Table | Description |
|---------|-------------|-------------|
| market_snapshot_research | market_snapshots_5m | 5-minute snapshots |
| evidence_research | market_evidence_5m | Evidence evaluations |
| ai_outlook_research | ai_outlooks_5m | AI outlook records |
| qualification_research | paper_trades | Trade qualifications |
| paper_trade_research | paper_trades | Paper trade lifecycle |
| outcome_research | research_outcome_tracking | Future outcomes |
| setup_research | research_setup_identity | Setup identity records |

## Export Schema Documentation

Each export includes:
- All columns from source table
- Data quality flags
- Engine version
- Timestamps (decision time and creation time)
- Source IDs linking to production records

## Security

- No public API exposes raw research data
- No credentials in exports
- No AI prompts in exports
- No internal DB structure exposed
- Only authorized users can access research endpoints

## Reproducibility

Each export includes:
- Schema version
- Engine version
- Generated timestamp
- Row count verification
- Data quality summary
