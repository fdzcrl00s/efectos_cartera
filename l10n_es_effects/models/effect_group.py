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
    portfolio_effect_ids = fields.One2many('account.effect', 'container_group_id', string='Efectos de la misma Cartera', )
    payment_history_ids = fields.One2many('account.effect.container.payment.history', 'group_id', string='Histórico Pagos', readonly=True)

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
                vals['cartera_number'] = self.env['account.effect']._next_cartera_number()
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
            'reference': False,
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
        if effects and all(e.state == 'paid' for e in effects):
            self.write({'state': 'paid', 'paid_date': payment_date or fields.Date.context_today(self)})
            self._log_container_situation(_('Agrupación saldada'))
        elif effects:
            self.write({'state': 'draft', 'paid_date': False})
        self._compute_totals()
        self._sync_container_effect()
        return True

    def _log_container_situation(self, note):
        if self.container_effect_id:
            self.container_effect_id._log_situation('paid' if self.state == 'paid' else 'pending', note)

    def action_open_effect(self):
        self.ensure_one()
        effect = self._sync_container_effect()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Agrupación %s') % self.cartera_number,
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
            'name': _('Agrupación %s') % self.cartera_number,
            'res_model': 'account.effect',
            'view_mode': 'form',
            'views': [(self.env.ref('l10n_es_effects.view_account_effect_form').id, 'form')],
            'res_id': effect.id,
            'target': 'current',
        }

    def action_edit_container(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Solo se puede editar una agrupación pendiente.'))
        effect = self._sync_container_effect()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Agrupación %s') % self.cartera_number,
            'res_model': 'account.effect',
            'view_mode': 'form',
            'views': [(self.env.ref('l10n_es_effects.view_account_effect_form').id, 'form')],
            'res_id': effect.id,
            'target': 'current',
            'context': dict(self.env.context, cartera_edit_mode=True),
        }

    def action_add_pending_effects(self):
        self.ensure_one()
        list_view = self.env.ref('l10n_es_effects.view_account_effect_list')
        return {
            'type': 'ir.actions.act_window',
            'name': _('Añadir efectos'),
            'res_model': 'account.effect',
            'view_mode': 'list,form',
            'views': [(list_view.id, 'list'), (False, 'form')],
            'target': 'new',
            'domain': [
                ('company_id', '=', self.company_id.id),
                ('group_id', '=', False),
                ('remittance_id', '=', False),
                ('is_container', '=', False),
                ('is_portfolio_effect', '=', False),
                ('state', '=', 'pending'),
            ],
            'context': {'group_id': self.id, 'create': False},
        }


    def _payment_register_action(self, effects, title):
        self.ensure_one()
        effects = effects.filtered(lambda e: not e.is_container and e.state in ('grouped', 'pending') and e.move_line_id and not e.move_line_id.reconciled)
        if not effects:
            raise UserError(_('No hay efectos con vencimientos pendientes de pago en esta agrupación.'))
        if len(effects.mapped('currency_id')) > 1:
            raise UserError(_('No se pueden saldar efectos de distintas monedas en una misma agrupación.'))
        return {
            'name': title,
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment.register',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_model': 'account.move.line',
                'active_ids': effects.mapped('move_line_id').ids,
                'group_id': self.id,
                'cartera_effect_ids': effects.ids,
            },
        }

    def action_saldar(self):
        self.ensure_one()
        effects = self.effect_ids.filtered(lambda e: e.state in ('grouped', 'pending') and e.move_line_id and not e.move_line_id.reconciled)
        return self._payment_register_action(effects, _('Saldar agrupación'))

    def action_saldar_parcial(self):
        self.ensure_one()
        effects = self.effect_ids.filtered(lambda e: e.state in ('grouped', 'pending') and e.move_line_id and not e.move_line_id.reconciled)
        if not effects:
            raise UserError(_('No hay efectos pendientes que se puedan saldar parcialmente.'))
        return {
            'name': _('Saldado parcial'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.effect.remittance.partial.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_group_id': self.id},
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

    def _has_active_payments(self):
        self.ensure_one()
        payments = self.payment_history_ids.mapped('payment_id') | self.effect_ids.mapped('payment_id')
        return any(p.state not in ('draft', 'canceled') for p in payments if p)

    def action_ungroup_selected(self):
        for group in self:
            if group._has_active_payments():
                raise UserError(_('No se pueden quitar efectos de una agrupación que tiene pagos activos. Anula primero los pagos asociados a la agrupación.'))
            effects = group.effect_ids.filtered(lambda e: not e.is_container and e.state != 'paid')
            effects.write({'group_id': False, 'remittance_id': False, 'cartera_number': False, 'state': 'pending', 'paid_date': False, 'payment_id': False})
            effects._compute_amount_pending()
            effects._compute_payment_state()
            # Partial portfolio effects are only a historical representation of
            # the previous partial settlement; once all payments are annulled
            # they must not remain as selectable effects.
            helpers = group.portfolio_effect_ids.filtered(lambda e: e.is_portfolio_effect)
            helpers.write({'active': False})
            group._compute_totals()
            group._sync_container_effect()
        return True


    def action_open_accounting_entries(self):
        self.ensure_one()
        move_ids = set(self.payment_history_ids.mapped('move_id').ids)
        move_ids.update(self.effect_ids.mapped('payment_move_id').ids)
        move_ids.update(self.effect_ids.mapped('adjustment_move_id').ids)
        if not move_ids:
            raise UserError(_('No hay asientos contables asociados a esta agrupación.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Asientos contables'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', list(move_ids))],
            'context': {'create': False},
        }

    def action_anular_saldado(self):
        self.ensure_one()
        history_model = self.env['account.effect.container.payment.history']
        histories = self.payment_history_ids.filtered(lambda h: h.type == 'paid' and h.payment_id)
        payments = histories.mapped('payment_id') | self.effect_ids.mapped('payment_id')
        payments = payments.exists().sorted(key=lambda p: (p.date or fields.Date.min, p.id))
        if not payments:
            raise UserError(_('No se han encontrado pagos de la agrupación.'))
        all_related = self.env['account.effect']
        for payment in payments:
            related = histories.filtered(lambda h: h.payment_id == payment).mapped('effect_ids')
            related |= self.effect_ids.filtered(lambda e: e.payment_id == payment and not e.is_container)
            all_related |= related
            if payment.state not in ('draft', 'canceled'):
                payment.action_cancel()
                payment.action_draft()
            if not history_model.search([('payment_id', '=', payment.id), ('group_id', '=', self.id), ('type', '=', 'cancelled')], limit=1):
                history_model.create({
                    'group_id': self.id,
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
        related.write({'state': 'grouped', 'paid_date': False, 'payment_id': False})
        for effect in related:
            if effect.move_line_id:
                effect.move_line_id.invalidate_recordset(['amount_residual', 'amount_residual_currency', 'reconciled'])
            effect._compute_amount_pending()
            effect._compute_payment_state()
            effect._log_situation('pending', _('Saldados anulados'))
        helpers = self.portfolio_effect_ids.filtered(lambda e: e.is_portfolio_effect)
        helpers.write({'active': False})
        self._update_payment_state_from_effects()
        return True

    def action_update_changes(self):
        for group in self:
            group._compute_totals()
            group._sync_container_effect()
        return True
