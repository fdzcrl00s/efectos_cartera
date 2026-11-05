# Changelog

## 18.0.4.3.1 (candidate) — 2026-11-05

- Automatic initial grouping move on effect addition / grouping save when the bank or cash journal can be inferred.
- Added explicit grouping confirmation and initial-entry recovery actions when a journal must be selected.
- Grouping actions consistently open the portfolio effect projection, reducing duplicate form routes.
- Grouping reference changes update the initial accounting entry.
- Remittance partial wizard no longer allows empty selection rows; effect references are preserved and amount totals use allocation-aware pending balances.
- Return availability is based on paid allocations net of prior returns, not solely on the individual effect state. This supports grouped effects whose invoice remains open until the entire group is settled.
- Returned amounts are stored against the original effect to prevent repeated returns; remaining unpaid balances stay active.
- Remittance annul/return buttons follow posted payment history and returnable allocations.
- Static validation passed (Python compile, XML parse, access CSV and manifest references). No live Odoo 18 installation/database tests were available.

## 18.0.4.3.0 (candidate) — 2026-11-04

- Initial grouping and consolidated settlement flow.
- Partial group settlement allocations and remittance effect selection.
- Multi-customer settlement represented by a single accounting entry plus per-partner payment records.

