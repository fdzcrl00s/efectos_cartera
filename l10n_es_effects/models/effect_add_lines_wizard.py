from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountEffectAddLinesWizard(models.TransientModel):
    _name = 'account.effect.add.lines.wizard'
    _description = 'Añadir efectos a agrupación o remesa'

    container_type = fields.Selection([
        ('group', 'Agrupación'),
        ('remittance', 'Remesa'),
    ], required=True, readonly=True)
    group_id = fields.Many2one('account.effect.group', readonly=True)
    remittance_id = fields.Many2one('account.effect.remittance', readonly=True)
    effect_ids = fields.Many2many(
        'account.effect',
        string='Efectos pendientes',
        domain="[('state', 'in', ('pending', 'grouped')), ('company_id', '=', company_id)]",
    )
    company_id = fields.Many2one('res.company', compute='_compute_company', store=False)

    @api.depends('group_id', 'remittance_id')
    def _compute_company(self):
        for wizard in self:
            wizard.company_id = (
                wizard.group_id.company_id
                or wizard.remittance_id.company_id
                or self.env.company
            )

    def action_add(self):
        self.ensure_one()
        effects = self.effect_ids
        if not effects:
            raise UserError(_('Selecciona al menos un efecto.'))

        if self.container_type == 'group':
            container = self.group_id
            if not container:
                raise UserError(_('No se ha encontrado la agrupación.'))
            if any(e.state not in ('pending', 'grouped') for e in effects):
                raise UserError(_('Solo se pueden añadir efectos pendientes o ya agrupados.'))
            if any(e.company_id != container.company_id for e in effects):
                raise UserError(_('No se pueden mezclar compañías.'))
            if any(e.currency_id != container.currency_id for e in effects):
                raise UserError(_('No se pueden mezclar monedas.'))
            effects.write({
                'group_id': container.id,
                'remittance_id': False,
                'cartera_number': container.cartera_number,
                'state': 'grouped',
            })
            container._compute_amount()
            return {'type': 'ir.actions.act_window_close'}

        container = self.remittance_id
        if not container:
            raise UserError(_('No se ha encontrado la remesa.'))
        if any(e.company_id != container.company_id for e in effects):
            raise UserError(_('No se pueden mezclar compañías.'))
        if any(e.currency_id != container.currency_id for e in effects):
            raise UserError(_('No se pueden mezclar monedas.'))
        effects.write({
            'remittance_id': container.id,
            'cartera_number': container.cartera_number,
            'state': 'remitted',
        })
        effects.mapped('group_id').write({'remittance_id': container.id})
        container._compute_amount()
        return {'type': 'ir.actions.act_window_close'}
