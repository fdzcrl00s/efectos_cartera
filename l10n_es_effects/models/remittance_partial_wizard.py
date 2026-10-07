from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountEffectRemittancePartialLine(models.TransientModel):
    _name = 'account.effect.remittance.partial.line'
    _description = 'Línea de saldado parcial de remesa'
    _order = 'due_date, id'

    wizard_id = fields.Many2one('account.effect.remittance.partial.wizard', required=True, ondelete='cascade')
    effect_id = fields.Many2one('account.effect', string='Efecto', readonly=True, ondelete='set null')
    selected = fields.Boolean(string='Saldar', default=False)
    name = fields.Char(related='effect_id.name', string='Nº Efecto', readonly=True)
    reference = fields.Char(related='effect_id.reference', string='Concepto', readonly=True)
    due_date = fields.Date(related='effect_id.due_date', string='Vencimiento', readonly=True)
    partner_id = fields.Many2one(related='effect_id.partner_id', string='Empresa', readonly=True)
    amount = fields.Monetary(related='effect_id.amount', string='Total', readonly=True, currency_field='currency_id')
    amount_pending = fields.Monetary(related='effect_id.amount_pending', string='Total pendiente', readonly=True, currency_field='currency_id')
    currency_id = fields.Many2one(related='effect_id.currency_id', readonly=True)
    payment_state = fields.Selection(related='effect_id.payment_state', string='Estado del pago', readonly=True)


class AccountEffectRemittancePartialWizard(models.TransientModel):
    _name = 'account.effect.remittance.partial.wizard'
    _description = 'Saldado parcial de remesa'

    remittance_id = fields.Many2one('account.effect.remittance', readonly=True)
    group_id = fields.Many2one('account.effect.group', readonly=True)
    line_ids = fields.One2many('account.effect.remittance.partial.line', 'wizard_id', string='Efectos')
    selected_total = fields.Monetary(string='Total seleccionado', compute='_compute_selected_total', currency_field='currency_id', readonly=True)
    currency_id = fields.Many2one(related='remittance_id.currency_id', readonly=True)

    @api.depends('line_ids.selected', 'line_ids.amount_pending')
    def _compute_selected_total(self):
        for wizard in self:
            wizard.selected_total = sum(wizard.line_ids.filtered('selected').mapped('amount_pending'))

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        remittance_id = self.env.context.get('default_remittance_id') or self.env.context.get('remittance_id')
        group_id = self.env.context.get('default_group_id') or self.env.context.get('group_id')
        effects = self.env['account.effect']
        if remittance_id:
            remittance = self.env['account.effect.remittance'].browse(remittance_id).exists()
            if remittance:
                vals['remittance_id'] = remittance.id
                effects = remittance.effect_ids.filtered(
                    lambda e: not e.is_container
                    and e.state not in ('paid', 'returned', 'uncollectible')
                    and e.move_line_id and not e.move_line_id.reconciled
                )
        elif group_id:
            group = self.env['account.effect.group'].browse(group_id).exists()
            if group:
                vals['group_id'] = group.id
                effects = group.effect_ids.filtered(
                    lambda e: not e.is_container
                    and e.state in ('grouped', 'pending')
                    and e.move_line_id and not e.move_line_id.reconciled
                )
        if 'line_ids' in fields_list:
            vals['line_ids'] = [(0, 0, {'effect_id': effect.id, 'selected': False}) for effect in effects]
        return vals

    def action_saldar(self):
        self.ensure_one()
        selected = self.line_ids.filtered('selected').mapped('effect_id').filtered(
            lambda e: e.move_line_id and not e.move_line_id.reconciled
        )
        if not selected:
            raise UserError(_('Selecciona al menos un efecto con vencimiento pendiente.'))
        if self.remittance_id:
            return self.remittance_id._payment_register_action(selected, _('Saldar parcialmente'))
        if self.group_id:
            return self.group_id._payment_register_action(selected, _('Saldar parcialmente'))
        raise UserError(_('No se ha encontrado la remesa o agrupación de destino.'))


class AccountEffectRemittanceReturnLine(models.TransientModel):
    _name = 'account.effect.remittance.return.line'
    _description = 'Línea de devolución de remesa'
    _order = 'paid_date, id'

    wizard_id = fields.Many2one('account.effect.remittance.return.wizard', required=True, ondelete='cascade')
    effect_id = fields.Many2one('account.effect', string='Efecto', readonly=True, ondelete='set null')
    selected = fields.Boolean(string='Devolver', default=False)
    name = fields.Char(related='effect_id.name', string='Nº Efecto', readonly=True)
    display_label = fields.Char(related='effect_id.display_label', string='Nombre', readonly=True)
    partner_id = fields.Many2one(related='effect_id.partner_id', string='Empresa', readonly=True)
    amount = fields.Monetary(related='effect_id.amount', string='Total', readonly=True, currency_field='currency_id')
    paid_date = fields.Date(related='effect_id.paid_date', string='Fecha de saldado', readonly=True)
    currency_id = fields.Many2one(related='effect_id.currency_id', readonly=True)


class AccountEffectRemittanceReturnWizard(models.TransientModel):
    _name = 'account.effect.remittance.return.wizard'
    _description = 'Devolver efectos de remesa'

    remittance_id = fields.Many2one('account.effect.remittance', required=True, readonly=True)
    line_ids = fields.One2many('account.effect.remittance.return.line', 'wizard_id', string='Efectos')

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        remittance_id = self.env.context.get('default_remittance_id') or self.env.context.get('remittance_id')
        if remittance_id:
            remittance = self.env['account.effect.remittance'].browse(remittance_id).exists()
            if remittance:
                vals['remittance_id'] = remittance.id
                effects = remittance.effect_ids.filtered(lambda e: e.state == 'paid')
                if 'line_ids' in fields_list:
                    vals['line_ids'] = [
                        (0, 0, {'effect_id': effect.id, 'selected': False})
                        for effect in effects
                    ]
        return vals

    def action_devolver(self):
        self.ensure_one()
        effects = self.line_ids.filtered('selected').mapped('effect_id').filtered(lambda e: e.state == 'paid')
        if not effects:
            raise UserError(_('Selecciona al menos un efecto saldado para devolver.'))
        for effect in effects:
            effect.action_devolver()
        self.remittance_id._update_payment_state_from_effects()
        return {'type': 'ir.actions.act_window_close'}
