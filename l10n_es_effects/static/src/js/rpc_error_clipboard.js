/** @odoo-module **/

import { RPCErrorDialog } from "@web/core/errors/error_dialogs";
import { patch } from "@web/core/utils/patch";

// Odoo's native handler assumes navigator.clipboard exists. Browsers hide that
// API on non-secure HTTP origins (for example, a QNAP reverse-proxy URL).
// Keep the native API when available and fall back to execCommand for HTTP.
patch(RPCErrorDialog.prototype, {
    async onClickClipboard() {
        const text = `${this.props.name || ""}\n\n${this.props.message || ""}\n\n${this.contextDetails || ""}\n\n${this.traceback || this.props.traceback || ""}`;
        const clipboard = globalThis.navigator?.clipboard;
        if (clipboard && typeof clipboard.writeText === "function") {
            await clipboard.writeText(text);
            this.showTooltip();
            return;
        }

        const textarea = document.createElement("textarea");
        textarea.value = text;
        textarea.setAttribute("readonly", "");
        textarea.style.position = "fixed";
        textarea.style.opacity = "0";
        textarea.style.pointerEvents = "none";
        document.body.appendChild(textarea);
        textarea.select();
        textarea.setSelectionRange(0, textarea.value.length);
        let copied = false;
        try {
            copied = document.execCommand("copy");
        } finally {
            textarea.remove();
        }
        if (copied) {
            this.showTooltip();
        } else {
            throw new Error("El navegador no permite copiar el texto. Accede a Odoo mediante HTTPS o copia el error manualmente.");
        }
    },
});
