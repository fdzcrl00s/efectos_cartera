from odoo import fields, models, _
from odoo.exceptions import UserError


class AccountEffectRemittancePartialWizard(models.TransientModel):
    _name = 'account.effect.remittance.partial.wizard'
    _description = 'Saldado parcial de remesa'

    remittance_id = fields.Many2one('account.effect.remittance', required=True, readonly=True)
    effect_ids = fields.Many2many(
        'account.effect',
        'account_effect_remittance_partial_rel',
        'wizard_id', 'effect_id',
        string='Efectos a saldar',
        domain="[('remittance_id', '=', remittance_id), ('state', 'not in', ['paid', 'returned', 'uncollectible']), ('move_line_id', '!=', False)]",
        required=True,
    )

    def action_saldar(self):
        self.ensure_one()
        effects = self.effect_ids.filtered(lambda e: e.move_line_id and not e.move_line_id.reconciled)
        if not effects:
            raise UserError(_('Selecciona al menos un efecto con vencimiento pendiente.'))
        return self.remittance_id._payment_register_action(effects, _('Saldar parcialmente'))
