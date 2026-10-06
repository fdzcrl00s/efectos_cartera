{
    'name': 'Cartera de Efectos - España',
    'version': '18.0.1.2.1',
    'category': 'Accounting/Accounting',
    'summary': 'Cartera de efectos para clientes y proveedores',
    'description': '''
Cartera de efectos para Odoo 18 Community.

V1.2:
- Menú principal "Cartera".
- Separación entre efectos de clientes y proveedores.
- Alta manual de efectos sin factura.
- Agrupación y remesa desde las listas de efectos.
- Orden por vencimiento más reciente primero.
- Estado de pago y situación separados.
- Totales y pendientes visibles en la lista.
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
        'views/remittance_partial_wizard_views.xml',
        'views/account_move_views.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'application': True,
}
