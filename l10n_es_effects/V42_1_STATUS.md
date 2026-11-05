# Cartera de Efectos 18.0.4.2.1 — estado de la entrega

## Alcance real de esta entrega

Este ZIP parte del código V4.1.0 facilitado por el usuario. Incluye correcciones acotadas de generación de asientos de gastos/comisiones y de la acción de anulación. **No equivale a la implementación completa de la especificación funcional V4.2/V4.2.1 acordada.**

## Cambios de código incluidos

- La creación del asiento de ajuste contempla todas las líneas de gastos y comisiones. Si «Agrupar apuntes en banco» está desmarcado, cada ajuste lleva su propia contrapartida bancaria; si está marcado, se genera una única contrapartida bancaria por el total.
- La acción de anulación de agrupaciones y remesas selecciona el último pago registrado.
- Se evita eliminar el registro de pago nativo al anular desde la agrupación/remesa.
- Los asientos de ajuste publicados se revierten en vez de ponerse en borrador y eliminarse.

## Funciones que siguen pendientes de implementación o validación en Odoo 18

- Asiento contable de creación de agrupación con la estructura exacta de las capturas y conciliación de cada efecto original.
- Modelo de operación de saldado conjunto con múltiples asientos sucesivos (uno por cada pago parcial) y una única línea bancaria por operación cuando corresponda.
- Tratamiento completo de pagos agrupados con distintos partners/pagador común y conciliación correcta de cada factura.
- Pago parcial de remesa por selección de efectos sin alterar los importes al marcar casillas.
- Efectos derivados dentro de la misma agrupación, relación circular e importes residuales.
- Añadir efectos en el formulario inicial de agrupaciones y remesas.
- Devoluciones y anulación de devoluciones según el flujo acordado.
- Históricos completos, estados y navegación tras las operaciones.
- Migración y actualización probada desde una base V4.1 con asientos existentes.

## Validaciones estáticas

Se compilan los archivos Python y se analizan los XML por sintaxis. Estas comprobaciones no verifican los modelos contra una instancia real de Odoo, la ejecución de los métodos contables ni la conciliación resultante.

## Uso

No instalar en producción. Si se decide probar este paquete, hacerlo únicamente en una base desechable con copia completa de base de datos y filestore. Revisar cada asiento y conciliación en Odoo 18.
