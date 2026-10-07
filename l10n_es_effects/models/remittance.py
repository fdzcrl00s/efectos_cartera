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
    has_active_payments = fields.Boolean(string='Tiene pagos activos', compute='_compute_has_active_payments', store=False)

    @api.depends('cartera_number')
    def _compute_name(self):
        for record in self:
            record.name = _('Remesa nº %s') % record.cartera_number

    @api.depends('payment_history_ids.payment_id.state', 'effect_ids.payment_id.state')
    def _compute_has_active_payments(self):
        for record in self:
            payments = record.payment_history_ids.mapped('payment_id') | record.effect_ids.mapped('payment_id')
            record.has_active_payments = any(p.state not in ('draft', 'canceled') for p in payments if p)

    @api.depends('effect_ids.amount', 'effect_ids.amount_pending', 'effect_ids.move_line_id.amount_residual', 'effect_ids.move_line_id.reconciled', 'effect_ids.state', 'effect_ids.currency_id')
    def _compute_totals(self):
        for record in self:
            effects = record.effect_ids.filtered(lambda e: not e.is_container)
            record.effect_count = len(effects)
            record.amount_total = sum(effects.mapped('amount'))
            record.amount_pending = sum(e._settlement_pending_amount() for e in effects if e.state not in ('paid', 'returned', 'uncollectible'))
            record.amount_paid = record.amount_total - record.amount_pending

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('cartera_number'):
                vals['cartera_number'] = self.env['account.effect']._next_cartera_number()
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
            'reference': False,
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
        effects = effects.filtered(lambda e: not e.is_container and e.state not in ('paid', 'returned', 'uncollectible') and e.move_line_id and not e.move_line_id.reconciled)
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
                'cartera_effect_ids': effects.ids,
                'cartera_amount_editable': False,
            },
        }

    def action_open_effect(self):
        self.ensure_one()
        effect = self._sync_container_effect()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Remesa %s') % self.cartera_number,
            'res_model': 'account.effect',
            'view_mode': 'form',
            'views': [(self.env.ref('l10n_es_effects.view_account_effect_form').id, 'form')],
            'res_id': effect.id,
            'target': 'current',
        }

    def get_formview_action(self, access_uid=None, **kwargs):
        self.ensure_one()
        effect = self._sync_container_effect()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Remesa %s') % self.cartera_number,
            'res_model': 'account.effect',
            'view_mode': 'form',
            'views': [(self.env.ref('l10n_es_effects.view_account_effect_form').id, 'form')],
            'res_id': effect.id,
            'target': 'current',
        }

    def action_edit_container(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Solo se puede editar una remesa pendiente.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Remesa %s') % self.cartera_number,
            'res_model': 'account.effect.remittance',
            'view_mode': 'form',
            'views': [(self.env.ref('l10n_es_effects.view_account_effect_remittance_form').id, 'form')],
            'res_id': self.id,
            'target': 'current',
            'context': dict(self.env.context, cartera_edit_mode=True),
        }

    def action_finish_container_edit(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Remesa %s') % self.cartera_number,
            'res_model': 'account.effect.remittance',
            'view_mode': 'form',
            'views': [(self.env.ref('l10n_es_effects.view_account_effect_remittance_form').id, 'form')],
            'res_id': self.id,
            'target': 'current',
            'context': dict(self.env.context, cartera_edit_mode=False),
        }

    def action_open_accounting_entries(self):
        self.ensure_one()
        move_ids = set(self.payment_history_ids.mapped('move_id').ids)
        move_ids.update(self.effect_ids.mapped('payment_move_id').ids)
        move_ids.update(self.effect_ids.mapped('adjustment_move_id').ids)
        if not move_ids:
            raise UserError(_('No hay asientos contables asociados a esta remesa.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Asientos contables'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', list(move_ids))],
            'context': {'create': False},
        }

    def action_devolver_efectos(self):
        self.ensure_one()
        effects = self.effect_ids.filtered(lambda e: e.state == 'paid')
        if not effects:
            raise UserError(_('No hay efectos saldados para devolver.'))
        return {
            'name': _('Devolver efectos'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.effect.remittance.return.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_remittance_id': self.id,
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
                ('remittance_id', '=', False),
                ('is_portfolio_effect', '=', False),
                '|',
                '&', ('is_container', '=', False), ('state', '=', 'pending'),
                '&', ('is_container', '=', True), ('effect_type', '=', 'group'), ('state', '=', 'pending'),
            ],
            'context': {'remittance_id': self.id, 'create': False},
        }



    def _has_active_payments(self):
        self.ensure_one()
        payments = self.payment_history_ids.mapped('payment_id') | self.effect_ids.mapped('payment_id')
        return any(p.state not in ('draft', 'canceled') for p in payments if p)

    def action_anular_saldado(self):
        self.ensure_one()
        history_model = self.env['account.effect.container.payment.history']
        histories = self.payment_history_ids.filtered(lambda h: h.type == 'paid' and h.payment_id)
        payments = histories.mapped('payment_id') | self.effect_ids.mapped('payment_id')
        payments = payments.exists().sorted(key=lambda p: (p.date or fields.Date.min, p.id))
        if not payments:
            raise UserError(_('No se han encontrado pagos de la remesa.'))
        all_related = self.env['account.effect']
        for payment in payments:
            related = histories.filtered(lambda h: h.payment_id == payment).mapped('effect_ids')
            related |= self.effect_ids.filtered(lambda e: e.payment_id == payment and not e.is_container)
            all_related |= related
            if payment.state not in ('draft', 'canceled'):
                payment.action_cancel()
            if not history_model.search([('payment_id', '=', payment.id), ('remittance_id', '=', self.id), ('type', '=', 'cancelled')], limit=1):
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
        related = all_related.filtered(lambda e: not e.is_container and e.state != 'returned')
        related.write({'state': 'remitted', 'paid_date': False, 'payment_id': False})
        for effect in related:
            if effect.move_line_id:
                effect.move_line_id.invalidate_recordset(['amount_residual', 'amount_residual_currency', 'reconciled'])
            effect._compute_amount_pending()
            effect._compute_payment_state()
            effect._log_situation('pending', _('Saldados anulados'))
        self._update_payment_state_from_effects()
        return True

    def action_update_changes(self):
        for remittance in self:
            remittance._compute_totals()
            remittance._update_payment_state_from_effects()
        return True

    def action_ungroup_selected(self):
        for remittance in self:
            if remittance._has_active_payments():
                raise UserError(_('No se pueden quitar efectos de una remesa que tiene pagos activos. Anula primero los pagos asociados a la remesa.'))
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
        effects = self.effect_ids.filtered(
            lambda e: not e.is_container and e.state not in ('paid', 'returned', 'uncollectible')
            and e.move_line_id and not e.move_line_id.reconciled
        )
        if not effects:
            raise UserError(_('No hay efectos pendientes que se puedan saldar en esta remesa.'))
        return self._payment_register_action(effects, _('Saldar remesa'))

    def action_saldar_parcial(self):
        self.ensure_one()
        effects = self.effect_ids.filtered(
            lambda e: not e.is_container and e.state not in ('paid', 'returned', 'uncollectible')
            and e.move_line_id
        )
        if not effects:
            raise UserError(_('No hay efectos asociados disponibles para saldar parcialmente.'))
        return {
            'name': _('Saldado parcial'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.effect.remittance.partial.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_remittance_id': self.id,
                'remittance_effect_ids': effects.ids,
                'cartera_effect_ids': effects.ids,
                'cartera_amount_editable': False,
            },
        }
