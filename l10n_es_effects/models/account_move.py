from odoo import api, fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    effect_ids = fields.One2many('account.effect', 'move_id', string='Efectos', readonly=True)
    effect_count = fields.Integer(compute='_compute_effect_count', string='Efectos')

    @api.depends('effect_ids')
    def _compute_effect_count(self):
        for move in self:
            move.effect_count = len(move.effect_ids)

    def action_open_effects(self):
        self.ensure_one()
        return {
            'name': 'Cartera de efectos',
            'type': 'ir.actions.act_window',
            'res_model': 'account.effect',
            'view_mode': 'list,form',
            'domain': [('move_id', '=', self.id)],
            'context': {'default_move_id': self.id},
        }

    def action_post(self):
        result = super().action_post()
        Effect = self.env['account.effect']

        for move in self:
            if move.state != 'posted':
                continue
            if move.move_type not in ('out_invoice', 'in_invoice'):
                continue

            account_type = 'asset_receivable' if move.move_type == 'out_invoice' else 'liability_payable'
            lines = move.line_ids.filtered(
                lambda line:
                    line.account_type == account_type
                    and line.display_type == 'payment_term'
                    and not line.reconciled
                    and line.balance != 0
            )

            for line in lines:
                if Effect.search_count([('move_line_id', '=', line.id)]):
                    continue

                currency = line.currency_id or move.currency_id
                amount = abs(line.amount_residual_currency) if line.currency_id and line.currency_id != move.company_currency_id else abs(line.amount_residual)

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
