# 5.0.5

- Añadida una acción contextual de lista «Reasociar a facturas» en el menú Acción,
  aplicable a los efectos seleccionados.
- La reparación informa también de los registros seleccionados que no son efectos
  individuales reparables.
- Añadida una migración previa idempotente para garantizar la existencia de las
  columnas introducidas en 5.0.4: `account_effect.return_cancelled`,
  `account_move_line.effect_returned_effect_id` y
  `account_effect_container_payment_history.reversal_move_id`.
- No se eliminan ni se modifican asientos históricos mediante esta migración.
