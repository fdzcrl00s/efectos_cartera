# Changelog

## V3.10.11 - 2026-10-08
- Fixed `NameError: portfolio_child is not defined` in `account.payment.register.action_create_payments`.
- Portfolio child/root context is now resolved locally before old-payment cleanup and post-payment processing.
- No functional change to the intended settlement logic.

# Changelog

## 18.0.3.10.10
- Unified pending/partial/paid calculation with currency rounding tolerance
- Fixed partial settlement residual chains for individual effects
- Remittance partial selection no longer requires an effect-level pending amount
- Removed duplicate native draft payments and delete cancelled test payments without trace
- Restored effects correctly after cancelling settlements
- Groupings allow effects from different customers/suppliers of the same type; container partner can represent the resulting pending balance
- Pending container editing supports date, partner and circular/concept
- Improved legacy/test data pending calculations
- Display dates in DD/MM/YYYY for situation labels
## 18.0.3.10.7

- Anulación de remesas y agrupaciones: cancela y pasa a borrador todos los pagos asociados, no solo el último.
- Tras anular todos los pagos, se permite de nuevo la desagrupación masiva; los pagos en borrador/cancelados no bloquean la edición.
- Agrupaciones: el saldado entero permite introducir un importe inferior al pendiente y crea un único nuevo efecto de cartera por el pendiente restante.
- Remesas: el saldado parcial y las devoluciones usan selección persistente de efectos con casillas y sumatorio.
- Se refuerza la persistencia de las selecciones de los asistentes de saldado/devolución.
- Los efectos agrupados/remesados mantienen las tres situaciones Pendiente/Saldado/Devuelto y muestran su estado de cartera como Agrupado/Remesado - Pendiente.
- Numeración de cartera compartida entre agrupaciones y remesas.
- Crear desde el listado abre directamente el formulario de efecto; el tipo Efecto/Agrupación/Remesa se elige en la propia ficha antes de guardar.
- Eliminado el botón de saldado parcial específico de las agrupaciones.

## 18.0.3.10.6

- Remesas y agrupaciones: saldado completo calcula directamente el total pendiente del contenedor, sin mostrar una lista previa de efectos en el formulario de pago
- Saldado parcial con selector de efectos y sumatorio del pendiente seleccionado
- Agrupaciones: añadido saldado parcial manteniendo la creación de nuevo efecto por pendiente
- Remesas: nunca se crean nuevos efectos por saldados parciales
- Anulación de saldado: el pago nativo de Odoo se cancela y pasa a borrador, y se recalcula el pendiente
- Estados visuales: pendiente se muestra en rojo; agrupado/remesado en azul
- Referencia de efectos de cartera de agrupaciones/remesas vacía en el listado
- Alta de cartera mediante un único asistente dinámico por tipo de proceso
## 18.0.3.10.5
- No permite quitar efectos de una remesa si existe cualquier pago asociado.
- Oculta Quitar y Desagrupación Masiva en edición de remesas con histórico de pagos.
- La protección también se aplica por servidor al ejecutar la acción.

# Changelog

## 18.0.3.10.4
- Agrupaciones y remesas abiertas desde sus listados muestran directamente su efecto de cartera.
- El formulario del efecto de cartera mantiene cuatro pestañas: efectos agrupados, efectos de la misma cartera, histórico de pagos e histórico de situaciones.
- Las agrupaciones muestran su cadena de efectos de cartera (efecto inicial y efectos pendientes generados por saldados parciales).
- Las remesas muestran un único efecto de cartera en "Efectos de la misma Cartera" y no generan nuevos efectos en saldados parciales.
- Añadido modo de edición para remesas y agrupaciones pendientes, con Añadir efectos, Desagrupación Masiva y Quitar.
- Añadida selección directa de efectos pendientes al editar una agrupación.
- El histórico de pagos de los contenedores se muestra en el efecto de cartera.
- Los asientos contables del contenedor quedan accesibles desde el botón Asientos.

