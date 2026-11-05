from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountEffectManualPaymentWizard(models.TransientModel):
    _name = 'account.effect.manual.payment.wizard'
    _description = 'Saldar efecto sin factura'

    effect_id = fields.Many2one('account.effect', string='Efecto', required=True, readonly=True)
    partner_id = fields.Many2one(related='effect_id.partner_id', string='Cliente / proveedor', readonly=True)
    company_id = fields.Many2one(related='effect_id.company_id', readonly=True)
    company_type = fields.Selection(related='effect_id.company_type', readonly=True)
    currency_id = fields.Many2one(related='effect_id.currency_id', readonly=True)
    amount = fields.Monetary(string='Importe a saldar', required=True, currency_field='currency_id')
    amount_pending = fields.Monetary(string='Pendiente máximo', compute='_compute_amount_pending', currency_field='currency_id')
    payment_date = fields.Date(string='Fecha de pago', required=True, default=fields.Date.context_today)
    journal_id = fields.Many2one(
        'account.journal', string='Diario bancario', required=True,
        domain="[('company_id', '=', company_id), ('type', 'in', ('bank', 'cash'))]",
    )

    @api.depends('effect_id', 'effect_id.amount', 'effect_id.state', 'effect_id.active')
    def _compute_amount_pending(self):
        for wizard in self:
            wizard.amount_pending = wizard.effect_id._cartera_pending_amount() if wizard.effect_id else 0.0

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        effect_id = self.env.context.get('default_effect_id') or self.env.context.get('effect_id')
        effect = self.env['account.effect'].browse(effect_id).exists() if effect_id else self.env['account.effect']
        if not effect:
            return vals
        pending = effect._cartera_pending_amount()
        vals.update({
            'effect_id': effect.id,
            'amount': pending,
            'payment_date': fields.Date.context_today(self),
        })
        if 'journal_id' in fields_list:
            journal = effect.bank_journal_id
            if journal and journal.company_id != effect.company_id:
                journal = self.env['account.journal']
            partner = effect.partner_id
            if not journal and partner:
                property_name = 'property_inbound_payment_method_line_id' if effect.company_type == 'customer' else 'property_outbound_payment_method_line_id'
                method_line = getattr(partner.with_company(effect.company_id), property_name, self.env['account.payment.method.line'])
                journal = method_line.journal_id if method_line else self.env['account.journal']
            if not journal:
                journal = self.env['account.journal'].search([
                    ('company_id', '=', effect.company_id.id),
                    ('type', 'in', ('bank', 'cash')),
                    ('default_account_id', '!=', False),
                ], order='type, sequence, id', limit=1)
            if journal:
                vals['journal_id'] = journal.id
        return vals

    def action_create_payment(self):
        self.ensure_one()
        effect = self.effect_id.exists()
        if not effect or effect.is_container:
            raise UserError(_('Selecciona un efecto individual válido.'))
        if effect.state not in ('pending', 'grouped', 'remitted'):
            raise UserError(_('Solo se pueden saldar efectos pendientes.'))
        pending = effect._cartera_pending_amount()
        currency = effect.currency_id
        if currency.is_zero(self.amount) or self.amount < 0:
            raise UserError(_('El importe debe ser mayor que cero.'))
        if currency.compare_amounts(self.amount, pending) > 0:
            raise UserError(_('El importe no puede superar el pendiente del efecto (%s).') % pending)

        journal = self.journal_id
        if not journal or journal.company_id != effect.company_id or journal.type not in ('bank', 'cash'):
            raise UserError(_('Selecciona un diario bancario o de caja de la misma compañía.'))
        payment_type = 'inbound' if effect.company_type == 'customer' else 'outbound'
        method_lines = journal.inbound_payment_method_line_ids if payment_type == 'inbound' else journal.outbound_payment_method_line_ids
        method_line = method_lines.filtered(lambda line: line.code == 'manual')[:1] or method_lines[:1]
        if not method_line:
            raise UserError(_(
                'El diario %(journal)s no tiene un método de pago disponible. '
                'Configura el método Manual en el diario.'
            ) % {'journal': journal.display_name})

        partner = effect.partner_id
        destination_account = effect.counterpart_account_id
        if not destination_account and partner:
            partner = partner.with_company(effect.company_id)
            destination_account = (
                partner.property_account_receivable_id if effect.company_type == 'customer'
                else partner.property_account_payable_id
            )
        if not destination_account:
            raise UserError(_(
                'El efecto no tiene una cuenta de contrapartida. Indica un cliente/proveedor con cuenta contable '
                'o configura la cuenta de contrapartida del efecto.'
            ))

        payment_vals = {
            'date': self.payment_date,
            'journal_id': journal.id,
            'company_id': effect.company_id.id,
            'amount': currency.round(self.amount),
            'currency_id': currency.id,
            'payment_type': payment_type,
            'partner_type': effect.company_type,
            'partner_id': effect.partner_id.id if effect.partner_id else False,
            'partner_bank_id': effect.partner_bank_id.id if effect.partner_bank_id else False,
            'payment_method_line_id': method_line.id,
            'destination_account_id': destination_account.id,
            'memo': _('Efecto nº %s') % (effect.cartera_number or effect.name),
            'payment_reference': _('Efecto nº %s') % (effect.cartera_number or effect.name),
        }
        payment = self.env['account.payment'].with_company(effect.company_id).create(payment_vals)
        payment.action_post()
        payment.write({'cartera_settled': True})

        paid_amount = currency.round(self.amount)
        residual = currency.round(pending - paid_amount)
        original_amount = effect.amount
        effect.write({
            'amount': paid_amount,
            'state': 'paid',
            'paid_date': self.payment_date,
            'payment_id': payment.id,
        })
        effect._log_situation('paid', _('Efecto saldado mediante pago %s') % payment.display_name)
        self.env['account.effect.payment.history'].create({
            'effect_id': effect.id,
            'date': self.payment_date,
            'payment_id': payment.id,
            'move_id': payment.move_id.id,
            'journal_id': journal.id,
            'amount': paid_amount,
            'note': _('Pago de efecto sin factura asociada'),
        })

        if currency.compare_amounts(residual, 0.0) > 0:
            continuation = self.env['account.effect'].create({
                'company_id': effect.company_id.id,
                'company_type': effect.company_type,
                'partner_id': effect.partner_id.id if effect.partner_id else False,
                'counterpart_account_id': effect.counterpart_account_id.id if effect.counterpart_account_id else False,
                'beneficiary_name': effect.beneficiary_name,
                'manual_category': effect.manual_category,
                'move_id': False,
                'move_line_id': False,
                'reference': effect.reference or False,
                'invoice_reference': effect.invoice_reference or False,
                'due_date': effect.due_date,
                'effect_type': 'effect',
                'bank_journal_id': journal.id,
                'partner_bank_id': effect.partner_bank_id.id if effect.partner_bank_id else False,
                'payment_direction': effect.payment_direction,
                'amount': residual,
                'currency_id': currency.id,
                'state': 'pending',
                'portfolio_chain_id': effect.id,
                'cartera_number': effect.cartera_number or False,
                'active': True,
            })
            continuation._log_situation('pending', _('Pendiente tras pago parcial de %s') % effect.name)

        return {'type': 'ir.actions.client', 'tag': 'reload'}
