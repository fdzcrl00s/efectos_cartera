def migrate(cr, version):
    """Restore the accounting sign on untouched invoice-linked cartera effects.

    Earlier builds stored ABS(payment-term residual) as the effect amount. That
    erased the negative sign of customer credit notes (and the corresponding
    sign on supplier/customer maturity lines). Correct only effects that are
    still pending and have not entered a group, remittance or payment flow.
    Amount magnitude is preserved; only its sign and cash direction are fixed.
    """
    cr.execute("""
        UPDATE account_effect AS effect
           SET amount = CASE
                   WHEN line.balance < 0 THEN -ABS(effect.amount)
                   ELSE ABS(effect.amount)
               END,
               payment_direction = CASE
                   WHEN line.balance > 0 THEN 'receive'
                   ELSE 'send'
               END
          FROM account_move_line AS line
         WHERE effect.move_line_id = line.id
           AND effect.move_id IS NOT NULL
           AND effect.state = 'pending'
           AND COALESCE(effect.is_container, FALSE) = FALSE
           AND COALESCE(effect.is_portfolio_effect, FALSE) = FALSE
           AND effect.group_id IS NULL
           AND effect.remittance_id IS NULL
           AND effect.payment_id IS NULL
           AND line.balance <> 0
           AND effect.amount <> 0
           AND (
               (line.balance < 0 AND effect.amount > 0)
               OR (line.balance > 0 AND effect.amount < 0)
           )
           AND NOT EXISTS (
               SELECT 1
                 FROM account_effect_payment_history AS history
                WHERE history.effect_id = effect.id
           )
    """)
