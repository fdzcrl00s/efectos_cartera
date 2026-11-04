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

        The liquidity line is deliberately left for bank reconciliation. Receivable
        and payable partial reconciliations are removed before the reversal is posted;
        then the original and reversal counterpart lines are reconciled with each
        other, leaving the underlying effects open again.
        """
        self.ensure_one()
        if self.state != 'posted':
            raise UserError(_('Solo se pueden anular asientos de cartera publicados.'))

        counterpart_lines = self.line_ids.filtered(
            lambda line: line.account_id.account_type in ('asset_receivable', 'liability_payable')
            and line.account_id.reconcile
        )
        if not counterpart_lines:
            raise UserError(_('El asiento no contiene contrapartidas de clientes o proveedores.'))

        liquidity_lines = self.line_ids.filtered(lambda line: line.account_id.account_type == 'asset_cash')
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

        reversed_counterparts = reversal.line_ids.filtered(
            lambda line: line.account_id.account_type in ('asset_receivable', 'liability_payable')
            and line.account_id.reconcile
        )
        company_currency = self.company_id.currency_id
        for original in counterpart_lines:
            candidates = reversed_counterparts.filtered(
                lambda line: line.account_id == original.account_id
                and line.partner_id == original.partner_id
                and line.currency_id == original.currency_id
                and not line.reconciled
                and company_currency.is_zero(line.balance + original.balance)
                and (
                    not original.currency_id
                    or original.currency_id == company_currency
                    or original.currency_id.is_zero(line.amount_currency + original.amount_currency)
                )
            ).sorted('id')
            candidate = candidates[:1]
            if not candidate:
                raise UserError(_(
                    'No se ha podido emparejar la contrapartida del asiento original con su reversión '
                    '(%s, %s). La anulación se ha cancelado para no dejar saldos abiertos.'
                ) % (original.account_id.display_name, original.partner_id.display_name or ''))
            pair = original | candidate
            pair.reconcile()
            if not all(pair.mapped('reconciled')):
                raise UserError(_(
                    'La contrapartida %s no ha quedado conciliada con su reversión. '
                    'La anulación se ha cancelado.'
                ) % original.account_id.display_name)
        return reversal


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    effect_id = fields.Many2one('account.effect', string='Efecto de cartera', readonly=True, copy=False, index=True)
    effect_group_id = fields.Many2one('account.effect.group', string='Agrupación de cartera', readonly=True, copy=False, index=True)
    effect_group_effect_id = fields.Many2one('account.effect', string='Efecto reclasificado', readonly=True, copy=False, index=True)
    effect_ids = fields.Many2many('account.effect', 'account_move_line_effect_rel', 'line_id', 'effect_id', string='Efectos liquidados', readonly=True, copy=False)
