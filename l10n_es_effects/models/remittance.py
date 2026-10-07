from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountEffectRemittance(models.Model):
    _name = 'account.effect.remittance'
    _description = 'Remesa de efectos'
    _order = 'date desc, id desc'

    name = fields.Char(string='Nombre', compute='_compute_name', store=True)
    cartera_number = fields.Char(string='Nº Cartera', required=True, readonly=True, copy=False)
    company_id = fields.Many2one('res.company', required=True, readonly=True, default=lambda self: self.env.company)
    company_type = fields.Selection(
        [('customer', 'Cliente'), ('supplier', 'Proveedor')],
        string='Tipo', default='customer'
    )
    currency_id = fields.Many2one('res.currency', string='Moneda', readonly=True, default=lambda self: self.env.company.currency_id)
    date = fields.Date(string='Fecha', required=True, default=fields.Date.context_today)
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
            record.name = _('Remesa %s') % record.cartera_number

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
            if not vals.get('cartera_number'):
                vals['cartera_number'] = self.env['ir.sequence'].next_by_code('account.effect.remittance') or '/'
        return super().create(vals_list)

    def action_mark_sent(self):
        for record in self:
            if not record.effect_ids:
                raise UserError(_('La remesa no contiene efectos.'))
            record.write({'state': 'sent'})
            effects = record.effect_ids.filtered(lambda e: e.state in ('grouped', 'remitted'))
            effects._set_state('remitted', _('Remesa %s enviada') % record.name)

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

    def action_add_pending_effects(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Añadir efectos'),
            'res_model': 'account.effect.add.lines.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_remittance_id': self.id,
                'default_container_type': 'remittance',
            },
        }


    def action_update_changes(self):
        for remittance in self:
            remittance._compute_totals()
            remittance.effect_ids.filtered(lambda e: e.state != 'paid').write({'state': 'remitted'})
        return True

    def action_ungroup_selected(self):
        for remittance in self:
            effects = remittance.effect_ids.filtered(lambda e: e.state != 'paid')
            grouped = effects.filtered(lambda e: e.group_id)
            standalone = effects - grouped
            if grouped:
                for effect in grouped:
                    effect.write({'remittance_id': False, 'cartera_number': effect.group_id.cartera_number, 'state': 'grouped'})

            standalone.write({'remittance_id': False, 'cartera_number': False, 'state': 'pending'})
            remittance._compute_totals()
        return True


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
