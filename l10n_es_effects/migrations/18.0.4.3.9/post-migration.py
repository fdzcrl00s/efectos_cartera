def migrate(cr, version):
    # Former manual effects stored the chosen P&L contra field, but their real
    # balance/reconciliation account is already present on the linked open item.
    cr.execute("""
        UPDATE account_effect AS effect
           SET manual_account_id = line.account_id
          FROM account_move_line AS line
         WHERE effect.manual_account_id IS NULL
           AND effect.move_id IS NULL
           AND effect.move_line_id = line.id
           AND line.account_id IS NOT NULL
    """)
    cr.execute("""
        UPDATE account_effect
           SET manual_nature = 'ordinary'
         WHERE manual_nature IS NULL
           AND move_id IS NULL
           AND NOT is_container
           AND NOT is_portfolio_effect
    """)

    cr.execute("""
        UPDATE account_effect AS effect
           SET manual_account_id = line.account_id
          FROM account_move_line AS line
         WHERE effect.manual_account_id IS NULL
           AND effect.move_id IS NULL
           AND effect.opening_move_id = line.move_id
           AND line.effect_id = effect.id
           AND line.account_id IS NOT NULL
           AND line.account_id IN (SELECT id FROM account_account WHERE reconcile = TRUE)
    """)
