from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    effect_group_ids = fields.Many2many(
        'account.effect.group', 'account_move_effect_group_rel', 'move_id', 'group_id',
        string='Agrupaciones de cartera', readonly=True, copy=False,
    )
    effect_remittance_id = fields.Many2one(
        'account.effect.remittance', string='Remesa de cartera', readonly=True, copy=False,
    )
    effect_ids = fields.One2many('account.effect', 'move_id', string='Efectos', readonly=True)
    effect_count = fields.Integer(compute='_compute_effect_count', string='Efectos')

    @api.depends('effect_ids')
    def _compute_effect_count(self):
        for move in self:
            move.effect_count = len(move.effect_ids)

    def action_open_effects(self):
        self.ensure_one()
        return {
            'name': 'Cartera', 'type': 'ir.actions.act_window', 'res_model': 'account.effect',
            'view_mode': 'list,form', 'domain': [('move_id', '=', self.id)],
            'context': {'default_move_id': self.id, 'default_company_type': 'customer' if self.move_type == 'out_invoice' else 'supplier'},
        }

    def action_post(self):
        result = super().action_post()
        Effect = self.env['account.effect']
        for move in self:
            if move.state != 'posted' or move.move_type not in ('out_invoice', 'in_invoice'):
                continue
            account_type = 'asset_receivable' if move.move_type == 'out_invoice' else 'liability_payable'
            lines = move.line_ids.filtered(lambda line:
                line.account_type == account_type and line.display_type == 'payment_term'
                and not line.reconciled and line.balance != 0)
            for line in lines:
                if Effect.search_count([('move_line_id', '=', line.id)]):
                    continue
                currency = line.currency_id or move.currency_id
                amount = (abs(line.amount_residual_currency)
                          if line.currency_id and line.currency_id != move.company_currency_id
                          else abs(line.amount_residual))
                Effect.create({
                    'partner_id': move.partner_id.id,
                    'company_type': 'customer' if move.move_type == 'out_invoice' else 'supplier',
                    'move_id': move.id,
                    'move_line_id': line.id,
                    'reference': move.name or move.ref or '',
                    'due_date': line.date_maturity or move.invoice_date_due or move.invoice_date or move.date,
                    'amount': amount,
                    'currency_id': currency.id,
                })
        return result

    def _reverse_cartera_payment_entry(self, reversal_date=None, note=None):
        """Reverse a cartera payment move and restore its open counterpart balances.

        The liquidity line is deliberately left for bank reconciliation. Receivable/payable or other reconcilable balance-account partial reconciliations
        are removed before the reversal is posted; the original and reversal balance
        lines are then reconciled with each other, restoring the prior open balance.
        """
        self.ensure_one()
        if self.state != 'posted':
            raise UserError(_('Solo se pueden anular asientos de cartera publicados.'))

        liquidity_account = self.journal_id.default_account_id
        liquidity_lines = self.line_ids.filtered(lambda line: line.account_id.account_type == 'asset_cash' or (liquidity_account and line.account_id == liquidity_account))
        counterpart_lines = self.line_ids.filtered(
            lambda line: line.account_id.reconcile and line not in liquidity_lines
        )
        if not counterpart_lines:
            raise UserError(_('El asiento no contiene líneas de balance conciliables para revertir.'))

        if any(line.matched_debit_ids or line.matched_credit_ids for line in liquidity_lines):
            raise UserError(_(
                'El asiento está conciliado con extractos bancarios. Deshaz primero la conciliación bancaria y vuelve a anular el pago.'
            ))

        # Remove both full and partial matches to the source effects/group balances.
        matched_counterparts = counterpart_lines.filtered(
            lambda line: line.matched_debit_ids or line.matched_credit_ids
        )
        if matched_counterparts:
            matched_counterparts.remove_move_reconcile()

        reversal = self._reverse_moves(default_values_list=[{
            'date': reversal_date or fields.Date.context_today(self),
            'ref': (self.ref or self.name or _('Liquidación de cartera')) + ' - ' + (note or _('Anulación')),
        }], cancel=False)
        reversal.action_post()

        reversal_liquidity_account = reversal.journal_id.default_account_id
        reversal_liquidity_lines = reversal.line_ids.filtered(lambda line: line.account_id.account_type == 'asset_cash' or (reversal_liquidity_account and line.account_id == reversal_liquidity_account))
        reversed_counterparts = reversal.line_ids.filtered(
            lambda line: line.account_id.reconcile and line not in reversal_liquidity_lines
        )
        company_currency = self.company_id.currency_id
        # Do not pair lines one by one: one payment can contain several effects
        # for the same partner/account, and the reversal can legally split or
        # regroup those lines. Reconcile each complete account/partner/currency
        # bucket instead. This also avoids pairing the wrong duplicate line.
        bucket_keys = set(
            (line.account_id.id, line.partner_id.id or False, line.currency_id.id or False)
            for line in (counterpart_lines | reversed_counterparts)
        )
        for account_id, partner_id, currency_id in bucket_keys:
            original_bucket = counterpart_lines.filtered(
                lambda line: line.account_id.id == account_id
                and (line.partner_id.id or False) == partner_id
                and (line.currency_id.id or False) == currency_id
            )
            reversal_bucket = reversed_counterparts.filtered(
                lambda line: line.account_id.id == account_id
                and (line.partner_id.id or False) == partner_id
                and (line.currency_id.id or False) == currency_id
            )
            if not original_bucket or not reversal_bucket:
                account = self.env['account.account'].browse(account_id)
                partner = self.env['res.partner'].browse(partner_id)
                raise UserError(_(
                    'No se ha podido localizar la contrapartida completa de la reversión '
                    '(%s, %s). La anulación se ha cancelado para no dejar saldos abiertos.'
                ) % (account.display_name, partner.display_name or ''))

            bucket = original_bucket | reversal_bucket
            currency = self.env['res.currency'].browse(currency_id) if currency_id else company_currency
            company_balance = sum(bucket.mapped('balance'))
            currency_balance = sum(bucket.mapped('amount_currency')) if currency_id else company_balance
            if not company_currency.is_zero(company_balance) or not currency.is_zero(currency_balance):
                account = self.env['account.account'].browse(account_id)
                partner = self.env['res.partner'].browse(partner_id)
                raise UserError(_(
                    'La reversión no cuadra para la cuenta %(account)s y el cliente/proveedor %(partner)s. '
                    'Debe: %(debit).2f · Haber: %(credit).2f. No se ha conciliado ningún apunte de ese grupo.'
                ) % {
                    'account': account.display_name,
                    'partner': partner.display_name or '',
                    'debit': sum(bucket.mapped('debit')),
                    'credit': sum(bucket.mapped('credit')),
                })

            bucket.filtered(lambda line: not line.reconciled).reconcile()
            if not all(bucket.mapped('reconciled')):
                account = self.env['account.account'].browse(account_id)
                raise UserError(_(
                    'La contrapartida %(account)s no ha quedado conciliada con su reversión. '
                    'La anulación se ha cancelado.'
                ) % {'account': account.display_name})
        return reversal


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    effect_id = fields.Many2one('account.effect', string='Efecto de cartera', readonly=True, copy=False, index=True)
    effect_group_id = fields.Many2one('account.effect.group', string='Agrupación de cartera', readonly=True, copy=False, index=True)
    effect_group_effect_id = fields.Many2one('account.effect', string='Efecto reclasificado', readonly=True, copy=False, index=True)
    effect_remittance_effect_id = fields.Many2one('account.effect', string='Efecto transferido a remesa', readonly=True, copy=False, index=True)
    effect_remittance_line_type = fields.Selection(
        [('source', 'Origen de remesa'), ('target', 'Saldo de remesa')],
        string='Tipo de línea de remesa', readonly=True, copy=False, index=True,
    )
    effect_remittance_origin_line_id = fields.Many2one(
        'account.move.line', string='Apunte origen de remesa', readonly=True, copy=False, index=True,
    )
    effect_ids = fields.Many2many('account.effect', 'account_move_line_effect_rel', 'line_id', 'effect_id', string='Efectos liquidados', readonly=True, copy=False)
