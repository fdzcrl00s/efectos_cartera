# Cartera de efectos · 18.0.5.0.4

- La devolución enlaza el efecto reabierto con el apunte exacto de cliente/proveedor del asiento de devolución.
- La liquidación de un efecto reabierto prioriza su propio apunte contable, sin volver al apunte del efecto original.
- En remesas, el botón «Editar» abre el histórico en modo de revisión y muestra «Anular» solo en la última operación activa.
- Las operaciones anuladas salen del histórico operativo, pero se conservan en «Histórico de anulaciones» con el asiento original y el asiento de reversión.
- Los efectos reabiertos por una devolución anulada se archivan y conservan su relación histórica, en lugar de borrarse.
- Se añade la acción temporal «Reasociar a facturas» para reparar efectos devueltos antiguos. La acción trabaja sobre los registros seleccionados y omite coincidencias ambiguas.
- El asistente etiqueta el campo como «Fecha de devolución».
