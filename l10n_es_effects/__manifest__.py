{
    'name': 'Cartera de Efectos - España',
    'version': '18.0.1.0.0',
    'category': 'Accounting/Accounting',
    'summary': 'Cartera de efectos para facturas de clientes y proveedores',
    'description': '''
Cartera de efectos española para Odoo 18 Community.

V1:
- Creación automática de efectos al contabilizar facturas y facturas de proveedor.
- Un efecto por cada vencimiento contable de la factura.
- Efectos de clientes y proveedores.
- Agrupación de efectos.
- Remesas.
- Liquidación mediante el asistente de pagos nativo de Odoo.
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
