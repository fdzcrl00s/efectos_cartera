# V4.3.1 candidate — status and validation

## Objetivo

Correcciones de los bloqueos observados en las primeras pruebas V4.3.0.

## Cambios incluidos

1. **Agrupación y asiento inicial**
   - Se abre siempre la ficha de proyección de cartera desde la acción de agrupar, evitando alternar entre la ficha del modelo de agrupación y la proyección.
   - Al añadir efectos o guardar un cambio en el diario de la agrupación, se intenta crear automáticamente el asiento inicial.
   - Si no se puede inferir un diario único, la ficha conserva la opción para seleccionar el diario y generar/confirmar el asiento.
   - Se incluye acción de confirmación y botón de recuperación en la ficha del modelo de agrupación.
   - La referencia/circular se guarda en la agrupación y se propaga a los asientos iniciales publicados.
   - El acceso a asientos permanece visible en los registros contenedor.

2. **Edición y navegación**
   - Las acciones habituales abren la misma proyección de cartera.
   - No se utilizan botones personalizados de entrar/salir de edición en las vistas activas; los campos de agrupación/remesa en borrador dependen del estado editable del contenedor.
   - El botón Añadir efectos permanece dentro de la pestaña de efectos agrupados.

3. **Pagos Odoo**
   - Se conservan registros de pago nativos por cliente/proveedor, vinculados al mismo asiento conjunto de tesorería, para que las operaciones se encuentren en el menú estándar de Pagos.
   - Los registros de pago compartidos bloquean las acciones individuales que podrían cancelar o alterar el asiento común.

4. **Remesas parciales**
   - Las líneas del asistente no son creables manualmente y el selector no puede generar filas vacías sin efecto.
   - La referencia oculta del efecto se fuerza a guardar.
   - El total se calcula desde el importe pendiente real, considerando las asignaciones de pagos parciales de agrupaciones.
   - La selección liquida el efecto completo seleccionado; no se admite introducir un importe menor por línea.
   - Antes de incluir una agrupación en una remesa se exige que su asiento inicial exista; el generador automático admite también agrupaciones ya marcadas como remesadas durante esa operación.

5. **Devoluciones y anulaciones**
   - La disponibilidad para devolver se calcula con los importes efectivamente cobrados a través de esa remesa menos importes ya devueltos.
   - La devolución crea un asiento conjunto con contrapartidas por efecto y una nueva posición pendiente por el importe devuelto.
   - Si un efecto agrupado mantiene una parte pendiente, se conserva esa parte abierta y no se elimina al devolver solo la porción cobrada.
   - Los botones de anulación/devolución se muestran según los históricos y asignaciones contables existentes.

6. **Contrapartidas por efecto**
   - El asiento de liquidación mantiene líneas separadas por efecto aunque varios efectos correspondan al mismo cliente.

## Validación realizada en este entorno

- `python -m compileall`: correcto.
- Parseo de los 11 XML: correcto.
- Lectura de `security/ir.model.access.csv`: correcto (15 permisos).
- Referencias declaradas en `__manifest__.py`: correctas (12 archivos de datos presentes).
- Comprobación del ZIP: correcta tras empaquetar (integridad verificada).

## Limitación importante

Esta entrega es una candidata corregida. No se ha podido instalar ni ejecutar en una base de datos Odoo 18 en este entorno. Antes de producción hay que actualizar el módulo en una copia de pruebas y repetir T01, T02, T03, T06, T08 y T10. T04, T05, T07 y T09 siguen sin validarse.
