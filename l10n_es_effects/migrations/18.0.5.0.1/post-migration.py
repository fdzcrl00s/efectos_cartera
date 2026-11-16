def migrate(cr, version):
    """Align Nº Efecto sequence with the highest number already issued."""
    cr.execute("""
        SELECT id, number_next
          FROM ir_sequence
         WHERE code = 'account.effect'
           AND company_id IS NULL
         ORDER BY id
         LIMIT 1
    """)
    sequence = cr.fetchone()
    if not sequence:
        return

    cr.execute("""
        SELECT MAX(name::bigint)
          FROM account_effect
         WHERE name ~ '^[0-9]+$'
    """)
    max_existing = cr.fetchone()[0] or 0
    current_next = sequence[1] or 1
    minimum_next = int(max_existing) + 1
    if current_next < minimum_next:
        cr.execute(
            "UPDATE ir_sequence SET number_next = %s WHERE id = %s",
            (minimum_next, sequence[0]),
        )
