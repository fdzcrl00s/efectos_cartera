from odoo import api, fields, models


class AccountMove(models.Model):
    _inherit = 'account.move'

    effect_ids = fields.One2many(
        'account.effect',
        'move_id',
        string='Efectos',
        readonly=True,
    )
    effect_count = fields.Integer(
        string='Efectos',
        compute='_compute_effect_count',
    )

    @api.depends('effect_ids')
    def _compute_effect_count(self):
        for move in self:
            move.effect_count = len(move.effect_ids)

    def action_open_effects(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Efectos',
            'res_model': 'account.effect',
            'view_mode': 'list,form',
            'domain': [('move_id', '=', self.id)],
            'context': {'default_move_id': self.id},
        }

    def action_post(self):
        result = super().action_post()

        Effect = self.env['account.effect']
        invoice_moves = self.filtered(
            lambda m: m.is_invoice(include_receipts=True)
            and m.state == 'posted'
            and m.move_type in ('out_invoice', 'out_refund', 'in_invoice', 'in_refund')
        )

        for move in invoice_moves:
            account_type = (
                'asset_receivable'
                if move.move_type in ('out_invoice', 'out_refund')
                else 'liability_payable'
            )

            for line in move.line_ids.filtered(
                lambda l: l.account_type == account_type and not l.reconciled
            ):
                residual = (
                    abs(line.amount_residual_currency)
                    if line.currency_id
                    else abs(line.amount_residual)
                )
                if not residual:
                    continue

                if Effect.search_count([('move_line_id', '=', line.id)]):
                    continue

                Effect.create({
                    'company_id': move.company_id.id,
                    'partner_id': move.partner_id.id,
                    'company_type': (
                        'customer'
                        if move.move_type in ('out_invoice', 'out_refund')
                        else 'supplier'
                    ),
                    'move_id': move.id,
                    'move_line_id': line.id,
                    'reference': move.name,
                    'due_date': (
                        line.date_maturity
                        or move.invoice_date_due
                        or move.invoice_date
                        or move.date
                    ),
                    'effect_type': 'effect',
                    'amount': residual,
                    'currency_id': (
                        line.currency_id.id
                        or move.company_id.currency_id.id
                    ),
                })

        return result
