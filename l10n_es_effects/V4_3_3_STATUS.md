# V4.3.3 — Cartera de Efectos Odoo 18

## Incluido en esta entrega

- Los diarios bancarios elegidos en la ficha de la agrupación/remesa se guardan en el modelo principal y vuelven a mostrarse al reabrir la ficha.
- Una remesa creada desde una selección o desde una agrupación genera automáticamente el asiento de reclasificación inicial.
- Si se modifica una remesa todavía pendiente, el módulo reconstruye el asiento inicial existente en lugar de acumular asientos duplicados.
- Las cuotas parciales pagadas de una agrupación permanecen activas y visibles cuando se registra el pago final; solo se archiva el efecto auxiliar pendiente.
- Las cuotas pagadas muestran acciones de anulación y devolución, también en agrupaciones de varios clientes.
- La anulación desde una cuota está limitada al último pago de la agrupación/remesa.
- El modelo `account.payment` incorpora `cartera_settled`, usado para que los pagos contabilizados por el módulo muestren estado Pagado.
- El registro de pagos propone el diario de la cartera/efecto o el primer diario de liquidez disponible.
- Las referencias de pago conservan el número de agrupación/remesa y la interfaz vuelve a la ficha actual tras liquidar.
- Los efectos manuales y residuales mantienen la lógica previa de circular y pagos parciales.
- El memo de un pago individual identifica el efecto por su número; los pagos de agrupación/remesa conservan el tipo y número del contenedor.
- La creación de remesas desde agrupaciones respeta el diario bancario predeterminado cuando no hay uno seleccionado expresamente.
- La creación de contenedores desde el menú no envía un valor bancario vacío que anule el valor predeterminado del modelo.
- El asiento inicial de una remesa pendiente se reconstruye sobre el mismo registro al añadir o quitar efectos; si queda vacía, el asiento inicial sin pagos se cancela y queda disponible para reutilizarlo.
- Se elimina el botón manual de confirmación de agrupación; el asiento inicial se genera mediante el guardado y la incorporación de efectos.

## Validaciones realizadas

- Compilación de los archivos Python.
- Análisis XML de los archivos de vistas/datos.
- Comprobación de referencias de archivos del manifiesto.
- Comprobación del CSV de permisos.

## Pendiente de validar en el servidor del usuario

No se dispone aquí de una instancia Odoo 18 ni de una base de datos de prueba. Debe validarse la actualización del módulo y la ejecución real de los asientos/conciliaciones en una copia de la base de datos.

### Última ronda recomendada

1. Abrir un efecto, agrupación y remesa pendientes; editar sus datos sin acciones especiales, guardar y comprobar que banco, circular y vencimiento permanecen.
2. Crear una remesa desde una agrupación y otra desde el menú; antes de pagar, añadir y quitar efectos. Comprobar que el asiento inicial se crea automáticamente, se actualiza sin duplicarse y se cancela si la remesa queda vacía.
3. Hacer dos pagos parciales de una agrupación: deben quedar dos cuotas pagadas visibles y un único efecto auxiliar pendiente por el saldo restante.
4. Anular el último pago: debe revertirse el asiento, archivarse la cuota anulada y actualizarse el efecto auxiliar pendiente.
5. Abrir una cuota pagada y probar devolución sin anular los pagos de otros clientes.
6. Saldar un efecto individual y comprobar que el pago nativo aparece como Pagado.
7. Confirmar que el memo contiene “Efecto nº …”, “Agrupación nº …” o “Remesa nº …” y que la pantalla actual se recarga sin saltar al asiento/pago.
