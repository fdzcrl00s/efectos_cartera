{
    'name': 'Cartera de Efectos - España',
    'version': '18.0.3.7.0',
    'category': 'Accounting/Accounting',
    'summary': 'Cartera de efectos para clientes y proveedores',
    'description': '''
Cartera de efectos para Odoo 18 Community.

CAMBIOS
=======
20261007 - V3.7
- Corrección de apertura del listado de efectos en Odoo 18: acción dinámica con vistas list/form compatibles.

20261007 - V3.6
- Agrupaciones y remesas pendientes visibles en el listado general de efectos.
- Sincronización de registros de cartera para contenedores.
- Situación enlazable y trazabilidad explícita del efecto.
- Corrección del campo situación que provocaba UndefinedColumn.
- Remesa sin cliente/proveedor obligatorio.
- Formulario de Saldar reorganizado en Datos de pago y Liquidación del efecto a ancho completo.
- Changelog visible en la descripción del módulo.
20261007 - V3.5
- Remesa creada con compañía, sin cliente/proveedor obligatorio.
- Corregido el error de partner_id al crear remesas.
- Situación del efecto enlazable a la agrupación o remesa desde el listado.
- Cabeceras de agrupación/remesa con su Nº Cartera visible.
- Formulario de Saldar reorganizado en Datos de pago y Liquidación del efecto a ancho completo.

20261007 - V3.4
Efectos agrupados/remesados como líneas azules, remesas unificadas por efectos y sin pestaña separada de agrupaciones.

20261007 - V3.3
Contenedores independientes, referencia estable del efecto, situación con agrupación/remesa, saldado directo de agrupaciones, remesas con efectos y agrupaciones, retirada individual de efectos y mejoras de liquidación.

20261007 - V3.2
Correcciones funcionales de saldado y creación unificada de efectos, agrupaciones y remesas.

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