def migrate(cr, version):
    # Block 2 introduces no additional database columns; this migration
    # marker allows a clean upgrade from the 4.4.0 intermediate package.
    pass
