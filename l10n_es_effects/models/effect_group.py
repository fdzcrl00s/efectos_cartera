from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountEffectGroup(models.Model):
    _name = 'account.effect.group'
    _description = 'Agrupación de efectos'
    _order = 'date desc, id desc'

    name = fields.Char(string='Nombre', compute='_compute_name', store=True)
    cartera_number = fields.Char(string='Nº Cartera', required=True, readonly=True, copy=False)
    company_id = fields.Many2one('res.company', required=True, readonly=True, default=lambda self: self.env.company)
    partner_id = fields.Many2one('res.partner', string='Cliente/Proveedor')
    company_type = fields.Selection(
        [('customer', 'Cliente'), ('supplier', 'Proveedor')],
        string='Tipo', required=True, default='customer'
    )
    currency_id = fields.Many2one('res.currency', string='Moneda', required=True, readonly=True)
    date = fields.Date(string='Fecha', required=True, default=fields.Date.context_today)
    effect_ids = fields.One2many('account.effect', 'group_id', string='Efectos')
    effect_count = fields.Integer(compute='_compute_totals', string='Nº efectos')
    amount_total = fields.Monetary(compute='_compute_totals', string='Importe total', currency_field='currency_id')
    amount_pending = fields.Monetary(compute='_compute_totals', string='Pendiente', currency_field='currency_id')
    state = fields.Selection(
        [('draft', 'Pendiente'), ('remitted', 'Remesado'), ('paid', 'Saldado'), ('cancelled', 'Cancelado')],
        string='Estado', default='draft', required=True
    )
    remittance_id = fields.Many2one('account.effect.remittance', string='Remesa', readonly=True, ondelete='set null')
    bank_journal_id = fields.Many2one('account.journal', string='Banco', domain="[('type', '=', 'bank')]")
    partner_bank_id = fields.Many2one('res.partner.bank', string='Cuenta bancaria')
    payment_direction = fields.Selection([('receive', 'Recibir dinero'), ('send', 'Enviar dinero')],
                                         string='Tipo de pago', compute='_compute_payment_direction', store=True)
    due_date = fields.Date(string='Vencimiento')
    reference = fields.Char(string='Circular / Concepto')
    notes = fields.Text(string='Notas')
    paid_date = fields.Date(string='Fecha de saldado', readonly=True, copy=False)
    container_effect_id = fields.Many2one('account.effect', string='Efecto de cartera', readonly=True, copy=False, ondelete='set null')

    @api.depends('company_type')
    def _compute_payment_direction(self):
        for record in self:
            record.payment_direction = 'receive' if record.company_type == 'customer' else 'send'

    @api.depends('cartera_number')
    def _compute_name(self):
        for record in self:
            record.name = _('Agrupación nº %s') % record.cartera_number

    @api.depends('effect_ids.amount', 'effect_ids.amount_pending', 'effect_ids.currency_id')
    def _compute_totals(self):
        for record in self:
            effects = record.effect_ids.filtered(lambda e: not e.is_container)
            record.effect_count = len(effects)
            record.amount_total = sum(effects.mapped('amount'))
            record.amount_pending = sum(effects.mapped('amount_pending'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('cartera_number'):
                vals['cartera_number'] = self.env['ir.sequence'].next_by_code('account.effect.group') or '/'
        records = super().create(vals_list)
        for record in records:
            record._sync_container_effect()
        return records

    def _sync_container_effect(self):
        self.ensure_one()
        effect = self.container_effect_id
        if not effect:
            effect = self.env['account.effect'].search([
                ('effect_type', '=', 'group'),
                ('group_id', '=', self.id),
            ], limit=1)
            if effect:
                self.container_effect_id = effect.id
        vals = {
            'company_id': self.company_id.id,
            'company_type': self.company_type,
            'partner_id': self.partner_id.id if self.partner_id else False,
            'due_date': self.due_date or self.date or fields.Date.context_today(self),
            'reference': self.reference or False,
            'amount': self.amount_total,
            'currency_id': self.currency_id.id,
            'payment_direction': self.payment_direction,
            'effect_type': 'group',
            'is_container': True,
            'container_group_id': self.id,
            'state': 'paid' if self.state == 'paid' else ('remitted' if self.remittance_id else ('pending' if self.state != 'cancelled' else 'returned')),
            'paid_date': self.paid_date,
            'cartera_number': self.cartera_number,
            'active': True,
        }
        if effect:
            effect.write(dict(vals, group_id=False, remittance_id=False))
        else:
            effect = self.env['account.effect'].create(vals)
            self.container_effect_id = effect.id
        return effect

    def _update_payment_state_from_effects(self, payment_date=False):
        self.ensure_one()
        effects = self.effect_ids.filtered(lambda e: not e.is_container)
        if effects and all(e.state == 'paid' for e in effects):
            self.write({'state': 'paid', 'paid_date': payment_date or fields.Date.context_today(self)})
            self._log_container_situation(_('Agrupación saldada'))
        self._compute_totals()
        self._sync_container_effect()
        return True

    def _log_container_situation(self, note):
        if self.container_effect_id:
            self.container_effect_id._log_situation('paid' if self.state == 'paid' else 'pending', note)

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

    def action_saldar(self):
        self.ensure_one()
        effects = self.effect_ids.filtered(lambda e: e.state == 'grouped' and e.move_line_id and not e.move_line_id.reconciled)
        if not effects:
            raise UserError(_('La agrupación no contiene efectos con vencimientos pendientes de pago.'))
        currencies = effects.mapped('currency_id')
        if len(currencies) > 1:
            raise UserError(_('No se pueden saldar efectos de distintas monedas en una misma agrupación.'))
        return {
            'name': _('Saldar agrupación'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment.register',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_model': 'account.move.line',
                'active_ids': effects.mapped('move_line_id').ids,
                'group_id': self.id,
            },
        }

    def action_create_remittance(self):
        self.ensure_one()
        effects = self.effect_ids.filtered(lambda e: e.state in ('grouped', 'pending') and not e.remittance_id)
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
        self._sync_container_effect()
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
            group._sync_container_effect()
        return True

    def action_update_changes(self):
        for group in self:
            group._compute_totals()
            group._sync_container_effect()
        return True
