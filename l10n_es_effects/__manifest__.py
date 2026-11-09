{
    'name': 'Cartera de Efectos - España',
    'version': '18.0.4.4.8',
    'category': 'Accounting/Accounting',
    'summary': 'Gestión de efectos, agrupaciones, remesas y liquidaciones parciales',
    'description': '''
Gestión integral de la cartera de efectos comerciales para clientes y proveedores en Odoo 18.

Permite administrar efectos individuales, agrupaciones y remesas; vincular efectos manuales a apuntes contables
existentes sin generar asientos de origen adicionales; registrar cobros y pagos completos o parciales;
conciliar operaciones de uno o varios clientes; gestionar devoluciones y anulaciones; y
consultar el histórico de pagos y situaciones de cada efecto.

El módulo centraliza el seguimiento de vencimientos, importes cobrados y saldos pendientes,
manteniendo la trazabilidad entre los efectos y sus movimientos contables.
''',
    'author': 'Custom',
    'license': 'LGPL-3',
    'depends': ['account', 'l10n_es'],
    'assets': {
        'web.assets_backend': [
            'l10n_es_effects/static/src/js/rpc_error_clipboard.js',
        ],
    },
    'data': [
        'security/ir.model.access.csv',
        'data/sequence.xml',
        'data/payment_document_data.xml',
        'views/effect_views.xml',
        'views/payment_register_views.xml',
        'views/payment_document_views.xml',
        'views/effect_create_wizard_views.xml',
        'views/manual_effect_payment_wizard_views.xml',
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