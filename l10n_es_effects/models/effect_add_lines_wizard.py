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
    group_ids = fields.Many2many(
        'account.effect.group',
        string='Agrupaciones pendientes',
        domain="[('state', '=', 'draft'), ('company_id', '=', company_id)]",
    )
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
        groups = self.group_ids
        if self.container_type == 'group' and not effects:
            raise UserError(_('Selecciona al menos un efecto.'))
        if self.container_type == 'remittance' and not effects and not groups:
            raise UserError(_('Selecciona al menos un efecto o una agrupación.'))

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
            container._compute_totals()
            return {'type': 'ir.actions.act_window_close'}

        container = self.remittance_id
        if not container:
            raise UserError(_('No se ha encontrado la remesa.'))
        if any(e.company_id != container.company_id for e in effects) or any(g.company_id != container.company_id for g in groups):
            raise UserError(_('No se pueden mezclar compañías.'))
        if any(e.currency_id != container.currency_id for e in effects) or any(g.currency_id != container.currency_id for g in groups):
            raise UserError(_('No se pueden mezclar monedas.'))
        if effects:
            effects.write({
                'remittance_id': container.id,
                'cartera_number': container.cartera_number,
                'state': 'remitted',
            })
            effects.mapped('group_id').write({'remittance_id': container.id, 'state': 'remitted'})
        if groups:
            for group in groups:
                group.write({'remittance_id': container.id, 'state': 'remitted'})
                group.effect_ids.filtered(lambda e: not e.remittance_id and e.state in ('grouped', 'pending')).write({
                    'remittance_id': container.id,
                    'cartera_number': container.cartera_number,
                    'state': 'remitted',
                })
        container._compute_totals()
        return {'type': 'ir.actions.act_window_close'}
