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