## V3.9 — Correcciones de saldado y listado

- Corregida la detección del pago conciliado usando las relaciones de conciliación de `account.move.line` compatibles con Odoo 18.
- El registro representativo de una agrupación o remesa puede abrir su circuito de saldado directamente.
- Eliminados los botones «Abrir/Ver» del listado general de efectos; las filas abren siempre la ficha del efecto de cartera.
- La trazabilidad de una agrupación/remesa queda en la ficha del efecto individual.
- Ocultadas las etiquetas nativas sobrantes de Importe/Cuenta bancaria destinataria en el formulario de Saldar.
- El formulario de Saldar queda centrado en Datos de pago y Liquidación del efecto.
- Añadida la moneda invisible al listado para que los agregados monetarios de Odoo 18 funcionen correctamente.
- Reforzados los permisos de los asistentes de añadir efectos y saldado parcial.

# CHANGELOG

## V3.8 - 2026-10-07
- Saldado unificado para efectos, agrupaciones y remesas.
- Estados y situaciones con fecha de saldado.
- Remesas: Pendiente / Saldada parcialmente / Saldada; eliminado Marcar enviada.
- Agrupaciones saldables directamente.
- Remesas muestran la compañía como cliente en el listado.
- Títulos con tipo + número.
- Totales y total pendiente en el listado con agregación de la selección.
- Corregidos permisos del asistente Añadir efectos.
- Formulario de Saldar simplificado.

# Changelog — Cartera de Efectos

## V3.6 — 07/10/2026
- Agrupaciones y remesas pendientes visibles en el listado general de efectos.
- Se crean/sincronizan registros de cartera para representar agrupaciones y remesas dentro del listado único de efectos.
- La situación de un efecto agrupado/remesado es enlazable directamente.
- Añadida trazabilidad «Pertenece a» en la ficha del efecto.
- `situation_ref` pasa a ser calculado no almacenado para evitar errores de columna inexistente durante actualizaciones.
- Remesas sin cliente/proveedor obligatorio; la compañía sigue siendo el dato base.
- Formulario de Saldar reorganizado: Datos de pago arriba y Liquidación del efecto debajo, en una sola columna.
- Añadida descripción HTML del módulo para mostrar el historial de cambios en la ficha de Aplicaciones.

# CHANGELOG

## V3.5 - 2026-10-07
- La remesa se crea con la compañía actual y no requiere cliente/proveedor.
- Corregido `partner_id` inválido al crear `account.effect.remittance`.
- La situación de un efecto agrupado/remesado se muestra como referencia enlazable a su agrupación o remesa.
- Cabecera visible `Agrupación nº` / `Remesa nº` con Nº Cartera.
- Formulario de Saldar reorganizado: Datos de pago (Diario, Método, Importe, Fecha de pago y Circular) y, debajo, Liquidación del efecto en una sola columna.

## V3.4 - 2026-10-07
- Efectos agrupados/remesados como líneas azules.
- Remesas unificadas por efectos, sin pestaña separada de agrupaciones.

## V3.3 - 2026-10-07
- Contenedores independientes, referencia estable del efecto, situación con agrupación/remesa, saldado directo de agrupaciones, remesas con efectos y agrupaciones, retirada individual de efectos y mejoras de liquidación.

## 18.0.3.10.9
- Corrige el saldado parcial de remesas para trabajar con efectos remesados aunque `amount_pending` del efecto individual sea 0.
- El importe editable del asistente de cartera se concentra en `Total efecto`; el importe nativo queda oculto y se sincroniza antes de crear el pago.
- Evita dejar pagos nativos en borrador al anular saldados: se cancelan y se limpian las referencias del efecto.
- Refuerza la creación de efectos pendientes derivados tras un saldado parcial de efectos individuales.
- Recalcula el pendiente de efectos agrupados/remesados como 0 y deja el pendiente económico en la cartera contenedora.
