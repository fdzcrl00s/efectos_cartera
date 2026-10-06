from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountEffectRemittance(models.Model):
    _name = 'account.effect.remittance'
    _description = 'Remesa de efectos'
    _order = 'date desc, id desc'

    name = fields.Char(string='Número', required=True, readonly=True, copy=False, default='/')
    company_id = fields.Many2one('res.company', required=True, readonly=True, default=lambda self: self.env.company)
    company_type = fields.Selection(
        [('customer', 'Cliente'), ('supplier', 'Proveedor')],
        string='Tipo', required=True, readonly=True
    )
    currency_id = fields.Many2one('res.currency', string='Moneda', required=True, readonly=True)
    date = fields.Date(string='Fecha', required=True, default=fields.Date.context_today)
    group_ids = fields.One2many('account.effect.group', 'remittance_id', string='Agrupaciones')
    effect_ids = fields.One2many('account.effect', 'remittance_id', string='Efectos')
    effect_count = fields.Integer(compute='_compute_totals', string='Nº efectos')
    amount_total = fields.Monetary(compute='_compute_totals', string='Total', currency_field='currency_id')
    amount_paid = fields.Monetary(compute='_compute_totals', string='Saldado', currency_field='currency_id')
    amount_pending = fields.Monetary(compute='_compute_totals', string='Pendiente', currency_field='currency_id')
    state = fields.Selection(
        [('draft', 'Borrador'), ('sent', 'Enviada'), ('partial', 'Saldada parcialmente'),
         ('paid', 'Saldada'), ('cancelled', 'Cancelada')],
        string='Estado', default='draft', required=True
    )
    notes = fields.Text(string='Notas')

    @api.depends('effect_ids.amount', 'effect_ids.amount_pending', 'effect_ids.state', 'effect_ids.currency_id')
    def _compute_totals(self):
        for record in self:
            record.effect_count = len(record.effect_ids)
            record.amount_total = sum(record.effect_ids.mapped('amount'))
            record.amount_pending = sum(record.effect_ids.mapped('amount_pending'))
            record.amount_paid = record.amount_total - record.amount_pending

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('account.effect.remittance') or '/'
        return super().create(vals_list)

    def action_mark_sent(self):
        for record in self:
            if not record.effect_ids:
                raise UserError(_('La remesa no contiene efectos.'))
            record.write({'state': 'sent'})
            record.effect_ids.filtered(lambda e: e.state in ('grouped', 'remitted')).write({'state': 'remitted'})

    def _payment_register_action(self, effects, title):
        effects = effects.filtered(lambda e: e.move_line_id and not e.move_line_id.reconciled)
        if not effects:
            raise UserError(_('No hay efectos con vencimientos pendientes de pago en esta remesa.'))
        currencies = effects.mapped('currency_id')
        if len(currencies) > 1:
            raise UserError(_('No se pueden saldar efectos de distintas monedas en una misma remesa.'))
        return {
            'name': title,
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment.register',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_model': 'account.move.line',
                'active_ids': effects.mapped('move_line_id').ids,
                'remittance_id': self.id,
            },
        }

    def action_saldar_entero(self):
        self.ensure_one()
        effects = self.effect_ids.filtered(lambda e: e.state in ('remitted', 'grouped'))
        return self._payment_register_action(effects, _('Saldar remesa'))

    def action_saldar_parcial(self):
        self.ensure_one()
        effects = self.effect_ids.filtered(lambda e: e.state not in ('paid', 'returned', 'uncollectible') and e.move_line_id)
        if not effects:
            raise UserError(_('No hay efectos pendientes que se puedan saldar parcialmente.'))
        return {
            'name': _('Saldado parcial'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.effect.remittance.partial.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_remittance_id': self.id,
                'default_effect_ids': [(6, 0, effects.ids)],
            },
        }
