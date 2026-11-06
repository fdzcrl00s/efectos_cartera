from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountEffectManualPaymentWizard(models.TransientModel):
    _name = 'account.effect.manual.payment.wizard'
    _description = 'Saldar efecto manual'

    effect_id = fields.Many2one('account.effect', string='Efecto', required=True, readonly=True)
    partner_id = fields.Many2one(related='effect_id.partner_id', string='Cliente / proveedor', readonly=True)
    company_id = fields.Many2one(related='effect_id.company_id', readonly=True)
    company_type = fields.Selection(related='effect_id.company_type', readonly=True)
    manual_account_id = fields.Many2one(related='effect_id.manual_account_id', string='Cuenta del efecto', readonly=True)
    currency_id = fields.Many2one(related='effect_id.currency_id', readonly=True)
    amount = fields.Monetary(string='Importe a saldar', required=True, currency_field='currency_id')
    amount_pending = fields.Monetary(string='Pendiente máximo', compute='_compute_amount_pending', currency_field='currency_id')
    payment_date = fields.Date(string='Fecha de pago', required=True, default=fields.Date.context_today)
    journal_id = fields.Many2one(
        'account.journal', string='Diario bancario', required=True,
        domain="[('company_id', '=', company_id), ('type', 'in', ('bank', 'cash')), ('default_account_id', '!=', False)]",
    )

    @api.depends('effect_id', 'effect_id.amount', 'effect_id.state', 'effect_id.move_line_id.amount_residual', 'effect_id.move_line_id.amount_residual_currency')
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
        vals.update({
            'effect_id': effect.id,
            'amount': effect._cartera_pending_amount(),
            'payment_date': fields.Date.context_today(self),
        })
        if 'journal_id' in fields_list:
            journal = effect.bank_journal_id
            if not journal or journal.company_id != effect.company_id or not journal.default_account_id:
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
        if not effect or effect.is_container or (effect.move_id and effect.move_id.move_type != 'entry'):
            raise UserError(_('Selecciona un efecto manual individual sin factura u originado por una devolución.'))
        if effect.group_id or effect.remittance_id:
            raise UserError(_('Los efectos agrupados o remesados deben saldarse desde su agrupación o remesa.'))
        if effect.state not in ('pending', 'grouped', 'remitted'):
            raise UserError(_('Solo se pueden saldar efectos pendientes.'))
        currency = effect.currency_id
        pending = effect._cartera_pending_amount()
        if currency.is_zero(self.amount) or self.amount < 0:
            raise UserError(_('El importe debe ser mayor que cero.'))
        if currency.compare_amounts(self.amount, pending) > 0:
            raise UserError(_('El importe no puede superar el pendiente del efecto (%s).') % pending)

        source = effect.move_line_id
        root_effect = effect.portfolio_chain_id or effect
        if not source and root_effect != effect:
            source = root_effect.move_line_id
        if (not source or source.reconciled or source.move_id.state != 'posted') and root_effect.opening_move_id:
            source = root_effect._ensure_manual_open_item_line()
        if not source or source.reconciled or source.move_id.state != 'posted':
            raise UserError(_('El efecto no tiene un apunte contable abierto para conciliar.'))
        account = source.account_id
        if not account.reconcile:
            raise UserError(_('La cuenta %s no permite conciliación.') % account.display_name)
        if effect.manual_account_id and effect.manual_account_id != account:
            raise UserError(_('La cuenta del efecto no coincide con el apunte contable de origen.'))
        if source.partner_id and effect.partner_id and source.partner_id != effect.partner_id:
            raise UserError(_('El apunte contable pertenece a un tercero distinto del efecto.'))
        source_residual = (
            source.amount_residual_currency
            if source.currency_id and source.currency_id != effect.company_id.currency_id
            else source.amount_residual
        )
        if currency.compare_amounts(self.amount, abs(source_residual)) > 0:
            raise UserError(_('El importe supera el saldo que todavía queda abierto en el apunte contable (%s).') % abs(source_residual))

        journal = self.journal_id
        if not journal or journal.company_id != effect.company_id or journal.type not in ('bank', 'cash') or not journal.default_account_id:
            raise UserError(_('Selecciona un diario bancario o de caja con cuenta de liquidez de la misma compañía.'))
        company_currency = effect.company_id.currency_id
        amount_company = currency._convert(
            self.amount, company_currency, effect.company_id, self.payment_date, round=True,
        ) if currency != company_currency else self.amount
        # The source-line balance determines the direction: a debit residual
        # is a right to collect; a credit residual is an obligation to pay.
        is_receipt = source_residual > 0
        # Receipt: debit bank / credit the effect's balance account.
        # Payment: debit the effect's balance account / credit bank.
        balance_debit = 0.0 if is_receipt else amount_company
        balance_credit = amount_company if is_receipt else 0.0
        balance_currency = -self.amount if is_receipt else self.amount
        bank_debit = amount_company if is_receipt else 0.0
        bank_credit = 0.0 if is_receipt else amount_company

        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': self.payment_date,
            'journal_id': journal.id,
            'ref': _('Cobro de efecto nº %s') % effect.name if is_receipt else _('Pago de efecto nº %s') % effect.name,
            'line_ids': [
                (0, 0, {
                    'name': effect.reference or _('Liquidación efecto nº %s') % effect.name,
                    'account_id': account.id,
                    'partner_id': source.partner_id.id if source.partner_id else False,
                    'currency_id': currency.id,
                    'amount_currency': balance_currency,
                    'debit': balance_debit,
                    'credit': balance_credit,
                    'date_maturity': self.payment_date,
                    'effect_id': effect.id,
                }),
                (0, 0, {
                    'name': _('Banco · Efecto nº %s') % effect.name,
                    'account_id': journal.default_account_id.id,
                    'debit': bank_debit,
                    'credit': bank_credit,
                }),
            ],
        })
        move.action_post()
        payment_line = move.line_ids.filtered(lambda line: line.account_id == account and line.effect_id == effect)[:1]
        if not payment_line:
            raise UserError(_('No se ha podido localizar la línea de liquidación del efecto.'))
        (source | payment_line).filtered(lambda line: not line.reconciled).reconcile()
        source.invalidate_recordset(['amount_residual', 'amount_residual_currency', 'reconciled'])
        if source.reconciled or currency.is_zero(effect._settlement_pending_amount()):
            effect.write({'state': 'paid', 'paid_date': self.payment_date})
            effect._log_situation('paid', _('Efecto saldado mediante asiento %s') % move.name)
        else:
            effect._log_situation(effect.state, _('Pago parcial registrado mediante asiento %s') % move.name)

        self.env['account.effect.payment.history'].create({
            'effect_id': effect.id,
            'date': self.payment_date,
            'move_id': move.id,
            'journal_id': journal.id,
            'amount': currency.round(self.amount),
            'note': _('Liquidación manual contra la cuenta %s') % account.display_name,
        })
        return {'type': 'ir.actions.client', 'tag': 'reload'}
