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
        [('draft', 'Pendiente'), ('partial', 'Saldada parcialmente'), ('remitted', 'Remesado'), ('paid', 'Saldado'), ('cancelled', 'Cancelado')],
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
    grouping_move_id = fields.Many2one('account.move', string='Asiento inicial de agrupación', readonly=True, copy=False, ondelete='restrict')
    grouping_move_ids = fields.Many2many('account.move', 'account_effect_group_move_rel', 'group_id', 'move_id', string='Asientos de agrupación', readonly=True, copy=False)
    portfolio_effect_ids = fields.One2many('account.effect', 'container_group_id', string='Efectos de la misma Cartera', )
    payment_history_ids = fields.One2many('account.effect.container.payment.history', 'group_id', string='Histórico Pagos', readonly=True)
    all_payment_history_ids = fields.Many2many(
        'account.effect.container.payment.history',
        relation='account_effect_group_all_history_rel', column1='group_id', column2='history_id',
        string='Histórico completo de pagos',
        compute='_compute_all_payment_history_ids',
    )
    has_active_payments = fields.Boolean(string='Tiene pagos activos', compute='_compute_has_active_payments', store=False)

    @api.depends('company_type')
    def _compute_payment_direction(self):
        for record in self:
            record.payment_direction = 'receive' if record.company_type == 'customer' else 'send'

    @api.depends('cartera_number')
    def _compute_name(self):
        for record in self:
            record.name = _('Agrupación nº %s') % record.cartera_number

    def _compute_all_payment_history_ids(self):
        history_model = self.env['account.effect.container.payment.history']
        for group in self:
            group.all_payment_history_ids = history_model.search([
                '|', ('group_id', '=', group.id), ('group_ids', 'in', group.id),
            ])

    @api.depends(
        'payment_history_ids.payment_id.state', 'payment_history_ids.move_id.state',
        'payment_history_ids.type', 'effect_ids.payment_id.state',
    )
    def _compute_has_active_payments(self):
        for record in self:
            record.has_active_payments = record._has_active_payments()

    @api.depends(
        'effect_ids.amount', 'effect_ids.amount_pending', 'effect_ids.move_line_id.amount_residual',
        'effect_ids.move_line_id.reconciled', 'effect_ids.state', 'effect_ids.currency_id',
        'payment_history_ids.type', 'payment_history_ids.allocation_line_ids.amount',
        'payment_history_ids.allocation_line_ids.effect_id', 'grouping_move_id.state',
    )
    def _compute_totals(self):
        for record in self:
            effects = record.effect_ids.filtered(lambda e: not e.is_container)
            record.effect_count = len(effects)
            record.amount_total = sum(effects.mapped('amount'))
            if record.grouping_move_id and record.grouping_move_id.state == 'posted':
                record.amount_pending = sum(record._get_effect_pending_amount(e) for e in effects if e.state not in ('returned', 'uncollectible'))
            else:
                record.amount_pending = sum(e._settlement_pending_amount() for e in effects if e.state not in ('returned', 'uncollectible'))

    def _get_effect_paid_amount(self, effect):
        """Sum valid allocations already assigned to a grouped effect."""
        self.ensure_one()
        lines = self.env['account.effect.container.payment.line'].search([
            ('effect_id', '=', effect.id),
            ('history_id.type', '=', 'paid'),
        ])
        return sum(lines.mapped('amount'))

    def _get_effect_pending_amount(self, effect):
        self.ensure_one()
        if effect.state in ('paid', 'returned', 'uncollectible'):
            return 0.0
        if not self.grouping_move_id or self.grouping_move_id.state != 'posted':
            return effect._settlement_pending_amount()
        pending = effect.amount - self._get_effect_paid_amount(effect)
        return max(0.0, pending)

    def _get_grouping_lines(self):
        self.ensure_one()
        return self.env['account.move.line'].search([
            ('effect_group_id', '=', self.id),
            ('effect_group_effect_id', '=', False),
            ('move_id', 'in', self.grouping_move_ids.ids),
            ('move_id.state', '=', 'posted'),
        ])

    def _reconcile_original_effects(self):
        """Reconcile original invoices only once the whole grouping is paid."""
        self.ensure_one()
        effects = self.effect_ids.filtered(lambda effect: not effect.is_container and effect.state not in ('returned', 'uncollectible'))
        for effect in effects:
            source = effect.move_line_id
            transfer_line = self.env['account.move.line'].search([
                ('effect_group_id', '=', self.id),
                ('effect_group_effect_id', '=', effect.id),
                ('move_id', 'in', self.grouping_move_ids.ids),
                ('move_id.state', '=', 'posted'),
            ], limit=1)
            if not source or not transfer_line:
                raise UserError(_('No se puede cerrar la agrupación: falta el apunte original o su reclasificación para el efecto %s.') % effect.display_name)
            if source.account_id != transfer_line.account_id or source.partner_id != transfer_line.partner_id:
                raise UserError(_('No se puede conciliar el efecto %s porque la cuenta o el cliente/proveedor no coinciden.') % effect.display_name)
            lines = (source | transfer_line).filtered(lambda line: not line.reconciled)
            if lines and source.account_id.reconcile:
                lines.reconcile()
            if not source.reconciled or not transfer_line.reconciled:
                raise UserError(_('El efecto %s no ha podido conciliarse completamente. Se ha cancelado la liquidación para evitar marcar facturas como pagadas incorrectamente.') % effect.display_name)
        if effects:
            paid_date = self.paid_date or fields.Date.context_today(self)
            effects.write({'state': 'paid', 'paid_date': paid_date})
            effects._log_situation('paid', _('Agrupación completamente saldada'))

    def _unreconcile_original_effects(self):
        self.ensure_one()
        for effect in self.effect_ids.filtered(lambda e: not e.is_container and e.move_line_id):
            transfer_line = self.env['account.move.line'].search([
                ('effect_group_id', '=', self.id),
                ('effect_group_effect_id', '=', effect.id),
                ('move_id', 'in', self.grouping_move_ids.ids),
            ], limit=1)
            lines = (effect.move_line_id | transfer_line).filtered(lambda line: line.reconciled)
            if lines:
                lines.remove_move_reconcile()

    def _create_grouping_move(self):
        """Reclassify source effect lines into one open balance per partner/account."""
        self.ensure_one()
        if not self.bank_journal_id:
            raise UserError(_('Selecciona el diario bancario antes de generar el asiento inicial de agrupación.'))
        if self.bank_journal_id.type not in ('bank', 'cash'):
            raise UserError(_('El diario de la agrupación debe ser de banco o caja.'))
        effects = self.effect_ids.filtered(lambda e: not e.is_container and e.state in ('grouped', 'remitted', 'pending'))
        grouped = {}
        move_lines = []
        has_new = False
        for effect in effects:
            exists = self.env['account.move.line'].search_count([
                ('effect_group_id', '=', self.id),
                ('effect_group_effect_id', '=', effect.id),
                ('move_id', 'in', self.grouping_move_ids.ids),
                ('move_id.state', '=', 'posted'),
            ])
            if exists:
                continue
            source = effect.move_line_id
            if not source or source.reconciled:
                raise UserError(_('El efecto %s no tiene un vencimiento contable abierto que pueda agruparse.') % effect.display_name)
            if not source.account_id.reconcile:
                raise UserError(_('La cuenta %s del efecto %s no permite conciliación.') % (source.account_id.display_name, effect.display_name))
            company_amount = abs(source.amount_residual)
            expected_balance_sign = 1 if self.company_type == 'customer' else -1
            if source.balance * expected_balance_sign <= 0:
                raise UserError(_('El efecto %s tiene un saldo contable de signo contrario al tipo de cartera de la agrupación.') % effect.display_name)
            currency = source.currency_id or self.company_id.currency_id
            currency_amount = abs(source.amount_residual_currency) if currency != self.company_id.currency_id else company_amount
            if effect.currency_id != currency:
                raise UserError(_('La moneda del efecto %s no coincide con la moneda de su vencimiento contable.') % effect.display_name)
            if effect.currency_id.compare_amounts(effect.amount, currency_amount) != 0:
                raise UserError(_('El importe del efecto %s (%s) no coincide con su saldo contable pendiente (%s). Actualiza el efecto antes de agruparlo.') % (effect.display_name, effect.amount, currency_amount))
            partner = source.partner_id or effect.partner_id
            if not partner:
                raise UserError(_('El efecto %s no tiene cliente/proveedor para contabilizar su agrupación.') % effect.display_name)
            key = (source.account_id.id, partner.id, currency.id)
            bucket = grouped.setdefault(key, {'account': source.account_id, 'partner': partner, 'currency': currency, 'company': 0.0, 'currency_amount': 0.0})
            bucket['company'] += company_amount
            bucket['currency_amount'] += currency_amount
            sign_source = -1 if self.company_type == 'customer' else 1
            move_lines.append((0, 0, {
                'name': effect.name or effect.display_name,
                'account_id': source.account_id.id,
                'partner_id': partner.id,
                'currency_id': currency.id,
                'amount_currency': sign_source * currency_amount,
                'debit': company_amount if sign_source > 0 else 0.0,
                'credit': company_amount if sign_source < 0 else 0.0,
                'date_maturity': self.due_date or self.date,
                'effect_group_id': self.id,
                'effect_group_effect_id': effect.id,
            }))
            has_new = True
        if not has_new:
            if self.grouping_move_id:
                return self.grouping_move_id
            raise UserError(_('No hay efectos nuevos que reclasificar en esta agrupación.'))
        for bucket in grouped.values():
            sign_group = 1 if self.company_type == 'customer' else -1
            move_lines.append((0, 0, {
                'name': self.name,
                'account_id': bucket['account'].id,
                'partner_id': bucket['partner'].id,
                'currency_id': bucket['currency'].id,
                'amount_currency': sign_group * bucket['currency_amount'],
                'debit': bucket['company'] if sign_group > 0 else 0.0,
                'credit': bucket['company'] if sign_group < 0 else 0.0,
                'date_maturity': self.due_date or self.date,
                'effect_group_id': self.id,
            }))
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': self.date,
            'journal_id': self.bank_journal_id.id,
            'ref': self.reference or self.name,
            'effect_group_ids': [(4, self.id)],
            'line_ids': move_lines,
        })
        move.action_post()
        self.write({
            'grouping_move_id': self.grouping_move_id.id or move.id,
            'grouping_move_ids': [(4, move.id)],
        })
        self._compute_totals()
        self._sync_container_effect()
        return move

    def action_generate_grouping_move(self):
        self.ensure_one()
        move = self._create_grouping_move()
        return {
            'type': 'ir.actions.act_window', 'name': _('Asiento inicial de agrupación'),
            'res_model': 'account.move', 'view_mode': 'form', 'res_id': move.id, 'target': 'current',
        }

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
            'state': 'paid' if self.state == 'paid' else ('remitted' if self.state == 'remitted' else ('pending' if self.state != 'cancelled' else 'returned')),
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
        self._compute_totals()
        if effects and self.currency_id.is_zero(self.amount_pending):
            paid_date = payment_date or fields.Date.context_today(self)
            self.write({'state': 'paid', 'paid_date': paid_date})
            self._reconcile_original_effects()
            residuals = self.portfolio_effect_ids.filtered(lambda e: e.is_portfolio_effect and e.active)
            residuals.write({'active': False})
            self._log_container_situation(_('Agrupación saldada'))
        elif effects and self.currency_id.compare_amounts(self.amount_pending, self.amount_total) < 0:
            self.write({'state': 'partial', 'paid_date': payment_date or fields.Date.context_today(self)})
            self._sync_partial_portfolio_effect()
        elif effects:
            self.write({'state': 'remitted' if self.remittance_id else 'draft', 'paid_date': False})
        # The original effect's pending amount is a stored computed field.
        # Re-write its current state so Odoo invalidates/recomputes that stored
        # field after allocations created by a remittance (linked through the
        # group_ids M2M rather than the direct group_id history field).
        for effect in effects:
            effect.write({'state': effect.state})
        self._compute_totals()
        self._sync_container_effect()
        return True

    def _sync_partial_portfolio_effect(self):
        self.ensure_one()
        pending = self.amount_pending
        active_helpers = self.portfolio_effect_ids.filtered(lambda e: e.is_portfolio_effect and e.active)
        if self.currency_id.is_zero(pending):
            active_helpers.write({'active': False})
            return self.env['account.effect']
        helper = active_helpers[:1]
        vals = {
            'company_id': self.company_id.id,
            'company_type': self.company_type,
            'partner_id': self.partner_id.id if self.partner_id else False,
            'move_id': False, 'move_line_id': False,
            'reference': False, 'invoice_reference': False,
            'due_date': self.due_date or fields.Date.context_today(self),
            'effect_type': 'effect',
            'bank_journal_id': self.bank_journal_id.id if self.bank_journal_id else False,
            'partner_bank_id': self.partner_bank_id.id if self.partner_bank_id else False,
            'payment_direction': self.payment_direction,
            'amount': pending, 'currency_id': self.currency_id.id,
            'state': 'pending', 'is_container': True, 'is_portfolio_effect': True,
            'container_group_id': self.id, 'container_remittance_id': False,
            'cartera_number': self.cartera_number, 'active': True,
        }
        if helper:
            helper.write(vals)
        else:
            helper = self.env['account.effect'].create(vals)
            helper._log_situation('pending', _('Saldo pendiente tras pago parcial de agrupación'))
        (active_helpers - helper).write({'active': False})
        return helper

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
        if self.state not in ('draft', 'partial'):
            raise UserError(_('Solo se puede editar una agrupación pendiente o parcialmente saldada.'))
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
        effects = effects.filtered(lambda e: not e.is_container and e.state in ('grouped', 'pending', 'remitted'))
        if not effects:
            raise UserError(_('No hay efectos pendientes seleccionados.'))
        if len(effects.mapped('currency_id')) > 1:
            raise UserError(_('No se pueden saldar efectos de distintas monedas en una misma agrupación.'))
        if not self.grouping_move_id or self.grouping_move_id.state != 'posted':
            raise UserError(_('Antes de saldar la agrupación debes generar el asiento inicial de reclasificación.'))
        accounting_lines = self.env['account.move.line']
        for effect in effects:
            source = effect.move_line_id
            if source:
                accounting_lines |= self._get_grouping_lines().filtered(
                    lambda line: line.account_id == source.account_id
                    and line.partner_id == source.partner_id
                    and not line.reconciled
                )
        line_ids = accounting_lines.ids
        if not line_ids:
            raise UserError(_('La agrupación no tiene saldo contable pendiente para los efectos seleccionados.'))
        return {
            'name': title,
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment.register',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_model': 'account.move.line',
                'active_ids': line_ids,
                'group_id': self.id,
                'cartera_effect_ids': effects.ids,
                'cartera_amount_editable': True,
            },
        }

    def action_saldar(self):
        self.ensure_one()
        effects = self.effect_ids.filtered(
            lambda e: not e.is_container and e.state in ('grouped', 'pending', 'remitted')
            and not e.currency_id.is_zero(self._get_effect_pending_amount(e))
        )
        return self._payment_register_action(effects, _('Saldar agrupación'))

    def action_create_remittance(self):
        self.ensure_one()
        effects = self.effect_ids.filtered(lambda e: not e.is_container and e.state in ('grouped', 'pending', 'remitted') and not e.remittance_id and not e.currency_id.is_zero(self._get_effect_pending_amount(e)))
        if not effects:
            raise UserError(_('La agrupación no contiene efectos pendientes de remesar.'))

        currencies = effects.mapped('currency_id')
        if len(currencies) > 1:
            raise UserError(_('No se pueden remesar efectos de distintas monedas.'))

        remittance = self.env['account.effect.remittance'].create({
            'company_id': self.company_id.id,
            'company_type': self.company_type,
            'currency_id': self.currency_id.id,
            'bank_journal_id': self.bank_journal_id.id if self.bank_journal_id else False,
            'partner_bank_id': self.partner_bank_id.id if self.partner_bank_id else False,
        })
        self._compute_totals()
        group_state = 'partial' if self.currency_id.compare_amounts(self.amount_pending, self.amount_total) < 0 else 'remitted'
        self.write({'remittance_id': remittance.id, 'state': group_state})
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
        if any(p.state not in ('draft', 'canceled') for p in payments if p):
            return True
        histories = self.env['account.effect.container.payment.history'].search([
            '|', ('group_id', '=', self.id), ('group_ids', 'in', self.id),
            ('type', '=', 'paid'), ('move_id.state', '=', 'posted'),
        ])
        return bool(histories)

    def action_ungroup_selected(self):
        for group in self:
            if group._has_active_payments():
                raise UserError(_('No se pueden quitar efectos de una agrupación que tiene pagos activos. Anula primero los pagos asociados a la agrupación.'))
            effects = group.effect_ids.filtered(lambda e: not e.is_container and e.state != 'paid')
            for original_move in group.grouping_move_ids.filtered(lambda m: m.state == 'posted'):
                reversal = original_move._reverse_moves(default_values_list=[{
                    'date': fields.Date.context_today(group),
                    'ref': (original_move.ref or group.name) + ' - ' + _('Anulación de agrupación'),
                }], cancel=False)
                reversal.action_post()
                reversal.write({'effect_group_ids': [(4, group.id)]})
                for account in original_move.line_ids.mapped('account_id').filtered(lambda a: a.reconcile):
                    partners = (original_move.line_ids | reversal.line_ids).filtered(lambda l: l.account_id == account).mapped('partner_id')
                    for partner in partners:
                        paired = (original_move.line_ids | reversal.line_ids).filtered(
                            lambda l: l.account_id == account and l.partner_id == partner and not l.reconciled
                        )
                        if len(paired) >= 2:
                            paired.reconcile()
            effects.write({'group_id': False, 'remittance_id': False, 'cartera_number': False, 'state': 'pending', 'paid_date': False, 'payment_id': False})
            effects._compute_amount_pending()
            effects._compute_payment_state()
            # Partial portfolio effects are only a historical representation of
            # the previous partial settlement; once all payments are annulled
            # they must not remain as selectable effects.
            helpers = group.portfolio_effect_ids.filtered(lambda e: e.is_portfolio_effect)
            helpers.write({'active': False})
            group.write({'grouping_move_id': False, 'grouping_move_ids': [(5, 0, 0)]})
            group._compute_totals()
            group._sync_container_effect()
        return True


    def action_open_accounting_entries(self):
        self.ensure_one()
        move_ids = set(self.all_payment_history_ids.mapped('move_id').ids)
        move_ids.update(self.grouping_move_ids.ids)
        move_ids.update(self.effect_ids.mapped('payment_move_id').ids)
        move_ids.update(self.effect_ids.mapped('adjustment_move_id').ids)
        move_ids.update(self.env['account.move'].search([('effect_group_ids', 'in', self.id)]).ids)
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
        histories = history_model.search([
            '|', ('group_id', '=', self.id), ('group_ids', 'in', self.id),
            ('type', '=', 'paid'),
        ], order='date desc, id desc')

        # A remittance can create one accounting entry spanning several groups.
        # It must be reversed from the remittance to avoid cancelling only part
        # of a consolidated operation.
        custom_history = histories.filtered(lambda history: history.move_id and history.move_id.state == 'posted')[:1]
        if custom_history:
            if custom_history.remittance_id:
                raise UserError(_(
                    'Este pago pertenece a una remesa conjunta. Anúlalo desde la ficha de la remesa para revertir todos los clientes afectados.'
                ))
            custom_history.move_id._reverse_cartera_payment_entry(note=_('Anulación del pago de agrupación'))
            custom_history.write({'type': 'cancelled'})
            self._unreconcile_original_effects()
            effects = self.effect_ids.filtered(lambda effect: not effect.is_container and effect.state != 'returned')
            state = 'remitted' if self.remittance_id else 'grouped'
            effects.write({'state': state, 'paid_date': False, 'payment_id': False})
            self._update_payment_state_from_effects()
            effects._log_situation(state, _('Pago de agrupación anulado'))
            return True

        # Compatibility path for payments created by older module versions.
        histories = histories.filtered(lambda history: history.payment_id)
        payments = histories.mapped('payment_id') | self.effect_ids.mapped('payment_id')
        payments = payments.exists().sorted(key=lambda payment: (payment.date or fields.Date.min, payment.id))[-1:]
        if not payments:
            raise UserError(_('No se han encontrado pagos de la agrupación.'))
        for payment in payments:
            related = histories.filtered(lambda history: history.payment_id == payment).mapped('effect_ids')
            related |= self.effect_ids.filtered(lambda effect: effect.payment_id == payment and not effect.is_container)
            if payment.state not in ('draft', 'canceled'):
                payment.action_cancel()
            history_model.search([('payment_id', '=', payment.id), ('type', '=', 'paid')]).write({'type': 'cancelled'})
            related.filtered(lambda effect: effect.state != 'returned').write({
                'state': 'grouped', 'paid_date': False, 'payment_id': False,
            })
        self._unreconcile_original_effects()
        self._update_payment_state_from_effects()
        return True

    def action_update_changes(self):
        for group in self:
            group._compute_totals()
            group._sync_container_effect()
        return True
