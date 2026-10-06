from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    effect_ids = fields.One2many('account.effect', 'move_id', string='Efectos de cartera', copy=False)
    effect_count = fields.Integer(compute='_compute_effect_count')

    def _compute_effect_count(self):
        grouped = self.env['account.effect'].read_group([('move_id', 'in', self.ids)], ['move_id'], ['move_id'])
        counts = {x['move_id'][0]: x['move_id_count'] for x in grouped if x.get('move_id')}
        for move in self:
            move.effect_count = counts.get(move.id, 0)

    def action_generate_effects(self):
        Effect = self.env['account.effect']
        created = Effect.browse()
        for move in self:
            if move.state != 'posted' or move.move_type not in ('out_invoice', 'out_refund', 'in_invoice', 'in_refund'):
                raise UserError(_('Solo se pueden generar efectos desde facturas o facturas rectificativas publicadas.'))
            lines = move.line_ids.filtered(
                lambda l: l.account_id.account_type in ('asset_receivable', 'liability_payable')
                and not l.reconciled and l.amount_residual
            )
            for line in lines:
                if Effect.search_count([('move_line_id', '=', line.id), ('active', '=', True)]):
                    continue
                is_customer = move.move_type in ('out_invoice', 'out_refund')
                amount = abs(line.amount_residual_currency) if line.currency_id and line.currency_id != move.company_currency_id else abs(line.amount_residual)
                created |= Effect.create({
                    'partner_id': move.partner_id.id,
                    'move_id': move.id,
                    'move_line_id': line.id,
                    'due_date': line.date_maturity or move.invoice_date_due or move.invoice_date or fields.Date.context_today(move),
                    'reference': move.payment_reference or move.name,
                    'amount': amount,
                    'company_id': move.company_id.id,
                    'bank_account_id': move.partner_id.bank_ids[:1].id,
                    'destination_account_id': line.account_id.id,
                    'company_type': 'customer' if is_customer else 'supplier',
                    'payment_type': 'receive' if is_customer else 'send',
                    'payment_method': 'direct_debit' if move.partner_id.bank_ids else 'bank_transfer',
                    'effect_type': 'effect',
                    'payment_state': 'pending',
                    'situation': 'pending',
                })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Efectos generados'),
            'res_model': 'account.effect',
            'view_mode': 'list,form',
            'domain': [('id', 'in', created.ids)],
        }

    def action_view_effects(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Efectos'),
            'res_model': 'account.effect',
            'view_mode': 'list,form',
            'domain': [('move_id', '=', self.id)],
            'context': {'default_move_id': self.id, 'default_partner_id': self.partner_id.id},
        }
