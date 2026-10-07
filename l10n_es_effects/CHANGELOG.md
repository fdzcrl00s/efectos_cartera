## v3.2.0 — 2026-10-07

### Correcciones funcionales
- Corregido el error de Odoo al abrir **Saldar** provocado por buscar `company_id` directamente en `account.account`; en Odoo 18 se utiliza la relación de compañías del plan contable.
- Corregidas las llamadas a los métodos de recálculo de agrupaciones y remesas.

### Creación unificada
- Eliminada la pantalla intermedia que obligaba a elegir primero entre **Efecto / Agrupación / Remesa**.
- **Crear** abre ahora un único formulario donde se selecciona el tipo y los campos cambian según la selección.
- Para agrupaciones y remesas, el **Nº Cartera** se genera automáticamente al confirmar la creación.
- La selección de **Cliente / Proveedor** determina automáticamente **Recibir dinero / Enviar dinero**.
- Los efectos se crean siempre con su **Nº Efecto** como nombre principal, independientemente de la Circular / Concepto introducida.

### Efectos asociados a facturas
- La pestaña de efectos relacionados deja de mostrar todos los efectos de la empresa.
- Si el efecto está asociado a una factura, solo muestra los efectos de esa misma factura.
- Si el efecto es manual y no tiene factura, la relación de efectos queda vacía.
- La Circular / Concepto queda como referencia independiente del Nº Efecto.

### Agrupaciones y remesas
- La creación de agrupaciones y remesas ya no exige introducir manualmente datos que son automáticos antes de poder añadir efectos.
- Una vez creado el documento, se pueden añadir efectos desde **Añadir efectos**.
- Se mantiene la validación de compañía y moneda al añadir efectos.
- Se hace visible el **Nº Cartera** en las fichas de agrupación y remesa.

# Historial de cambios — l10n_es_effects

## v3.1.0 — 2026-10-07

### Formulario de Saldar
- Añadidos los campos de gestión de gastos y comisiones al formulario de pago desde cartera:
  - **Total efecto**
  - **Cuadre del efecto**
  - **Gastos**
  - **Cuenta de gastos**
  - **Comisiones**
  - **Cuenta de comisiones**
  - **Agrupar apuntes en banco**
- Las cuentas de gastos y comisiones se establecen por defecto en la **626**.
- Al activar **Cuadre del efecto**, la cuenta de gastos pasa automáticamente a la **769**.
- La opción **Agrupar apuntes en banco** genera un único asiento contable de ajuste para los gastos/comisiones del efecto, con su contrapartida en banco.
- Los gastos y comisiones se contabilizan después de crear el pago nativo de Odoo y no modifican la conciliación normal del pago.
- Se guarda en el efecto el asiento de gastos/comisiones generado para poder consultarlo posteriormente.

### Creación de efectos
- El botón **Crear** del listado de efectos queda visible de forma permanente.
- El asistente de creación permite elegir entre:
  - **Efecto**
  - **Agrupación**
  - **Remesa**
- Los registros de agrupación y remesa se gestionan mediante sus propios modelos; el modelo de efecto mantiene el tipo real **Efecto**.

### Numeración
- **Nº Efecto** identifica cada efecto individual.
- **Nº Cartera** se utiliza para agrupaciones y remesas.
- Se mantienen los números sin prefijos artificiales.

### Agrupaciones y remesas
- Se mantiene la posibilidad de añadir efectos pendientes a agrupaciones y remesas mediante asistente.
- Se controla la compañía y moneda al añadir efectos.
- Se actualiza el estado de los efectos al agrupar/remesar.
- La desagrupación devuelve los efectos a estado pendiente y elimina su número de cartera.

### Saldado
- Se mantiene la acción **Saldar** como acción de pago del efecto.
- Se mantiene **Saldado parcial** para seleccionar individualmente los efectos de una remesa.
- La contabilización principal del pago continúa utilizando el mecanismo nativo de Odoo.

### Compatibilidad Odoo 18
- Revisado el XML y Python del módulo para Odoo 18 Community.
- Verificados sintaxis Python, XML, referencias de métodos de botones, IDs XML, manifiesto y ausencia de `__pycache__`/`.pyc`.
- La compatibilidad estática no sustituye la prueba funcional en una base de datos real.

### Observaciones de la revisión
- La cuenta bancaria del asiento de ajuste depende de la configuración de la cuenta por defecto del diario o de las cuentas de pagos pendientes de Odoo.
- La lógica de ajuste depende del sentido del pago (**cliente/proveedor**), por lo que debe probarse con ambos casos.
- Los efectos en moneda distinta a la de la compañía deben probarse antes de utilizarlos en producción.

---

## v3.0.0 — 2026-10-06

- Consolidación de la gestión de efectos, agrupaciones y remesas.
- Creación automática de efectos desde las facturas contabilizadas a partir de las líneas de vencimiento.
- Separación de los registros de efecto, agrupación y remesa.
- Gestión de estados de cartera y trazabilidad mediante historial.
- Incorporación de acciones de agrupación, remesa, desagrupación y saldado.
- Menú principal **Cartera** bajo Facturación.
- Submenús **Efectos de clientes** y **Efectos de proveedores**.
- Diferenciación entre **Nº Efecto** y **Nº Cartera**.

## Criterios contables de la versión

- La contabilización de la factura permanece en el circuito estándar de Odoo.
- El pago del efecto utiliza el registro de pagos nativo de Odoo y mantiene la conciliación con la factura.
- Los gastos y comisiones de cartera se registran mediante asientos de ajuste independientes.
