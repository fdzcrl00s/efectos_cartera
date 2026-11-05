from datetime import date
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
    has_returnable_effects = fields.Boolean(string='Tiene efectos saldados para devolver', compute='_compute_has_returnable_effects', store=False)

    @api.depends('cartera_number')
    def _compute_name(self):
        for record in self:
            record.name = _('Remesa nº %s') % record.cartera_number

    def _effect_returnable_amount(self, effect):
        """Return the amount of this effect paid through this remittance and not returned yet."""
        self.ensure_one()
        lines = self.env['account.effect.container.payment.line'].search([
            ('effect_id', '=', effect.id),
            ('history_id.remittance_id', '=', self.id),
        ])
        paid = sum(lines.filtered(lambda line: line.history_id.type == 'paid').mapped('amount'))
        returned = sum(lines.filtered(lambda line: line.history_id.type == 'returned').mapped('amount'))
        available = effect.currency_id.round(paid - returned)
        if effect.currency_id.is_zero(available) and effect.state == 'paid':
            # Compatibility with settled effects created before per-effect
            # allocation lines were introduced.
            legacy_paid = self.payment_history_ids.filtered(
                lambda history: history.type == 'paid' and effect in history.effect_ids
                and not history.allocation_line_ids
            )
            if legacy_paid:
                available = effect.amount
        return max(0.0, available)

    @api.depends(
        'effect_ids.state', 'effect_ids.is_container',
        'payment_history_ids.type', 'payment_history_ids.effect_ids',
        'payment_history_ids.allocation_line_ids.amount',
        'payment_history_ids.allocation_line_ids.effect_id',
    )
    def _compute_has_returnable_effects(self):
        for record in self:
            record.has_returnable_effects = any(
                record.currency_id.compare_amounts(record._effect_returnable_amount(effect), 0.0) > 0
                for effect in record.effect_ids.filtered(lambda item: not item.is_container)
            )

    @api.depends(
        'payment_history_ids.payment_id.state', 'payment_history_ids.move_id.state',
        'payment_history_ids.type', 'effect_ids.payment_id.state',
    )
    def _compute_has_active_payments(self):
        for record in self:
            record.has_active_payments = record._has_active_payments()

    @api.depends('effect_ids.amount', 'effect_ids.amount_pending', 'effect_ids.move_line_id.amount_residual', 'effect_ids.move_line_id.reconciled', 'effect_ids.state', 'effect_ids.currency_id')
    def _compute_totals(self):
        for record in self:
            effects = record.effect_ids.filtered(lambda e: not e.is_container)
            record.effect_count = len(effects)
            record.amount_total = sum(effects.mapped('amount'))
            record.amount_pending = sum(e._cartera_pending_amount() for e in effects if e.state not in ('returned', 'uncollectible'))
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

    def write(self, vals):
        result = super().write(vals)
        if not self.env.context.get('cartera_skip_container_sync') and any(
            key in vals for key in ('reference', 'due_date', 'bank_journal_id', 'partner_bank_id', 'company_type')
        ):
            for remittance in self:
                remittance._compute_totals()
                remittance._sync_container_effect()
        return result

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
                key=lambda e: (e.paid_date or date.min, e.id), reverse=True
            )[:1].payment_id.id if self.effect_ids.filtered(lambda e: e.payment_id) else False,
        }
        if effect:
            effect.with_context(cartera_sync_container=True).write(dict(vals, group_id=False, remittance_id=False))
        else:
            effect = self.env['account.effect'].create(vals)
            self.container_effect_id = effect.id
        return effect

    def _update_payment_state_from_effects(self, payment_date=False):
        self.ensure_one()
        effects = self.effect_ids.filtered(lambda e: not e.is_container)
        payment_date = payment_date or fields.Date.context_today(self)
        self._compute_totals()
        if not effects:
            self.write({'state': 'draft', 'paid_date': False})
        elif self.currency_id.is_zero(self.amount_pending):
            self.write({'state': 'paid', 'paid_date': payment_date})
        elif self.currency_id.compare_amounts(self.amount_pending, self.amount_total) < 0:
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
        effects = effects.filtered(lambda e: not e.is_container and e.state in ('pending', 'grouped', 'remitted'))
        effects = effects.filtered(lambda e: not e.currency_id.is_zero(e._cartera_pending_amount()))
        if not effects:
            raise UserError(_('No hay efectos con saldo pendiente en esta remesa.'))
        currencies = effects.mapped('currency_id')
        if len(currencies) > 1:
            raise UserError(_('No se pueden saldar efectos de distintas monedas en una misma remesa.'))
        accounting_lines = self.env['account.move.line']
        for effect in effects:
            if effect.group_id and effect.group_id.grouping_move_id:
                source = effect.move_line_id
                if source:
                    accounting_lines |= effect.group_id._get_grouping_lines().filtered(
                        lambda line: line.account_id == source.account_id
                        and line.partner_id == source.partner_id
                        and not line.reconciled
                    )
            else:
                root = effect.portfolio_chain_id or effect
                if root.move_line_id and not root.move_line_id.reconciled:
                    accounting_lines |= root.move_line_id
        if not accounting_lines:
            raise UserError(_('No hay apuntes contables abiertos para liquidar los efectos seleccionados.'))
        return {
            'name': title,
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment.register',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_model': 'account.move.line',
                'active_ids': accounting_lines.ids,
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
        move_ids.update(self.effect_ids.mapped('group_id.grouping_move_id').ids)
        move_ids.update(self.effect_ids.mapped('group_id.grouping_move_ids').ids)
        move_ids.update(self.env['account.move'].search([('effect_remittance_id', '=', self.id)]).ids)
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
        effects = self.env['account.effect'].browse([
            effect.id for effect in self.effect_ids.filtered(lambda item: not item.is_container)
            if self.currency_id.compare_amounts(self._effect_returnable_amount(effect), 0.0) > 0
        ])
        if not effects:
            raise UserError(_('No hay efectos con importes cobrados pendientes de devolución en esta remesa.'))
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

    def _return_selected_effects(self, effects, journal=None):
        """Return selected settled effects with one bank line and a separate due line per effect."""
        self.ensure_one()
        effects = effects.filtered(
            lambda effect: not effect.is_container
            and self.currency_id.compare_amounts(self._effect_returnable_amount(effect), 0.0) > 0
        )
        if not effects:
            raise UserError(_('Selecciona al menos un efecto con un importe cobrado pendiente de devolución.'))
        if any(effect.company_id != self.company_id for effect in effects):
            raise UserError(_('Todos los efectos devueltos deben pertenecer a la misma compañía.'))
        currencies = effects.mapped('currency_id')
        if len(currencies) != 1:
            raise UserError(_('No se pueden devolver efectos de distintas monedas en una misma operación.'))
        company_types = set(effects.mapped('company_type'))
        if len(company_types) != 1:
            raise UserError(_('No se pueden mezclar clientes y proveedores en una misma devolución.'))

        company_type = next(iter(company_types))
        currency = currencies[0]
        journals = effects.mapped('payment_id.journal_id').filtered(lambda item: item)
        if journal:
            journal = journal.exists()
        if not journal and len(journals) > 1:
            raise UserError(_('Los efectos seleccionados proceden de diarios bancarios distintos. Devuélvelos por separado.'))
        journal = journal or journals[:1] or self.bank_journal_id or effects.mapped('bank_journal_id')[:1]
        if not journal or journal.type not in ('bank', 'cash') or not journal.default_account_id:
            raise UserError(_('Selecciona un diario bancario con cuenta de liquidez para registrar la devolución.'))

        bank_account = journal.default_account_id
        company_currency = self.company_id.currency_id
        today = fields.Date.context_today(self)
        is_customer = company_type == 'customer'
        line_values = []
        return_data = []
        total_company = 0.0
        total_currency = 0.0

        for effect in effects.sorted(key=lambda item: (item.due_date or date.max, item.id)):
            source = effect.move_line_id
            if not source and effect.portfolio_chain_id:
                source = effect.portfolio_chain_id.move_line_id
            partner = (source.partner_id if source else False) or effect.partner_id
            account = source.account_id if source else (
                partner.with_company(self.company_id).property_account_receivable_id if is_customer
                else partner.with_company(self.company_id).property_account_payable_id
            )
            if not partner or not account or not account.reconcile:
                raise UserError(_('El efecto %s no tiene una cuenta de cliente/proveedor conciliable para registrar la devolución.') % effect.display_name)

            amount = currency.round(self._effect_returnable_amount(effect))
            if currency.is_zero(amount):
                raise UserError(_('No se ha encontrado un importe saldado para el efecto %s.') % effect.display_name)

            company_amount = currency._convert(amount, company_currency, self.company_id, today, round=True) if currency != company_currency else amount
            # Return of a customer receipt: debit receivable / credit bank.
            # Return of a supplier payment: debit bank / credit payable.
            receivable_debit = is_customer
            new_effect = self.env['account.effect'].create({
                'company_id': effect.company_id.id,
                'company_type': effect.company_type,
                'partner_id': partner.id,
                'reference': _('Pendiente tras devolución de %s') % (effect.reference or effect.name),
                'invoice_reference': effect.invoice_reference,
                'due_date': today,
                'effect_type': 'effect',
                'bank_journal_id': journal.id,
                'partner_bank_id': effect.partner_bank_id.id if effect.partner_bank_id else False,
                'payment_direction': effect.payment_direction,
                'amount': amount,
                'currency_id': currency.id,
                'state': 'pending',
            })
            line_values.append((0, 0, {
                'name': _('Devolución de %s') % effect.name,
                'account_id': account.id,
                'partner_id': partner.id,
                'currency_id': currency.id,
                'amount_currency': amount if receivable_debit else -amount,
                'debit': company_amount if receivable_debit else 0.0,
                'credit': company_amount if not receivable_debit else 0.0,
                'date_maturity': today,
                'effect_id': new_effect.id,
            }))
            return_data.append((effect, new_effect, amount))
            total_company += company_amount
            total_currency += amount

        # Customer receipts being returned are an outflow; returned supplier payments are an inflow.
        bank_debit = not is_customer
        line_values.append((0, 0, {
            'name': _('Devolución de remesa %s') % self.cartera_number,
            'account_id': bank_account.id,
            'debit': total_company if bank_debit else 0.0,
            'credit': total_company if not bank_debit else 0.0,
        }))
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': today,
            'journal_id': journal.id,
            'ref': _('Devolución de remesa %s') % self.cartera_number,
            'effect_remittance_id': self.id,
            'line_ids': line_values,
        })
        move.action_post()

        for effect, returned_effect, amount in return_data:
            return_line = move.line_ids.filtered(lambda line: line.effect_id == returned_effect)[:1]
            if not return_line:
                raise UserError(_('No se ha podido enlazar el nuevo efecto pendiente con su apunte contable.'))
            returned_effect.write({'move_id': return_line.move_id.id, 'move_line_id': return_line.id})
            was_fully_settled = effect.currency_id.is_zero(effect._cartera_pending_amount())
            if was_fully_settled:
                effect.write({'state': 'returned', 'paid_date': today, 'payment_id': False})
                effect._log_situation('returned', _('Efecto devuelto mediante asiento %s') % move.name)
            returned_effect._log_situation('pending', _('Nuevo efecto pendiente tras devolución de %s') % effect.name)
            self.env['account.effect.payment.history'].create({
                'effect_id': effect.id,
                'date': today,
                'move_id': move.id,
                'journal_id': journal.id,
                'amount': amount,
                'note': _('Devolución contabilizada en %s') % move.name,
            })

        self.env['account.effect.container.payment.history'].create({
            'remittance_id': self.id,
            'reference': move.name or move.ref,
            'move_id': move.id,
            'date': today,
            'effect_ids': [(6, 0, effects.ids)],
            'amount': currency.round(total_currency),
            'currency_id': currency.id,
            'group_ids': [(6, 0, effects.mapped('group_id').ids)],
            'allocation_line_ids': [(0, 0, {'effect_id': effect.id, 'amount': amount}) for effect, returned_effect, amount in return_data],
            'type': 'returned',
        })
        for group in effects.mapped('group_id'):
            group._compute_totals()
            group._sync_container_effect()
        self._compute_totals()
        self._sync_container_effect()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Asiento de devolución'),
            'res_model': 'account.move',
            'view_mode': 'form',
            'res_id': move.id,
            'target': 'current',
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
        if any(p.state not in ('draft', 'canceled') for p in payments if p):
            return True
        return bool(self.payment_history_ids.filtered(lambda h: h.type == 'paid' and h.move_id.state == 'posted'))

    def action_anular_saldado(self):
        self.ensure_one()
        histories = self.payment_history_ids.filtered(
            lambda history: history.type == 'paid' and history.move_id and history.move_id.state == 'posted'
        ).sorted(key=lambda history: (history.date or date.min, history.id))
        custom_history = histories[-1:]
        if custom_history:
            history = custom_history[0]
            history.move_id._reverse_cartera_payment_entry(note=_('Anulación del pago de remesa'))
            linked_payments = history.payment_ids | history.payment_id
            if linked_payments:
                linked_payments.with_context(cartera_internal_state_update=True).write({'state': 'canceled'})
            history.write({'type': 'cancelled'})
            groups = history.group_ids | history.effect_ids.mapped('group_id')
            for group in groups:
                group._unreconcile_original_effects()
            related = history.effect_ids.filtered(lambda effect: not effect.is_container and effect.state != 'returned')
            for effect in related:
                restored_state = 'remitted' if effect.remittance_id else ('grouped' if effect.group_id else 'pending')
                effect.write({'state': restored_state, 'paid_date': False, 'payment_id': False})
                effect._log_situation(restored_state, _('Pago de remesa anulado'))
            for group in groups:
                group._update_payment_state_from_effects()
            self._update_payment_state_from_effects()
            return True

        # Compatibility path for native account.payment records from older versions.
        history_model = self.env['account.effect.container.payment.history']
        histories = self.payment_history_ids.filtered(lambda history: history.type == 'paid' and history.payment_id)
        payments = histories.mapped('payment_id') | self.effect_ids.mapped('payment_id')
        payments = payments.exists().sorted(key=lambda payment: (payment.date or date.min, payment.id))[-1:]
        if not payments:
            raise UserError(_('No se han encontrado pagos de la remesa.'))
        related = self.env['account.effect']
        for payment in payments:
            related |= histories.filtered(lambda history: history.payment_id == payment).mapped('effect_ids')
            related |= self.effect_ids.filtered(lambda effect: effect.payment_id == payment and not effect.is_container)
            if payment.state not in ('draft', 'canceled'):
                payment.action_cancel()
            history_model.search([('payment_id', '=', payment.id), ('type', '=', 'paid')]).write({'type': 'cancelled'})
        related.filtered(lambda effect: effect.state != 'returned').write({
            'state': 'remitted', 'paid_date': False, 'payment_id': False, 'adjustment_move_id': False,
        })
        for effect in related:
            effect._compute_amount_pending()
            effect._compute_payment_state()
        for group in related.mapped('group_id'):
            group._unreconcile_original_effects()
            group._update_payment_state_from_effects()
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
                        group.write({'remittance_id': False})
                        group._update_payment_state_from_effects()

            standalone.write({'remittance_id': False, 'cartera_number': False, 'state': 'pending'})
            remittance._compute_totals()
            remittance._update_payment_state_from_effects()
        return True


    def action_saldar_entero(self):
        self.ensure_one()
        effects = self.effect_ids.filtered(
            lambda e: not e.is_container and e.state in ('pending', 'grouped', 'remitted')
            and not e.currency_id.is_zero(e._cartera_pending_amount())
        )
        if not effects:
            raise UserError(_('No hay efectos pendientes que se puedan saldar en esta remesa.'))
        return self._payment_register_action(effects, _('Saldar remesa'))

    def action_saldar_parcial(self):
        self.ensure_one()
        effects = self.effect_ids.filtered(
            lambda e: not e.is_container and e.state in ('pending', 'grouped', 'remitted')
            and not e.currency_id.is_zero(e._cartera_pending_amount())
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
