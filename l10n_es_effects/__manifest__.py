{
    'name': 'Cartera de Efectos - España',
    'version': '18.0.4.3.3',
    'category': 'Accounting/Accounting',
    'summary': 'Cartera de efectos para clientes y proveedores',
    'description': '''
Cartera de efectos para Odoo 18 Community.

CAMBIOS
=======
20261105 - V4.3.3
- Draft grouping/remittance container projections now synchronize selected bank and beneficiary bank values back to the business records.
- Remittances created from selected effects or from a grouping generate their opening transfer entry immediately; draft edits rebuild the same move rather than creating duplicates.
- Partial grouping settlement keeps each paid tranche active and actionable, while only the pending continuation helper is resized or archived.
- Paid tranches expose their own annulment and return actions from the portfolio tab, including multi-customer groupings without a single partner payment link.
- Added the explicit `cartera_settled` state flag on native payments so posted cartera payments display as Paid rather than In Process when the journal uses a transit account.
- The standard payment register preselects the effect/group/remittance bank journal or an available company liquidity journal.
- Payment memo/reference identifies the effect, grouping or remittance by its corresponding number; post-settlement actions reload the current cartera record.
- Draft remittance opening entries rebuild on the same move when effects are added/removed; an empty unpaid remittance cancels that opening move for reuse.
- Preserve the default bank journal when creating group/remittance containers without an explicit journal.
- Remove the manual grouping-confirmation button; initial grouping entries are created through the save/add-effects flow.
- Static validation only; not executed against a live Odoo 18 database.

20261105 - V4.3.2
- Partial continuation effects copy the circular/concept reference from the source effect or grouping.
- Fixed invalid `fields.Date.min/max` references by using Python date boundaries in ordering operations.
- Remittance payment reversals now reconcile aggregated counterpart buckets by account, partner and currency, rather than requiring a one-to-one line match.
- Remittance return wizard now preselects a valid liquidity journal and allows an explicit bank/cash journal selection.
- Added direct settlement for manually-created effects without an invoice, using a native account.payment and receivable/payable counterpart; partial manual settlements create an actionable residual effect.
- Cancelling a partial individual payment restores the original amount and deactivates its continuation, while preventing reversal ahead of later payments in the chain.
- Grouping settlement action is labelled simply “Saldar”.
- Static validation only; not executed against a live Odoo 18 database.

20261105 - V4.3.1 candidate
- Grouping creation opens the single portfolio projection and creates its initial move automatically when the journal can be inferred; added explicit confirm/generate fallback actions when a journal must be selected.
- Grouping reference changes are propagated to the initial entry; accounting-entry smart button remains available on container records.
- Remittance partial-selection lines no longer allow blank records; hidden effect references are force-saved and selection uses direct toggles. The grouping-seat generator also runs when a group is marked as remitted during remittance creation.
- Remittance returns are available from recorded paid allocations, including grouped effects whose individual invoice state remains open until the full group settles; returned amounts are tracked to prevent duplicate returns.
- Remittance return/reversal controls now follow actual posted payment histories.
- Group/remittance entry flows consistently open the portfolio projection to avoid duplicate form routes.
- Shared payments remain represented in the native customer/vendor payments list through per-partner account.payment records linked to one consolidated entry.
- Static validation only; not executed against an Odoo 18 database.

20261104 - V4.3.0 candidate
- Added the initial receivable/payable reclassification entry when effects are grouped, retaining original invoices as open until the whole group is paid.
- Added single-entry group/remittance settlements with one bank line and counterpart distribution by partner/account.
- Added successive partial group settlement allocations and residual portfolio tracking.
- Added whole-effect selection for partial remittance settlement; selected effects cannot be manually underpaid.
- Added full reversal safeguards and complete grouping/remittance payment history visibility.
- Static validation only; this candidate has not been executed against an Odoo 18 database.

20261104 - V4.2.1 candidate
- Corrected expense/commission adjustment move generation for both grouped and separate bank lines.
- Group/remittance annulment targets only the latest settlement installment.
- Cancelled payments are retained as audit records; posted adjustment moves are reversed rather than deleted.
- This candidate does not implement or certify the full V4.2 functional specification; see V42_1_STATUS.md.

20261027 - V4.1.0
- Se mantiene la estructura de menús con clientes, proveedores y nuevo apartado de empleados y tributos.
- Se añade clasificación y campos de cuenta/beneficiario para efectos manuales.
- Se añade acceso a anulación de saldado desde la línea de efecto pagado en la cartera.

20261012 - V3.10.13
- The standalone effect shows itself in the 'Efectos de la misma cartera' traceability tab.
- Individual continuation effects without their own move line retain the Saldar action and resolve their root accounting line.
- Group/remittance settlement resolves accounting lines through continuation-effect roots and removes duplicate line IDs.
- Payment history records are created against each actual reconciled payment when Odoo creates more than one.

20261008 - V3.10.12
- Corrected grouping/remittance selection for different customers/providers of the same type.
- Grouped cartera settlements force one native Odoo payment for the logical total.
- Individual payment history is now created after every cartera settlement.
- Partial settlements reduce the settled effect total and create a visible, actionable continuation effect.
- Returned effects release the accounting due line back to a new pending effect and reverse the payment reconciliation.
- Group/remittance annulment keeps payment history as an audit trail and marks it cancelled instead of deleting it.
- Effect names use the invoice reference when available.
- Totals show the configured currency formatting in forms and lists.

20261008 - V3.10.11
- Fixed payment wizard runtime NameError by resolving portfolio child/root in action_create_payments before reuse.
- Kept normal, grouped, remittance and portfolio-child payment flows compatible with Odoo 18 payment registration.

20261008 - V3.10.10
- Unified pending balance mathematics with currency rounding tolerance.
- Fixed partial settlement continuation effects for individual effects.
- Remittance partial selection no longer depends on effect-level residual being non-zero.
- Removed stale/draft native payments when repeating cartera settlement operations.
- Anulaciones remove the native payment and its related accounting/history records instead of leaving drafts/cancelled payments.
- Grouping accepts different customers/providers of the same customer/supplier type.
- Pending containers can edit date, partner and circular/concept from the portfolio effect.
- Legacy V3 pending balances are recomputed when opening the cartera.
- Situation labels use DD/MM/YYYY.

20261007 - V3.10.3
- Apertura uniforme de remesas desde el efecto de cartera.
- Efectos asociados de la remesa muestran siempre sus efectos reales.
- Saldado entero usa el total de todos los efectos pendientes de la remesa.
- Saldado parcial con selección explícita mediante casillas y sumatorio.
- Devolución selectiva de efectos con el mismo patrón de selección.
- Las remesas nunca crean efectos auxiliares por saldados parciales.
- Situación visible del efecto limitada a Pendiente, Saldado y Devuelto.

20261007 - V3.10.2
- Remesas con un único efecto de cartera; los saldados parciales no crean nuevos efectos.
- Selección completa de efectos en saldado entero y parcial.
- Anular saldado desde la remesa y devolución selectiva de efectos.
- Acceso a asientos contables desde efectos y remesas.
- Selector de remesa: solo pendientes individuales y efectos de agrupación, nunca los efectos internos agrupados.
- Situación visible de los efectos reducida a Pendiente, Saldado y Devuelto.

20261007 - V3.10
- Pago Odoo enlazado desde el efecto.
- Anular saldado y devolución con nuevo efecto pendiente.
- Popup directo para añadir efectos y agrupaciones a remesas, excluyendo efectos ya remesados.
- Cuatro pestañas en agrupaciones y remesas.
- Histórico de pagos de contenedores con referencia, asiento, fecha, efectos, total y tipo.
- Efectos de cartera derivados de saldados parciales.

20261007 - V3.8
- Saldado unificado para efectos, agrupaciones y remesas.
- Estados y situaciones con fecha de saldado.
- Remesas con estados Pendiente, Saldada parcialmente y Saldada; eliminado Marcar enviada.
- Agrupaciones saldables directamente.
- Remesas muestran la compañía como cliente en el listado.
- Títulos con tipo + número.
- Totales de Total y Total pendiente en el listado, incluyendo selección.
- Corregidos permisos del asistente Añadir efectos.
- Formulario de Saldar reducido a Datos de pago y Liquidación del efecto, ocultando campos nativos redundantes.

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