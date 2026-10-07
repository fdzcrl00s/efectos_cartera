from odoo import api, fields, models, _
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

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        remittance_id = self.env.context.get('default_remittance_id') or self.env.context.get('remittance_id')
        if remittance_id:
            vals['remittance_id'] = remittance_id
            remittance = self.env['account.effect.remittance'].browse(remittance_id).exists()
            if remittance and 'effect_ids' in fields_list:
                effects = remittance.effect_ids.filtered(
                    lambda e: e.state not in ('paid', 'returned', 'uncollectible')
                    and e.move_line_id and not e.move_line_id.reconciled
                )
                vals['effect_ids'] = [(6, 0, effects.ids)]
        return vals

    def action_saldar(self):
        self.ensure_one()
        effects = self.effect_ids.filtered(lambda e: e.move_line_id and not e.move_line_id.reconciled)
        if not effects:
            raise UserError(_('Selecciona al menos un efecto con vencimiento pendiente.'))
        return self.remittance_id._payment_register_action(effects, _('Saldar parcialmente'))


class AccountEffectRemittanceReturnWizard(models.TransientModel):
    _name = 'account.effect.remittance.return.wizard'
    _description = 'Devolver efectos de remesa'

    remittance_id = fields.Many2one('account.effect.remittance', required=True, readonly=True)
    effect_ids = fields.Many2many(
        'account.effect',
        'account_effect_remittance_return_rel',
        'wizard_id', 'effect_id',
        string='Efectos a devolver',
        domain="[('remittance_id', '=', remittance_id), ('state', '=', 'paid')]",
        required=True,
    )

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        remittance_id = self.env.context.get('default_remittance_id') or self.env.context.get('remittance_id')
        if remittance_id:
            vals['remittance_id'] = remittance_id
            remittance = self.env['account.effect.remittance'].browse(remittance_id).exists()
            if remittance and 'effect_ids' in fields_list:
                vals['effect_ids'] = [(6, 0, remittance.effect_ids.filtered(lambda e: e.state == 'paid').ids)]
        return vals

    def action_devolver(self):
        self.ensure_one()
        effects = self.effect_ids.filtered(lambda e: e.state == 'paid')
        if not effects:
            raise UserError(_('Selecciona al menos un efecto saldado para devolver.'))
        actions = []
        for effect in effects:
            actions.append(effect.action_devolver())
        self.remittance_id._update_payment_state_from_effects()
        return {'type': 'ir.actions.act_window_close'}
