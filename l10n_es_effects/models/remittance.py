from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountEffectRemittance(models.Model):
    _name = 'account.effect.remittance'
    _description = 'Remesa de efectos'
    _order = 'date desc, id desc'

    name = fields.Char(string='Nombre', compute='_compute_name', store=True)
    cartera_number = fields.Char(string='Nº Cartera', required=True, readonly=True, copy=False)
    company_id = fields.Many2one('res.company', required=True, readonly=True, default=lambda self: self.env.company)
    partner_id = fields.Many2one('res.partner', string='Cliente', related='company_id.partner_id', store=True, readonly=True)
    company_type = fields.Selection(
        [('customer', 'Cliente'), ('supplier', 'Proveedor')],
        string='Tipo'
    )
    currency_id = fields.Many2one('res.currency', string='Moneda', readonly=True, default=lambda self: self.env.company.currency_id)
    date = fields.Date(string='Fecha', required=True, default=fields.Date.context_today)
    effect_ids = fields.One2many('account.effect', 'remittance_id', string='Efectos')
    effect_count = fields.Integer(compute='_compute_totals', string='Nº efectos')
    amount_total = fields.Monetary(compute='_compute_totals', string='Total', currency_field='currency_id')
    amount_paid = fields.Monetary(compute='_compute_totals', string='Saldado', currency_field='currency_id')
    amount_pending = fields.Monetary(compute='_compute_totals', string='Pendiente', currency_field='currency_id')
    state = fields.Selection(
        [('draft', 'Pendiente'), ('partial', 'Saldada parcialmente'),
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
    paid_date = fields.Date(string='Fecha de saldado', readonly=True, copy=False)
    container_effect_id = fields.Many2one('account.effect', string='Efecto de cartera', readonly=True, copy=False, ondelete='set null')
    portfolio_effect_ids = fields.One2many('account.effect', 'container_remittance_id', string='Efectos de la misma Cartera', )
    payment_history_ids = fields.One2many('account.effect.container.payment.history', 'remittance_id', string='Histórico Pagos', readonly=True)

    @api.depends('cartera_number')
    def _compute_name(self):
        for record in self:
            record.name = _('Remesa nº %s') % record.cartera_number

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
        records = super().create(vals_list)
        for record in records:
            record._sync_container_effect()
        return records

    def _sync_container_effect(self):
        self.ensure_one()
        if not self.company_type and self.effect_ids:
            company_types = self.effect_ids.filtered(lambda e: not e.is_container).mapped('company_type')
            if len(company_types) == 1:
                self.company_type = company_types[0]
        effect = self.container_effect_id
        if not effect:
            effect = self.env['account.effect'].search([
                ('effect_type', '=', 'remittance'),
                ('remittance_id', '=', self.id),
            ], limit=1)
            if effect:
                self.container_effect_id = effect.id
        state = 'paid' if self.state == 'paid' else ('returned' if self.state == 'cancelled' else 'pending')
        vals = {
            'company_id': self.company_id.id,
            'company_type': self.company_type or 'customer',
            'partner_id': self.company_id.partner_id.id,
            'due_date': self.due_date or self.date or fields.Date.context_today(self),
            'reference': self.reference or False,
            'amount': self.amount_total,
            'currency_id': self.currency_id.id,
            'payment_direction': self.payment_direction or ('receive' if self.company_type == 'customer' else 'send'),
            'effect_type': 'remittance',
            'is_container': True,
            'container_remittance_id': self.id,
            'state': state,
            'paid_date': self.paid_date,
            'cartera_number': self.cartera_number,
            'active': True,
            'is_portfolio_effect': False,
            'payment_id': self.effect_ids.filtered(lambda e: e.payment_id).sorted(
                key=lambda e: (e.paid_date or fields.Date.min, e.id), reverse=True
            )[:1].payment_id.id if self.effect_ids.filtered(lambda e: e.payment_id) else False,
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
        payment_date = payment_date or fields.Date.context_today(self)
        if not effects:
            self.write({'state': 'draft', 'paid_date': False})
        elif all(e.state == 'paid' for e in effects):
            self.write({'state': 'paid', 'paid_date': payment_date})
        elif any(e.state == 'paid' for e in effects) or any(e.amount_pending < e.amount for e in effects):
            self.write({'state': 'partial', 'paid_date': payment_date})
        else:
            self.write({'state': 'draft', 'paid_date': False})
        groups = effects.mapped('group_id')
        for group in groups:
            group._update_payment_state_from_effects(payment_date)
        self._compute_totals()
        self._sync_container_effect()
        return True

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
        list_view = self.env.ref('l10n_es_effects.view_account_effect_list')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Añadir: Agrupar Efectos'),
            'res_model': 'account.effect',
            'view_mode': 'list,form',
            'views': [(list_view.id, 'list'), (False, 'form')],
            'target': 'new',
            'domain': [
                ('company_id', '=', self.company_id.id),
                ('is_container', '=', False),
                ('is_portfolio_effect', '=', False),
                ('state', 'in', ('pending', 'grouped')),
                ('remittance_id', '=', False),
            ],
            'context': {'remittance_id': self.id, 'create': False},
        }



    def action_anular_saldado(self):
        self.ensure_one()
        paid_effects = self.effect_ids.filtered(lambda e: e.payment_id and (e.state == 'paid' or e.amount_pending < e.amount))
        payment = paid_effects.mapped('payment_id').sorted(key=lambda p: (p.date or fields.Date.min, p.id), reverse=True)[:1]
        if not payment:
            raise UserError(_('No se ha encontrado el último pago de la remesa.'))
        related = paid_effects.filtered(lambda e: e.payment_id == payment)
        payment.action_cancel()
        history_model = self.env['account.effect.container.payment.history']
        history_domain = [('payment_id', '=', payment.id), ('remittance_id', '=', self.id)]
        if not history_model.search(history_domain + [('type', '=', 'cancelled')], limit=1):
            history_model.create({
                'remittance_id': self.id,
                'payment_id': payment.id,
                'reference': payment.name or '',
                'move_id': payment.move_id.id if payment.move_id else False,
                'date': fields.Date.context_today(self),
                'effect_ids': [(6, 0, related.ids)],
                'amount': payment.amount,
                'currency_id': payment.currency_id.id,
                'type': 'cancelled',
            })
        for effect in related:
            effect.write({'state': 'remitted', 'paid_date': False, 'payment_id': False})
            effect._log_situation('remitted', _('Saldado anulado · Pago %s') % payment.display_name)
        self._update_payment_state_from_effects()
        return True

    def action_update_changes(self):
        for remittance in self:
            remittance._compute_totals()
            remittance._update_payment_state_from_effects()
        return True

    def action_ungroup_selected(self):
        for remittance in self:
            effects = remittance.effect_ids.filtered(lambda e: e.state != 'paid')
            grouped = effects.filtered(lambda e: e.group_id)
            standalone = effects - grouped
            if grouped:
                touched_groups = grouped.mapped('group_id')
                for effect in grouped:
                    effect.write({'remittance_id': False, 'cartera_number': effect.group_id.cartera_number, 'state': 'grouped'})
                for group in touched_groups:
                    if not group.effect_ids.filtered(lambda e: e.remittance_id == remittance):
                        group.write({'remittance_id': False, 'state': 'draft'})
                        group._sync_container_effect()

            standalone.write({'remittance_id': False, 'cartera_number': False, 'state': 'pending'})
            remittance._compute_totals()
            remittance._update_payment_state_from_effects()
        return True


    def action_saldar_entero(self):
        self.ensure_one()
        effects = self.effect_ids.filtered(lambda e: e.state == 'remitted' and e.move_line_id and not e.move_line_id.reconciled)
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
