from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountEffectGroup(models.Model):
    _name = 'account.effect.group'
    _description = 'Agrupación de efectos'
    _order = 'date desc, id desc'

    name = fields.Char(string='Nombre', compute='_compute_name', store=True)
    cartera_number = fields.Char(string='Nº Cartera', required=True, readonly=True, copy=False)
    company_id = fields.Many2one('res.company', required=True, readonly=True, default=lambda self: self.env.company)
    partner_id = fields.Many2one('res.partner', string='Cliente/Proveedor', readonly=True)
    company_type = fields.Selection(
        [('customer', 'Cliente'), ('supplier', 'Proveedor')],
        string='Tipo', required=True, readonly=True
    )
    currency_id = fields.Many2one('res.currency', string='Moneda', required=True, readonly=True)
    date = fields.Date(string='Fecha', required=True, default=fields.Date.context_today)
    effect_ids = fields.One2many('account.effect', 'group_id', string='Efectos')
    effect_count = fields.Integer(compute='_compute_totals', string='Nº efectos')
    amount_total = fields.Monetary(compute='_compute_totals', string='Importe total', currency_field='currency_id')
    state = fields.Selection(
        [('draft', 'Borrador'), ('remitted', 'Remesado'), ('cancelled', 'Cancelado')],
        string='Estado', default='draft', required=True
    )
    remittance_id = fields.Many2one('account.effect.remittance', string='Remesa', readonly=True, ondelete='set null')
    bank_journal_id = fields.Many2one('account.journal', string='Banco', domain="[('type', '=', 'bank')]")
    partner_bank_id = fields.Many2one('res.partner.bank', string='Cuenta bancaria')
    payment_direction = fields.Selection([('receive', 'Recibir dinero'), ('send', 'Enviar dinero')],
                                         string='Tipo de pago')
    due_date = fields.Date(string='Vencimiento')
    reference = fields.Char(string='Circular / Concepto')
    notes = fields.Text(string='Notas')

    @api.depends('cartera_number')
    def _compute_name(self):
        for record in self:
            record.name = _('Agrupación %s') % record.cartera_number

    @api.depends('effect_ids.amount', 'effect_ids.currency_id')
    def _compute_totals(self):
        for record in self:
            record.effect_count = len(record.effect_ids)
            record.amount_total = sum(record.effect_ids.mapped('amount'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('cartera_number'):
                vals['cartera_number'] = self.env['ir.sequence'].next_by_code('account.effect.group') or '/'
        return super().create(vals_list)

    def action_add_pending_effects(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Añadir efectos'),
            'res_model': 'account.effect.add.lines.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_group_id': self.id,
                'default_container_type': 'group',
            },
        }

    def action_create_remittance(self):
        self.ensure_one()
        effects = self.effect_ids.filtered(lambda e: e.state == 'grouped')
        if not effects:
            raise UserError(_('La agrupación no contiene efectos pendientes de remesar.'))

        currencies = effects.mapped('currency_id')
        if len(currencies) > 1:
            raise UserError(_('No se pueden remesar efectos de distintas monedas.'))

        remittance = self.env['account.effect.remittance'].create({
            'company_id': self.company_id.id,
            'company_type': self.company_type,
            'currency_id': self.currency_id.id,
        })
        self.write({'remittance_id': remittance.id, 'state': 'remitted'})
        effects.write({'remittance_id': remittance.id, 'state': 'remitted'})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Remesa'),
            'res_model': 'account.effect.remittance',
            'view_mode': 'form',
            'res_id': remittance.id,
        }

    def action_ungroup_selected(self):
        for group in self:
            effects = group.effect_ids.filtered(lambda e: e.state != 'paid')
            effects.write({'group_id': False, 'cartera_number': False, 'state': 'pending'})
            group._compute_totals()
        return True

    def action_update_changes(self):
        for group in self:
            group._compute_totals()
        return True
