"""Repair the transient settlement wizard schema before ORM initialization.

The universal individual-effect settlement wizard already declares these
Many2one fields. Some databases were running the updated Python code without
having upgraded the module, leaving the transient table behind the model and
causing UndefinedColumn when the wizard was saved.
"""


def migrate(cr, version):
    cr.execute("SELECT to_regclass('account_effect_manual_payment_wizard')")
    if not cr.fetchone()[0]:
        # The ORM will create the table from the current model definition.
        return

    # Add missing columns idempotently. The regular ORM schema update then
    # completes field metadata/index/constraint synchronization during -u.
    cr.execute("""
        ALTER TABLE account_effect_manual_payment_wizard
            ADD COLUMN IF NOT EXISTS expense_account_id INTEGER,
            ADD COLUMN IF NOT EXISTS commission_account_id INTEGER
    """)
