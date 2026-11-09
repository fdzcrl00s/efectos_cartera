def migrate(cr, version):
    # No schema changes are needed for 4.4.1.2. The wizard fields are transient
    # and are created/updated by the module registry during the upgrade.
    return
