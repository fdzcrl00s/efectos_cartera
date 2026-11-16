def migrate(cr, version):
    cr.execute(
        """
        UPDATE account_effect_payment_history
           SET operation_type = 'returned'
         WHERE COALESCE(note, '') ILIKE '%Devolución contabilizada en%'
            OR COALESCE(note, '') ILIKE '%Devolución de efecto%'
        """
    )
