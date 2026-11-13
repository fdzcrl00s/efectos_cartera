from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountPayment(models.Model):
    _inherit = 'account.payment'

    cartera_settled = fields.Boolean(
        string='Liquidado por cartera',
        default=False,
        readonly=True,
        copy=False,
        index=True,
        help='Indica que el movimiento de cartera está contabilizado y liquidado, aunque el diario utilice una cuenta transitoria.',
    )
    cartera_consolidated = fields.Boolean(
        string='Pago de cartera conjunto',
        default=False,
        readonly=True,
        copy=False,
        index=True,
        help='Registro de pago visible por cliente asociado a un único asiento conjunto de cartera.',
    )
    cartera_effect_ids = fields.Many2many(
        'account.effect',
        'account_payment_cartera_effect_rel',
        'payment_id', 'effect_id',
        string='Efectos de cartera',
        readonly=True,
        copy=False,
    )
    cartera_container_history_id = fields.Many2one(
        'account.effect.container.payment.history',
        string='Operación conjunta de cartera',
        readonly=True,
        copy=False,
        ondelete='restrict',
    )

    @api.depends(
        'reconciled_invoice_ids.payment_state', 'reconciled_bill_ids.payment_state',
        'move_id.line_ids.amount_residual', 'cartera_settled', 'move_id.state',
    )
    def _compute_state(self):
        super()._compute_state()
        for payment in self.filtered('cartera_settled'):
            if payment.move_id and payment.move_id.state == 'posted' and payment.state not in ('canceled', 'rejected'):
                payment.state = 'paid'

    @api.depends(
        'move_id.line_ids.matched_debit_ids', 'move_id.line_ids.matched_credit_ids',
        'invoice_ids', 'cartera_effect_ids', 'cartera_effect_ids.move_id',
        'cartera_effect_ids.move_line_id.move_id',
    )
    def _compute_stat_buttons_from_reconciliation(self):
        super()._compute_stat_buttons_from_reconciliation()
        for payment in self.filtered('cartera_consolidated'):
            effects = payment.cartera_effect_ids
            source_moves = effects.mapped('move_id') | effects.mapped('move_line_id.move_id')
            invoices = source_moves.filtered(lambda move: move.is_invoice(include_receipts=True))
            payment.reconciled_invoice_ids = invoices.filtered(lambda move: move.is_sale_document(include_receipts=True))
            payment.reconciled_bill_ids = invoices.filtered(lambda move: move.is_purchase_document(include_receipts=True))
            payment.reconciled_invoices_count = len(payment.reconciled_invoice_ids)
            payment.reconciled_bills_count = len(payment.reconciled_bill_ids)
            if payment.reconciled_invoice_ids and not payment.reconciled_bill_ids:
                payment.reconciled_invoices_type = 'invoice'
            elif payment.reconciled_bill_ids and not payment.reconciled_invoice_ids:
                payment.reconciled_invoices_type = 'invoice'
            else:
                payment.reconciled_invoices_type = False

    @api.depends(
        'move_id.amount_total_signed', 'amount', 'payment_type', 'currency_id',
        'date', 'company_id', 'company_currency_id',
    )
    def _compute_amount_company_currency_signed(self):
        super()._compute_amount_company_currency_signed()
        for payment in self.filtered('cartera_consolidated'):
            sign = 1.0 if payment.payment_type == 'inbound' else -1.0
            payment.amount_company_currency_signed = sign * payment.currency_id._convert(
                payment.amount,
                payment.company_id.currency_id,
                payment.company_id,
                payment.date,
                round=True,
            )

    def _check_cartera_shared_move(self, operation):
        if self.filtered('cartera_consolidated') and not self.env.context.get('cartera_internal_state_update'):
            raise UserError(_(
                'Este pago forma parte de un asiento conjunto de cartera. '
                'No se puede %(operation)s de forma individual porque afectaría a otros clientes. '
                'Utiliza la acción correspondiente desde la agrupación o remesa.'
            ) % {'operation': operation})

    def action_post(self):
        self._check_cartera_shared_move(_('confirmar'))
        # Ensure the bank/cash journal has the OCA shared entry sequence before
        # account.payment posts its generated account.move. This is deliberately
        # done here as well as in account.move.action_post so payment-register
        # flows cannot reach OCA with entry_number_sequence_id=False.
        if 'entry_number_sequence_id' in self.env['account.journal']._fields:
            remittance_model = self.env['account.effect.remittance']
            for journal in self.mapped('journal_id').filtered(lambda item: item):
                remittance_model._ensure_journal_entry_number_sequence(journal)
        return super().action_post()

    def action_validate(self):
        self._check_cartera_shared_move(_('validar'))
        return super().action_validate()

    def action_reject(self):
        self._check_cartera_shared_move(_('rechazar'))
        return super().action_reject()

    def mark_as_sent(self):
        self._check_cartera_shared_move(_('marcar como enviado'))
        return super().mark_as_sent()

    def unmark_as_sent(self):
        self._check_cartera_shared_move(_('desmarcar como enviado'))
        return super().unmark_as_sent()

    def action_cancel(self):
        self._check_cartera_shared_move(_('anular'))
        return super().action_cancel()

    def action_draft(self):
        self._check_cartera_shared_move(_('volver a borrador'))
        return super().action_draft()

    def button_request_cancel(self):
        self._check_cartera_shared_move(_('solicitar la anulación'))
        return super().button_request_cancel()

    def unlink(self):
        self._check_cartera_shared_move(_('eliminar'))
        return super().unlink()

    def copy(self, default=None):
        self._check_cartera_shared_move(_('duplicar'))
        return super().copy(default=default)

    def write(self, vals):
        protected_fields = {
            'move_id', 'journal_id', 'company_id', 'partner_id', 'partner_type',
            'payment_type', 'amount', 'currency_id', 'date', 'payment_method_line_id',
            'cartera_consolidated', 'cartera_effect_ids', 'cartera_container_history_id', 'cartera_settled', 'state',
        }
        if (
            self.filtered('cartera_consolidated')
            and protected_fields.intersection(vals)
            and not self.env.context.get('cartera_internal_state_update')
        ):
            self._check_cartera_shared_move(_('modificar'))
        return super().write(vals)
