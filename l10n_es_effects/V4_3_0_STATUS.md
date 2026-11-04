# Cartera de Efectos – V4.3.0 candidate (Odoo 18)

## Functional work included

### Grouping and first accounting entry
- Creating a grouping can generate an initial journal entry in the selected bank/cash journal.
- The entry reclassifies each original receivable/payable due line and creates a grouped open balance, bucketed by account, partner and currency.
- Original invoices remain open. They are reconciled and marked paid together only after the full grouping balance reaches zero.
- The grouping entry is linked to the grouping and exposed through the accounting entries action.

### Full and successive partial settlement
- A grouping can be settled in full or for a smaller total amount.
- A partial payment is allocated automatically by oldest due date, then effect ID.
- Each settlement creates one journal entry with a single liquidity/bank line and counterpart lines split by partner/account/group as required.
- Per-effect allocations are stored in a separate history model. Remaining balances are represented by the grouping's pending balance and a synthetic residual portfolio record; the synthetic record is not counted as an additional source debt.
- Original invoices remain unreconciled until every effect in the grouping has been paid.

### Remittances and mixed customers
- Partial remittance settlement is based on explicit effect selection.
- Every selected effect is settled for its full current pending amount; the wizard does not allow a lower payment total.
- A consolidated remittance settlement creates one journal entry with one bank line and separate counterpart lines by partner/account/group.
- When the remittance contains several groupings, the single payment history record is linked to every affected grouping for traceability and cancellation safeguards.

### Reversals and audit trail
- Annulment reverses the latest consolidated settlement move and retains the original history as cancelled.
- Receivable/payable reconciliations are removed and restored against the reversal entry.
- If the liquidity line has already been reconciled to a bank statement, annulment is blocked until that bank reconciliation is undone.
- A payment move spanning several groupings must be annulled from the remittance to avoid partial reversal of a shared bank operation.
- Individual return of an effect paid inside a consolidated group/remittance payment is blocked with an explanatory message; it must first be handled at the container-operation level.

## Static validation performed

- Python source compilation with `compileall`.
- XML parsing of every module view/data file.
- CSV parsing of access-control declarations.
- ZIP integrity check on the generated package.

## Important runtime validation limitation

This environment does not contain an Odoo 18 server/runtime or a disposable Odoo database. Therefore the candidate has **not** been installed or executed here. It must first be installed on a copy/staging database and tested with actual company charts of accounts, journals, receivable/payable accounts, currencies, and bank-statement reconciliation before production use.

Recommended minimum acceptance scenarios:
1. Group two or more customer effects, verify the initial reclassification entry and that all original invoices remain unpaid.
2. Pay a grouping in full and verify that all original invoices reconcile together.
3. Pay a grouping in several partial installments, including a partial installment that crosses from one effect to the next in FIFO order; verify residuals and history after each installment.
4. Repeat with supplier effects.
5. Build a remittance from standalone effects and groupings belonging to multiple partners; select only some effects and verify one bank line, separate partner counterpart lines, exact full settlement of selected effects, and no change to unselected effects.
6. Annul a full and a partial consolidated payment; verify that payment counterpart lines reopen, original grouping invoices reopen if the group is no longer fully settled, and history remains visible as cancelled.
7. Verify fee/commission cases and foreign-currency entries if those are used in the live company.
8. Verify grouping ungroup/reversal and bank statement reconciliation protections.
