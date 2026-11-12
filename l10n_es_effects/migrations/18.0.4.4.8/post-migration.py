def migrate(cr, version):
    # Link existing invoice-origin effects to their source invoice so the invoice
    # payment state and the effects smart button can account for all legacy records.
    cr.execute("""
        UPDATE account_effect AS effect
           SET origin_invoice_id = move.id
          FROM account_move AS move
         WHERE effect.move_id = move.id
           AND effect.origin_invoice_id IS NULL
           AND move.move_type IN ('out_invoice', 'in_invoice', 'out_refund', 'in_refund', 'out_receipt', 'in_receipt')
    """)
