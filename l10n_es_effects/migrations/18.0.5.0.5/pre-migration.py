"""Ensure columns introduced in 18.0.5.0.4 exist before ORM initialization.

This migration is intentionally idempotent. It only creates missing columns and
does not modify accounting entries or effect records.
"""


def _table_exists(cr, table):
    cr.execute("SELECT to_regclass(%s)", (table,))
    return bool(cr.fetchone()[0])


def _add_column(cr, table, column, sql_type):
    if _table_exists(cr, table):
        cr.execute(
            'ALTER TABLE "{}" ADD COLUMN IF NOT EXISTS "{}" {}'.format(
                table, column, sql_type
            )
        )


def migrate(cr, version):
    # Boolean audit marker used by archived replacement effects.
    _add_column(cr, 'account_effect', 'return_cancelled', 'BOOLEAN')
    if _table_exists(cr, 'account_effect'):
        cr.execute(
            'UPDATE account_effect SET return_cancelled = FALSE '
            'WHERE return_cancelled IS NULL'
        )
        cr.execute(
            'ALTER TABLE account_effect ALTER COLUMN return_cancelled SET DEFAULT FALSE'
        )
        cr.execute(
            'ALTER TABLE account_effect ALTER COLUMN return_cancelled SET NOT NULL'
        )

    # Link from the return journal item to the replacement effect.
    _add_column(cr, 'account_move_line', 'effect_returned_effect_id', 'INTEGER')

    # Keep the reversing journal entry linked to a cancelled container history row.
    _add_column(
        cr, 'account_effect_container_payment_history', 'reversal_move_id', 'INTEGER'
    )
