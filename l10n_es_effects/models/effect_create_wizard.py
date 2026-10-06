from odoo import fields, models, _


class AccountEffectCreateWizard(models.TransientModel):
    _name = 'account.effect.create.wizard'
    _description = 'Crear elemento de cartera'

    effect_type = fields.Selection([
        ('effect', 'Efecto'),
        ('group', 'Agrupación'),
        ('remittance', 'Remesa'),
    ], string='Tipo de efecto', required=True, default='effect')

    def action_create(self):
        self.ensure_one()
        if self.effect_type == 'effect':
            return {
                'type': 'ir.actions.act_window',
                'name': _('Crear efecto'),
                'res_model': 'account.effect',
                'view_mode': 'form',
                'target': 'current',
                'context': {'default_effect_type': 'effect'},
            }
        if self.effect_type == 'group':
            return {
                'type': 'ir.actions.act_window',
                'name': _('Crear agrupación'),
                'res_model': 'account.effect.group',
                'view_mode': 'form',
                'target': 'current',
                'context': {'default_company_id': self.env.company.id},
            }
        return {
            'type': 'ir.actions.act_window',
            'name': _('Crear remesa'),
            'res_model': 'account.effect.remittance',
            'view_mode': 'form',
            'target': 'current',
            'context': {'default_company_id': self.env.company.id},
        }
