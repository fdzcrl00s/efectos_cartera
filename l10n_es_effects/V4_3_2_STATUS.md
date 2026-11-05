# V4.3.2 candidate — Odoo 18

## Corrections based on live user tests

1. **Circular on residual effects**
   - Residual effects from partial payments now inherit the original effect's `reference` (circular/concept).
   - Residual grouping portfolio entries inherit the grouping's `reference`.

2. **Date ordering crash**
   - Replaced unsupported `fields.Date.min` / `fields.Date.max` references with `datetime.date.min` / `datetime.date.max` across effect, grouping, and remittance models and the remittance return wizard.

3. **Remittance reversal with repeated counterpart lines**
   - Reversal matching is now performed by account, partner, and currency buckets.
   - Each bucket is checked for a zero company-currency and transaction-currency balance before reconciliation.
   - No line is reconciled if the complete bucket does not balance.

4. **Remittance returns and bank journal**
   - The return wizard includes an editable bank/cash journal field.
   - It defaults to the remittance journal, otherwise the latest posted payment's journal, otherwise a valid company bank/cash journal.
   - Only journals with a liquidity/default account are selectable.

5. **Manually-created effects without an invoice**
   - The Saldar button is visible for pending effects that have a partner or a configured counterpart account, even when no invoice due line exists.
   - A new wizard creates a native Odoo `account.payment` using the partner receivable/payable account (or the effect's explicit counterpart account).
   - Partial manual payments mark the paid portion as settled and create a pending residual effect preserving the circular, bank, partner, and account details.
   - Cancelling the latest payment in an individual continuation chain restores the settled effect's previous amount and deactivates the residual. Reversing an earlier payment is blocked while a later continuation payment is still active.

6. **Grouping action label**
   - The grouping action is labelled `Saldar`; remittance continues to show `Saldar (entero)`.

## Static validation

- Python syntax compilation: passed (14 Python files).
- XML parsing: passed (12 XML files).
- Manifest file references and access-control CSV: passed (13 manifest data files; 16 access-control entries).
- ZIP integrity: checked after final packaging.

## Not certified

This candidate has not been installed or executed on a real Odoo 18 database in this environment. The accounting workflows—especially native payments without invoice lines, multi-line reversal reconciliation, and return entries—must be tested in a cloned database before production use.
