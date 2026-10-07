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
