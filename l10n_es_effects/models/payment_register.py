from odoo import models


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    def action_create_payments(self):
        effect_id = self.env.context.get('effect_id')
        effect_remittance_id = self.env.context.get('effect_remittance_id')

        result = super().action_create_payments()

        payments = self.env['account.payment']
        if isinstance(result, dict):
            if result.get('res_id'):
                payments |= self.env['account.payment'].browse(result['res_id'])
            else:
                for item in result.get('domain', []):
                    if (
                        isinstance(item, (list, tuple))
                        and len(item) == 3
                        and item[0] == 'id'
                        and item[1] == 'in'
                    ):
                        payments |= self.env['account.payment'].browse(item[2])

        if effect_id and payments:
            effect = self.env['account.effect'].browse(effect_id).exists()
            if effect:
                effect.write({
                    'payment_id': payments[:1].id,
                    'state': 'paid',
                })

        if effect_remittance_id and payments:
            remittance = self.env['account.effect.remittance'].browse(
                effect_remittance_id
            ).exists()
            if remittance:
                effects = remittance.effect_ids.filtered(
                    lambda e: e.move_line_id and e.move_line_id.reconciled
                )
                for effect in effects:
                    if len(payments) == 1:
                        effect.payment_id = payments.id
                    effect.state = 'paid'

                if remittance.effect_ids and all(
                    effect.state == 'paid'
                    for effect in remittance.effect_ids
                ):
                    remittance.state = 'paid'

        return result
