{
    'name': 'Cartera de Efectos - España',
    'version': '18.0.3.0.0',
    'category': 'Accounting/Accounting',
    'summary': 'Cartera de efectos para clientes y proveedores',
    'description': '''
Cartera de efectos para Odoo 18 Community.

CAMBIOS
=======
20261007 - 02:00h\nCorrecciones de compatibilidad Odoo 18 y lógica de agrupación/remesa.\n\n20261007 - 01:00h
Añadidas configuraciones de agrupaciones y remesas.
Separada la numeración entre Nº Efecto y Nº Cartera.
Añadida ficha ampliada de efectos.
Añadidos históricos de pagos y situaciones.
Añadidos saldado entero y saldado parcial de remesas.
Añadidas líneas de efectos de la misma cartera y acciones de actualización.

HISTÓRICO DE VERSIONES
======================
V3.0.0 - 20261007
- Nº Efecto individual para cada registro.
- Nº Cartera exclusivo de agrupaciones y remesas.
- Ficha ampliada de Efecto, Agrupación y Remesa.
- Gestión de efectos agrupados y remesados.
- Saldado individual y saldado parcial/entero.
''',
    'author': 'Custom',
    'license': 'LGPL-3',
    'depends': ['account', 'l10n_es'],
    'data': [
        'security/ir.model.access.csv',
        'data/sequence.xml',
        'views/effect_views.xml',
        'views/payment_register_views.xml',
        'views/effect_create_wizard_views.xml',
        'views/effect_add_lines_wizard_views.xml',
        'views/effect_history_views.xml',
        'views/group_views.xml',
        'views/remittance_views.xml',
        'views/remittance_partial_wizard_views.xml',
        'views/account_move_views.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'application': True,
}