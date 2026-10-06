{
    'name': 'Cartera de Efectos - SEPA',
    'version': '18.0.1.1.0',
    'category': 'Accounting/Accounting',
    'summary': 'Extensión SEPA para remesas de cartera',
    'author': 'Custom',
    'license': 'LGPL-3',
    'depends': ['l10n_es_effects'],
    'data': [
        'security/ir.model.access.csv',
        'views/company_views.xml',
        'views/remittance_sepa_views.xml',
    ],
    'installable': True,
    'application': False,
}
