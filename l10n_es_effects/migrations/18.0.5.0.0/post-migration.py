def migrate(cr, version):
    # Keep cartera payment histories when a legacy remittance is deleted.
    # The journal entries themselves are never deleted by the module; posted
    # entries are retained with a posted reversal, and draft entries are canceled.
    cr.execute("""
        DO $$
        DECLARE fk_name text;
        BEGIN
            IF to_regclass('account_effect_container_payment_history') IS NOT NULL THEN
                FOR fk_name IN
                    SELECT conname
                    FROM pg_constraint
                    WHERE conrelid = 'account_effect_container_payment_history'::regclass
                      AND contype = 'f'
                      AND pg_get_constraintdef(oid) ILIKE '%(remittance_id)%'
                LOOP
                    EXECUTE format(
                        'ALTER TABLE account_effect_container_payment_history DROP CONSTRAINT %I',
                        fk_name
                    );
                END LOOP;
                ALTER TABLE account_effect_container_payment_history
                    ADD CONSTRAINT account_effect_container_payment_history_remittance_id_fkey
                    FOREIGN KEY (remittance_id)
                    REFERENCES account_effect_remittance(id)
                    ON DELETE SET NULL;
            END IF;
        END
        $$;
    """)
