# Cartera de Efectos para Odoo 18 Community

Dos módulos:

- `l10n_es_effects`: efectos, cartera, agrupaciones y remesas.
- `l10n_es_effects_sepa`: extensión SEPA para remesas.

## Instalación por Git

Clonar el repositorio en un directorio que esté incluido en el `addons_path` del contenedor Odoo.

Ejemplo:

```bash
git clone <URL_DEL_REPOSITORIO> /ruta/de/addons/odoo18-cartera
```

Después reiniciar Odoo y actualizar la lista de aplicaciones.

## Importante

Este proyecto es un módulo Odoo normal con Python. **No se debe instalar mediante el botón de importación ZIP de módulos importables** de Odoo. Debe estar físicamente en un directorio del `addons_path`.

## Flujo inicial

Factura publicada -> Generar efectos -> Cartera -> Agrupar -> Remesa -> Generar SEPA.

La generación SEPA incluida es una primera implementación y debe validarse con el banco antes de usarla en producción. Para producción se recomienda integrar la remesa con OCA `bank-payment`/SEPA cuando esté disponible en la instalación.
