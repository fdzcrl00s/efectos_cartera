{
    'name': 'Cartera de Efectos - España',
    'version': '18.0.1.1.0',
    'category': 'Accounting/Accounting',
    'summary': 'Cartera de efectos de clientes y proveedores para Odoo 18 Community',
    'author': 'Custom',
    'license': 'LGPL-3',
    'depends': ['account', 'l10n_es'],
    'data': [
        'security/ir.model.access.csv',
        'data/sequence.xml',
        'views/effect_views.xml',
        'views/account_move_views.xml',
        'views/remittance_views.xml',
        'views/menu.xml',
    ],
    'installable': True,
    'application': True,
}
