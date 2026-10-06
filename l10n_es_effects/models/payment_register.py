from odoo import models


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    def action_create_payments(self):
        active_model = self.env.context.get('active_model')
        active_ids = self.env.context.get('active_ids', [])
        effects = self.env['account.effect']
        if active_model == 'account.move.line' and active_ids:
            effects = self.env['account.effect'].search([
                ('move_line_id', 'in', active_ids),
            ])

        result = super().action_create_payments()

        paid_effects = effects.filtered(lambda effect: effect.move_line_id.reconciled)
        if paid_effects:
            paid_effects.write({'state': 'paid'})

        remittances = paid_effects.mapped('remittance_id')
        for remittance in remittances:
            effects_with_moves = remittance.effect_ids.filtered('move_line_id')
            if effects_with_moves and all(effect.move_line_id.reconciled for effect in effects_with_moves):
                remittance.state = 'paid'
            elif paid_effects.filtered(lambda effect: effect.remittance_id == remittance):
                remittance.state = 'partial'

        return result
