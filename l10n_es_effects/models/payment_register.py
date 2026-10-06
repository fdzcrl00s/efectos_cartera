from odoo import fields, models


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    def action_create_payments(self):
        active_model = self.env.context.get('active_model')
        active_ids = self.env.context.get('active_ids', [])
        effects = self.env['account.effect']
        before_pending = {}
        if active_model == 'account.move.line' and active_ids:
            effects = self.env['account.effect'].search([('move_line_id', 'in', active_ids)])
            before_pending = {effect.id: effect.amount_pending for effect in effects}

        result = super().action_create_payments()

        for effect in effects:
            effect.invalidate_recordset(['amount_pending', 'payment_state'])
            paid_delta = max(before_pending.get(effect.id, effect.amount_pending) - effect.amount_pending, 0)
            if effect.move_line_id.reconciled:
                effect._set_state('paid', 'Pago conciliado')
            elif paid_delta > 0:
                effect._log_situation('pending', 'Pago parcial')

            payment_moves = (effect.move_line_id.matched_debit_ids.mapped('debit_move_id') | effect.move_line_id.matched_credit_ids.mapped('credit_move_id')).mapped('move_id')
            payments = self.env['account.payment'].search([('move_id', 'in', payment_moves.ids)], order='id desc') if payment_moves else self.env['account.payment']
            payment = payments[:1]
            if payment:
                effect.payment_id = payment.id
                if paid_delta > 0:
                    self.env['account.effect.payment.history'].create({
                        'effect_id': effect.id,
                        'date': fields.Date.context_today(self),
                        'payment_id': payment.id,
                        'journal_id': payment.journal_id.id,
                        'amount': paid_delta,
                        'note': payment.ref or payment.name,
                    })

        remittances = effects.mapped('remittance_id')
        for remittance in remittances:
            pending = remittance.effect_ids.filtered(lambda e: e.state not in ('paid', 'returned', 'uncollectible') and e.move_line_id and not e.move_line_id.reconciled)
            if not pending and remittance.effect_ids:
                remittance.state = 'paid'
            elif len(pending) < len(remittance.effect_ids):
                remittance.state = 'partial'

        return result
