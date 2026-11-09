# Cartera de Efectos – España

Módulo de gestión de efectos comerciales de clientes y proveedores integrado con la contabilidad de **Odoo 18.0**.

- **Nombre técnico:** `l10n_es_effects`
- **Versión del módulo:** `18.0.4.4.9`
- **Licencia:** LGPL-3
- **Dependencias declaradas:** `account`, `l10n_es`

El módulo centraliza el ciclo de vida de los efectos: creación, agrupación, remesa, saldado total o parcial, devolución, anulación de liquidaciones e histórico contable.

## Contenido

- [Funcionalidades](#funcionalidades)
- [Menús](#menús)
- [Requisitos](#requisitos)
- [Instalación](#instalación)
- [Configuración inicial](#configuración-inicial)
- [Uso](#uso)
- [Facturas y facturas rectificativas](#facturas-y-facturas-rectificativas)
- [Documentos de pago](#documentos-de-pago)
- [Numeración](#numeración)
- [Seguridad y permisos](#seguridad-y-permisos)
- [Actualización](#actualización)
- [Estructura del módulo](#estructura-del-módulo)
- [Alcance](#alcance)

## Funcionalidades

### Efectos de clientes y proveedores

- Registro y consulta de efectos comerciales.
- Seguimiento de vencimiento, importe total, importe pendiente, tercero, empresa y dirección del cobro o pago.
- Vinculación con facturas y apuntes contables de vencimiento.
- Histórico de pagos y de cambios de situación.
- Acceso a la factura, al pago y a los asientos relacionados desde la ficha del efecto.

### Efectos manuales

- Permite crear un efecto sin factura ni apunte contable de origen.
- Requiere tercero, importe, vencimiento y una cuenta contable conciliable de destino.
- La creación del efecto manual no publica un asiento de apertura ni una contrapartida automática.
- Cuando se liquide o agrupe, se utilizan la cuenta y los datos contables configurados para la operación.
- También puede vincularse opcionalmente a un apunte contable existente, siempre que esté publicado, abierto y sea compatible con el efecto.

### Agrupaciones

- Agrupa varios efectos en una única agrupación.
- Admite efectos procedentes de facturas y efectos manuales.
- Permite definir la cuenta de destino de la agrupación.
- Genera el asiento contable de reclasificación y conserva la relación con los efectos originales.
- Admite saldados completos y parciales, con histórico de las distintas operaciones.

### Remesas

- Permite crear remesas e incorporar efectos pendientes.
- Utiliza el diario bancario y la cuenta bancaria de la empresa propia.
- Genera el asiento inicial de la remesa y mantiene la trazabilidad de los apuntes de origen.
- Admite saldados completos y parciales.
- Permite registrar devoluciones, con gastos y comisiones opcionales y la posibilidad de crear un nuevo efecto.
- La empresa que se muestra en la ficha/listado de una remesa corresponde a la empresa propia configurada en Odoo.

### Saldados, pagos parciales y devoluciones

- Registro de liquidaciones completas y parciales.
- Registro de gastos y comisiones asociados a una liquidación, con sus cuentas contables.
- Posibilidad de agrupar los apuntes de banco en la contabilización cuando el asistente lo permite.
- Anulación del último saldado cuando se cumplen las condiciones contables.
- Devoluciones con registro de asiento e histórico de operación.
- Conservación de la trazabilidad de los efectos anteriores y, cuando se solicita, creación de un nuevo efecto pendiente.

### Integración con facturas de Odoo

El módulo crea efectos automáticamente al contabilizar los siguientes tipos de documento:

- Factura de cliente (`out_invoice`).
- Factura rectificativa de cliente (`out_refund`).
- Factura de proveedor (`in_invoice`).
- Factura rectificativa/devolución de proveedor (`in_refund`).

Se crea un efecto por cada vencimiento contable pendiente. El importe conserva el signo del saldo del vencimiento y la dirección del movimiento se determina a partir de ese signo.

Para documentos ya contabilizados, se incluye la acción **Acción → Generar efectos de cartera** en el listado de facturas. La operación valida el lote completo y se ejecuta dentro de la transacción de Odoo: si falla una de las creaciones, la operación completa se revierte. Los vencimientos que ya tienen efecto no se duplican y los documentos sin saldo pendiente no generan efectos nuevos.

En la factura se añade un acceso rápido a los efectos relacionados. El estado de pago de la factura se calcula teniendo en cuenta los efectos de cartera: estar agrupado o remesado no equivale por sí solo a estar pagado; una devolución puede mostrarse como **Devuelto** mientras siga pendiente de sustitución o liquidación.

## Menús

El módulo añade el menú superior **Cartera**, con estas opciones principales:

- **Efectos de clientes**
- **Efectos de proveedores**
- **Efectos de empleados y tributos**

La configuración de documentos de pago está disponible en:

**Contabilidad → Configuración → Administración → Documentos de pago**

El menú Cartera se sitúa junto a los menús de Proveedores y Contabilidad, según la secuencia configurada en el menú de contabilidad.

## Requisitos

- Odoo **18.0**.
- Aplicaciones/módulos estándar `account` y `l10n_es` instalados.
- Un plan contable y diarios configurados para cada empresa que vaya a utilizar la cartera.
- Para contabilizar pagos o devoluciones: un diario bancario o de caja de la empresa, con cuenta de liquidez configurada.
- Para efectos manuales sin apunte de origen: una cuenta contable activa que permita conciliación.

El manifest declara únicamente `account` y `l10n_es` como dependencias obligatorias. La integración con campos de numeración de asiento de otros complementos se detecta de forma condicional cuando esos campos están instalados; no se declara como dependencia obligatoria.

## Instalación

1. Copiar la carpeta `l10n_es_effects` al directorio de addons de Odoo.
2. Comprobar que el directorio de addons está incluido en `addons_path`.
3. Reiniciar el servicio/contenedor de Odoo.
4. Activar el modo desarrollador si es necesario y actualizar la lista de aplicaciones.
5. Buscar **Cartera de Efectos - España** e instalar el módulo.

Ejemplo de actualización desde línea de comandos (adaptar la ruta y el nombre de la base de datos a la instalación):

```bash
./odoo-bin -d NOMBRE_BASE_DATOS -u l10n_es_effects --stop-after-init
```

En despliegues Docker, el comando debe ejecutarse dentro del contenedor que utiliza el mismo código y configuración de addons que el servicio Odoo.

## Configuración inicial

### 1. Diarios

Para cada empresa:

- Configurar al menos un diario bancario o de caja con una cuenta de liquidez.
- Revisar que los diarios y las cuentas pertenezcan a la empresa correspondiente.
- En caso de utilizar un complemento externo de numeración de asientos, verificar que el diario tenga la secuencia que ese complemento requiere.

### 2. Cuentas contables

- Los vencimientos de facturas deben utilizar cuentas de clientes/proveedores que permitan conciliación.
- Los efectos manuales deben tener una cuenta de destino activa y conciliable.
- Las agrupaciones deben utilizar una cuenta de destino válida y conciliable.
- Las cuentas de gastos y comisiones deben pertenecer a la empresa y estar activas.

### 3. Documentos de pago

Acceder a **Contabilidad → Configuración → Administración → Documentos de pago**. El catálogo permite crear y mantener:

| Campo | Descripción |
|---|---|
| Código | Identificador único del documento. |
| Nombre | Nombre visible del documento de pago. |
| Hay que recibirlo/enviarlo | Indicador configurable del documento. |
| Remesable | Determina si el documento puede utilizarse en operaciones de remesa. |
| Activo | Permite archivar un documento sin eliminar su histórico. |

El módulo carga inicialmente el documento **TR – Transferencia bancaria**, marcado como remesable. En los asistentes de cartera, el método técnico de pago de Odoo se mantiene en **Manual** internamente; el usuario selecciona el **Documento de pago** del catálogo.

Los documentos utilizados quedan registrados en los históricos de pagos y devoluciones.

## Uso

### Crear un efecto manual

1. Entrar en **Cartera → Efectos de clientes** o **Cartera → Efectos de proveedores**.
2. Crear un efecto individual.
3. Seleccionar el tercero, cuenta bancaria/diario si corresponde, cuenta contable de destino, importe, moneda y vencimiento.
4. Dejar vacío el apunte contable de origen si se trata de un efecto manual independiente.
5. Guardar.

La creación no genera por sí sola un asiento contable de apertura. Para su posterior liquidación, el efecto debe disponer de una cuenta conciliable válida.

### Agrupar efectos

1. Seleccionar efectos pendientes compatibles (empresa, moneda y tercero/tipo según las validaciones del módulo).
2. Ejecutar **Agrupar**.
3. Revisar el tercero, la cuenta de destino, diario bancario, cuenta bancaria, fecha y concepto.
4. Confirmar la agrupación y revisar el asiento inicial generado.

### Crear una remesa

1. Seleccionar efectos aptos para remesa.
2. Ejecutar **Crear remesa** o incorporarlos desde una remesa existente.
3. Revisar empresa propia, diario bancario, cuenta bancaria de la empresa, vencimiento y concepto.
4. Confirmar y comprobar el asiento inicial y los efectos incluidos.

### Saldar o devolver

Desde la ficha del efecto, agrupación o remesa, utilizar las acciones disponibles según su estado. Seleccionar el diario, el documento de pago y la fecha; cuando corresponda, completar los gastos, comisiones y sus cuentas. Las opciones disponibles dependen del estado y de los pagos ya registrados.

## Facturas y facturas rectificativas

### Creación automática

Al contabilizar una factura compatible, el módulo examina sus líneas contables de vencimiento pendientes y crea un efecto por línea, evitando duplicar vencimientos que ya estén vinculados.

### Importación de facturas anteriores

En el listado de facturas:

1. Seleccionar una o varias facturas/facturas rectificativas contabilizadas.
2. Abrir el menú **Acción**.
3. Ejecutar **Generar efectos de cartera**.

La acción admite los cuatro tipos indicados anteriormente. La selección debe estar contabilizada y las compañías deben estar activas para el usuario. Los saldos pendientes se toman de los apuntes contables; los documentos totalmente pagados no generan nuevos efectos.

La acción es atómica: si una factura, vencimiento o creación no supera las validaciones, Odoo revierte los cambios del lote.

### Signo y dirección

La dirección se obtiene del signo del saldo del vencimiento, no únicamente del tipo de documento. Por ejemplo:

| Documento | Signo habitual del vencimiento | Dirección |
|---|---:|---|
| Factura de cliente | Positivo | Recibir dinero |
| Rectificativa de cliente | Negativo | Enviar dinero |
| Factura de proveedor | Negativo | Enviar dinero |
| Rectificativa de proveedor | Positivo | Recibir dinero |

El resultado efectivo siempre depende del saldo residual contable de cada vencimiento.

## Documentos de pago

El catálogo de documentos de pago clasifica las operaciones de cartera y permite indicar si un documento es remesable. El documento seleccionado se guarda en el histórico de la operación.

El método técnico **Manual** de Odoo se conserva internamente para crear el pago/asiento; no es el dato que debe seleccionar el usuario en el asistente de cartera. El usuario trabaja con el campo **Documento de pago**.

## Numeración

El módulo utiliza una secuencia para el **Nº Efecto** de las fichas de cartera y una numeración común de **Nº Cartera** para agrupaciones y remesas. Los números se asignan al crear los contenedores, incluso antes de añadirles efectos.

Las migraciones del módulo incluyen recuperación de números ausentes en agrupaciones/remesas antiguas. La secuencia de cartera está diseñada para no retroceder ni reutilizar números ya emitidos.

## Seguridad y permisos

Los permisos se apoyan en los grupos estándar de contabilidad de Odoo:

- **Usuarios de contabilidad** (`account.group_account_user`): lectura, creación y operación de efectos, agrupaciones, remesas y asistentes, según las reglas de acceso del modelo.
- **Responsables de contabilidad** (`account.group_account_manager`): administración del catálogo de documentos de pago.

El acceso también está sujeto a las compañías habilitadas para cada usuario y a las reglas multiempresa de Odoo.

## Actualización

Antes de actualizar:

1. Realizar copia de seguridad de la base de datos.
2. Realizar copia del filestore.
3. Sustituir el código del addon por la nueva versión.
4. Reiniciar Odoo.
5. Actualizar el módulo, sin desinstalarlo.

Las carpetas `migrations/` contienen scripts de migración asociados a versiones concretas del módulo. Odoo los ejecuta durante la actualización cuando corresponde a la versión instalada y a la versión destino.

No se recomienda desinstalar el módulo para actualizarlo, ya que se perderían relaciones e históricos gestionados por sus modelos.

## Estructura del módulo

```text
l10n_es_effects/
├── __init__.py
├── __manifest__.py
├── data/
│   ├── payment_document_data.xml
│   └── sequence.xml
├── migrations/
│   └── <version>/post-migration.py
├── models/
│   ├── account_move.py
│   ├── account_payment.py
│   ├── effect.py
│   ├── effect_group.py
│   ├── effect_history.py
│   ├── payment_document.py
│   ├── payment_register.py
│   ├── remittance.py
│   └── asistentes y líneas auxiliares
├── security/
│   └── ir.model.access.csv
├── static/
│   ├── description/
│   └── src/js/
└── views/
    ├── account_move_views.xml
    ├── effect_views.xml
    ├── group_views.xml
    ├── menu.xml
    ├── payment_document_views.xml
    ├── payment_register_views.xml
    └── remittance_views.xml
```

## Alcance

Este módulo está orientado a la gestión de efectos, agrupaciones, remesas, liquidaciones, devoluciones e históricos contables en Odoo 18 con localización española.

No incluye funcionalidades de factoring, confirming ni descuento de efectos.

> **Nota de despliegue:** antes de actualizar una base de datos de producción, se recomienda probar la versión en una copia reciente de la base de datos y verificar contabilización, conciliación, saldados parciales y devoluciones con los diarios y cuentas reales de la empresa.
