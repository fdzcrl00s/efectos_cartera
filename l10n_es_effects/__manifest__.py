{
    'name': 'Cartera de Efectos - España',
    'version': '18.0.1.1.0',
    'category': 'Accounting/Accounting',
    'summary': 'Cartera de efectos para facturas de clientes y proveedores',
    'description': '''
Cartera de efectos para Odoo 18 Community.

V1.1:
- Creación automática de efectos al contabilizar facturas de clientes y proveedores.
- Un efecto por cada vencimiento contable de la factura.
- Gestión de clientes y proveedores.
- Agrupaciones.
- Remesas.
- Registro del pago mediante el asistente nativo de Odoo.
- Sin modificar el asiento original de la factura.
''',
    'author': 'Custom',
    'license': 'LGPL-3',
    'depends': ['account', 'l10n_es'],
    'data': [
        'security/ir.model.access.csv',
        'data/sequence.xml',
        'views/effect_views.xml',
        'views/group_views.xml',
        'views/remittance_views.xml',
        'views/account_move_views.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'application': True,
}
