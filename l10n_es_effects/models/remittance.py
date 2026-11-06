from datetime import date
from odoo import api, fields, models, _
from odoo.exceptions import UserError


def _default_cartera_bank_journal(env, company=None):
    company = company or env.company
    journals = env['account.journal'].search([
        ('company_id', '=', company.id),
        ('type', '=', 'bank'),
        ('default_account_id', '!=', False),
    ], order='sequence, id')
    return journals[:1].id


def _default_company_partner_bank(env, company=None):
    """Return the first bank account owned by the Odoo company partner."""
    company = company or env.company
    if not company.partner_id:
        return False
    bank = env['res.partner.bank'].search(
        [('partner_id', '=', company.partner_id.id)], order='id', limit=1
    )
    return bank.id or False


class AccountEffectRemittance(models.Model):
    _name = 'account.effect.remittance'
    _description = 'Remesa de efectos'
    _order = 'date desc, id desc'

    name = fields.Char(string='Nombre', compute='_compute_name', store=True)
    cartera_number = fields.Char(string='Nº Cartera', required=True, readonly=True, copy=False)
    company_id = fields.Many2one('res.company', string='Empresa', required=True, readonly=True, default=lambda self: self.env.company)
    company_partner_id = fields.Many2one('res.partner', related='company_id.partner_id', readonly=True)
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
    bank_journal_id = fields.Many2one(
        'account.journal', string='Banco', domain="[('type', '=', 'bank')]",
        default=lambda self: _default_cartera_bank_journal(self.env),
    )
    initial_move_id = fields.Many2one(
        'account.move', string='Asiento inicial de remesa', readonly=True,
        copy=False, ondelete='restrict',
    )
    partner_bank_id = fields.Many2one(
        'res.partner.bank', string='Cuenta bancaria',
        domain="[('partner_id', '=', company_partner_id)]",
        default=lambda self: _default_company_partner_bank(self.env),
    )
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
    has_valid_initial_move = fields.Boolean(string='Asiento inicial válido', compute='_compute_has_valid_initial_move', store=False)

    @api.constrains('company_id', 'partner_bank_id')
    def _check_company_partner_bank(self):
        for remittance in self:
            if remittance.partner_bank_id and remittance.partner_bank_id.partner_id != remittance.company_id.partner_id:
                raise UserError(_('La cuenta bancaria de una remesa debe pertenecer a la empresa propia configurada en Odoo.'))

    @api.depends('cartera_number')
    def _compute_name(self):
        for record in self:
            record.name = _('Remesa nº %s') % record.cartera_number

    def _assign_cartera_number(self):
        for remittance in self:
            if not remittance.cartera_number or remittance.cartera_number == '/':
                number = self.env['account.effect']._next_cartera_number()
                remittance.with_context(cartera_skip_container_sync=True).write({'cartera_number': number})
        return True

    def _initial_move_is_valid(self):
        """Validate the remittance transfer entry by matching each effect's source/target legs.

        A grouped effect can enter a remittance with a residual lower than its
        original face value. Comparing the move to amount_total would then
        incorrectly hide settlement controls even though the transfer is sound.
        """
        self.ensure_one()
        move = self.initial_move_id
        effects = self.effect_ids.filtered(lambda effect: not effect.is_container and not effect.is_portfolio_effect)
        if not move or move.state != 'posted' or not effects:
            return False
        lines = move.line_ids.filtered(lambda line: line.effect_remittance_effect_id)
        sources = lines.filtered(lambda line: line.effect_remittance_line_type == 'source')
        targets = lines.filtered(lambda line: line.effect_remittance_line_type == 'target')
        if set(targets.mapped('effect_remittance_effect_id').ids) != set(effects.ids):
            return False
        if set(sources.mapped('effect_remittance_effect_id').ids) != set(effects.ids):
            return False
        for effect in effects:
            effect_sources = sources.filtered(lambda line: line.effect_remittance_effect_id == effect)
            effect_targets = targets.filtered(lambda line: line.effect_remittance_effect_id == effect)
            source_total = sum(abs(line.amount_currency) for line in effect_sources)
            target_total = sum(abs(line.amount_currency) for line in effect_targets)
            if effect.currency_id.compare_amounts(source_total, target_total) != 0:
                return False
            if effect.currency_id.is_zero(target_total):
                return False
        company_balance = sum(move.line_ids.mapped('debit')) - sum(move.line_ids.mapped('credit'))
        return self.company_id.currency_id.is_zero(company_balance)

    @api.depends('initial_move_id.state', 'effect_ids.amount', 'effect_ids.state', 'amount_total')
    def _compute_has_valid_initial_move(self):
        for remittance in self:
            remittance.has_valid_initial_move = remittance._initial_move_is_valid()

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
        # A remittance belongs to the active Odoo company. It is a bank batch,
        # not a single customer/supplier operation. Keep the original creation
        # lifecycle (number, projection and initial entry) in this same method.
        active_company_id = self.env.company.id
        for vals in vals_list:
            vals['company_id'] = active_company_id
            vals.pop('partner_id', None)
            if not vals.get('cartera_number'):
                vals['cartera_number'] = '/'
        records = super().create(vals_list)
        for record in records:
            # A remittance is a cartera in its own right and gets its number
            # immediately, even when it is created before adding any effects.
            record._assign_cartera_number()
            record._sync_container_effect()
        if any('effect_ids' in vals for vals in vals_list):
            records._ensure_initial_move()
        return records

    def write(self, vals):
        if 'company_id' in vals and any(record.company_id.id != self.env.company.id for record in self):
            raise UserError(_('La compañía de una remesa no se puede modificar.'))
        if 'company_id' in vals and vals['company_id'] != self.env.company.id:
            raise UserError(_('La compañía de la remesa debe ser la compañía activa.'))
        vals = dict(vals)
        vals.pop('partner_id', None)
        result = super().write(vals)
        if not self.env.context.get('cartera_skip_container_sync'):
            for remittance in self:
                if 'reference' in vals and remittance.initial_move_id and remittance.initial_move_id.state == 'posted':
                    remittance.initial_move_id.write({'ref': _('Remesa nº %s') % remittance.cartera_number + ((' · ' + remittance.reference) if remittance.reference else '')})
                if any(key in vals for key in ('reference', 'due_date', 'bank_journal_id', 'partner_bank_id', 'company_type', 'date', 'effect_ids')):
                    remittance._compute_totals()
                    remittance._sync_container_effect()
                    remittance._ensure_initial_move()
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
            'partner_id': False,
            'due_date': self.due_date or self.date or fields.Date.context_today(self),
            'reference': self.reference or False,
            'bank_journal_id': self.bank_journal_id.id if self.bank_journal_id else False,
            'partner_bank_id': self.partner_bank_id.id if self.partner_bank_id else False,
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
        self._ensure_initial_move()
        accounting_lines = self.env['account.move.line']
        if not self._initial_move_is_valid():
            raise UserError(_('No se puede saldar: el asiento inicial de la remesa debe estar publicado y cuadrado con el importe de los efectos.'))
        if self.initial_move_id and self.initial_move_id.state == 'posted':
            accounting_lines |= self.initial_move_id.line_ids.filtered(
                lambda line: line.effect_remittance_line_type == 'target'
                and line.effect_remittance_effect_id in effects
                and not line.reconciled
            )
        if not self.initial_move_id:
            for effect in effects:
                if effect.group_id and effect.group_id.grouping_move_id:
                    grouping = effect.group_id
                    accounting_lines |= grouping._get_grouping_lines().filtered(
                        lambda line: line.account_id == grouping.grouping_account_id
                        and line.partner_id == grouping.partner_id
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

    def _ensure_initial_move(self):
        """Create or refresh the single opening transfer entry for a draft remittance.

        The entry moves each selected effect from its original receivable/payable
        line (or grouping balance) to a remittance-specific open line. When the
        selection changes, the same move is rebuilt after releasing its prior
        reconciliations; no second opening entry is accumulated.
        """
        Move = self.env['account.move']
        MoveLine = self.env['account.move.line']
        for remittance in self:
            company_currency = remittance.company_id.currency_id
            if remittance.state != 'draft':
                continue
            effects = remittance.effect_ids.filtered(
                lambda effect: not effect.is_container and not effect.is_portfolio_effect
                and effect.state in ('pending', 'grouped', 'remitted')
            ).sorted(key=lambda item: (item.due_date or fields.Date.today(), item.id))
            if not effects:
                # A draft remittance may become empty after an effect is removed.
                # Release the original source reconciliations and cancel the
                # now obsolete opening entry instead of leaving it posted.
                empty_move = remittance.initial_move_id
                if empty_move and empty_move.state == 'posted':
                    source_transfers = empty_move.line_ids.filtered(
                        lambda line: line.effect_remittance_line_type == 'source'
                    )
                    if source_transfers.filtered('reconciled'):
                        source_transfers.remove_move_reconcile()
                    empty_move.button_draft()
                elif empty_move and empty_move.state == 'cancel':
                    empty_move.button_draft()
                if empty_move and empty_move.state == 'draft':
                    empty_move.button_cancel()
                continue

            remittance._assign_cartera_number()
            journal = remittance.bank_journal_id
            if not journal:
                candidates = self.env['account.journal'].search([
                    ('company_id', '=', remittance.company_id.id),
                    ('type', 'in', ('bank', 'cash')),
                    ('default_account_id', '!=', False),
                ], order='sequence, id')
                journal = candidates[:1]
                if journal:
                    remittance.with_context(cartera_skip_container_sync=True).write({'bank_journal_id': journal.id})
            if not journal or journal.company_id != remittance.company_id or journal.type not in ('bank', 'cash') or not journal.default_account_id:
                raise UserError(_('Selecciona un diario bancario o de caja con cuenta de liquidez para la remesa.'))

            move = remittance.initial_move_id
            # A draft remittance has no payment history. Rebuilding the same move
            # is safe after undoing only the reconciliations created by its source lines.
            if move and move.state == 'posted':
                source_transfers = move.line_ids.filtered(
                    lambda line: line.effect_remittance_line_type == 'source'
                )
                if source_transfers.filtered('reconciled'):
                    source_transfers.remove_move_reconcile()
                move.button_draft()
            elif move and move.state == 'cancel':
                # Reuse a previously cancelled opening entry if effects are added
                # again while the remittance is still unpaid.
                move.button_draft()

            # Track how much of each open source line has already been allocated
            # in this rebuild. Several effects may share one grouping balance.
            line_values = []
            origin_line_ids = set()
            capacity = {}
            for effect in effects:
                root = effect.portfolio_chain_id or effect
                origin = root.move_line_id
                if effect.group_id and effect.group_id.grouping_move_id and effect.group_id.grouping_move_id.state == 'posted':
                    grouping = effect.group_id
                    if not grouping.grouping_account_id or not grouping.partner_id:
                        raise UserError(_('La agrupación %s necesita una cuenta y un cliente/proveedor de destino antes de remesarse.') % grouping.display_name)
                    candidates = grouping._get_grouping_lines().filtered(
                        lambda line: line.account_id == grouping.grouping_account_id
                        and line.partner_id == grouping.partner_id
                        and line.currency_id == effect.currency_id
                        and not line.reconciled
                    )
                else:
                    candidates = origin.filtered(lambda line: not line.reconciled) if origin else MoveLine

                pending = effect._cartera_pending_amount()
                if not candidates and not (effect.group_id and effect.group_id.grouping_move_id and effect.group_id.grouping_move_id.state == 'posted'):
                    if not origin and not effect.move_id and effect.manual_account_id:
                        raise UserError(_(
                            'El efecto manual %s debe incorporarse primero a una agrupación para poder remesarse. '
                            'La agrupación generará el traspaso contable desde su cuenta destino.'
                        ) % effect.display_name)
                if effect.currency_id.is_zero(pending):
                    continue
                if not candidates:
                    raise UserError(_('El efecto %s no tiene un apunte contable abierto para incorporarlo a la remesa.') % effect.display_name)

                remaining = pending
                for source in candidates:
                    if effect.currency_id.is_zero(remaining):
                        break
                    source_currency = source.currency_id or remittance.company_id.currency_id
                    if source_currency != effect.currency_id:
                        raise UserError(_('La moneda del efecto %s no coincide con la de su apunte contable.') % effect.display_name)
                    residual_currency = abs(
                        source.amount_residual_currency
                        if source.currency_id and source.currency_id != remittance.company_id.currency_id
                        else source.amount_residual
                    )
                    if source.id not in capacity:
                        capacity[source.id] = residual_currency
                    available = min(remaining, capacity[source.id])
                    if effect.currency_id.is_zero(available):
                        continue
                    company_residual = abs(source.amount_residual)
                    # Allocate the company-currency balance in the same
                    # proportion as the effect's foreign-currency residual.
                    # This also avoids repeating the full grouped balance when
                    # several effects draw from one consolidated group line.
                    company_amount = (
                        company_residual * available / residual_currency
                        if residual_currency else 0.0
                    )
                    company_amount = remittance.company_id.currency_id.round(company_amount)
                    source_sign = 1 if source.amount_residual > 0 else -1
                    currency_sign = 1 if (source.amount_residual_currency or source.amount_residual) > 0 else -1
                    partner = source.partner_id or effect.partner_id
                    if not partner or not source.account_id.reconcile:
                        raise UserError(_('El efecto %s necesita un cliente/proveedor y una cuenta conciliable.') % effect.display_name)
                    common = {
                        'account_id': source.account_id.id,
                        'partner_id': partner.id,
                        'currency_id': source_currency.id,
                        'date_maturity': remittance.due_date or remittance.date,
                        'effect_remittance_effect_id': effect.id,
                    }
                    line_values.append((0, 0, dict(common, **{
                        'name': _('Traspaso origen · %s') % effect.name,
                        'amount_currency': -currency_sign * available,
                        'debit': company_amount if source_sign < 0 else 0.0,
                        'credit': company_amount if source_sign > 0 else 0.0,
                        'effect_remittance_line_type': 'source',
                        'effect_remittance_origin_line_id': source.id,
                    })))
                    line_values.append((0, 0, dict(common, **{
                        'name': _('Remesa nº %s · %s') % (remittance.cartera_number, effect.name),
                        'amount_currency': currency_sign * available,
                        'debit': company_amount if source_sign > 0 else 0.0,
                        'credit': company_amount if source_sign < 0 else 0.0,
                        'effect_remittance_line_type': 'target',
                        'effect_remittance_origin_line_id': False,
                        'effect_ids': [(6, 0, [effect.id])],
                    })))
                    origin_line_ids.add(source.id)
                    capacity[source.id] = remittance.currency_id.round(capacity[source.id] - available)
                    remaining = remittance.currency_id.round(remaining - available)
                if not effect.currency_id.is_zero(remaining):
                    raise UserError(_('No se ha podido trasladar el saldo completo del efecto %s a la remesa.') % effect.display_name)

            if not line_values:
                # If all effects were removed from an unpaid draft remittance,
                # release the former source reconciliations and cancel its now
                # obsolete opening move. Keep the move linked for audit/reuse.
                if move and move.state == 'draft':
                    move.button_cancel()
                continue
            label = _('Remesa nº %s') % remittance.cartera_number
            if remittance.reference:
                label += ' · ' + remittance.reference.strip()
            move_vals = {
                'move_type': 'entry',
                'date': remittance.date,
                'journal_id': journal.id,
                'ref': label,
                'effect_remittance_id': remittance.id,
            }
            if move:
                move.write({
                    'line_ids': [(5, 0, 0)] + line_values,
                    'date': remittance.date,
                    'journal_id': journal.id,
                    'ref': label,
                })
            else:
                move = Move.create(dict(move_vals, line_ids=line_values))
                remittance.initial_move_id = move.id
            move.action_post()

            # Reconcile each origin once against all remittance source lines
            # that were created from it (handles several effects for one customer).
            for origin in MoveLine.browse(list(origin_line_ids)).exists():
                transfers = move.line_ids.filtered(
                    lambda line: line.effect_remittance_line_type == 'source'
                    and line.effect_remittance_origin_line_id == origin
                    and not line.reconciled
                )
                to_reconcile = (origin | transfers).filtered(lambda line: not line.reconciled)
                if len(to_reconcile) >= 2:
                    to_reconcile.reconcile()
        return True

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
            'target': 'main',
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
            'target': 'main',
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
        move_ids.update(self.initial_move_id.ids)
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

    def _return_selected_effects(
        self, effects, journal=None, impute_expenses=False,
        effect_expenses=0.0, expense_account=None,
        effect_commissions=0.0, commission_account=None,
        create_new_effect=False, payment_date=False, communication=False,
        group_bank_entries=False,
    ):
        """Post a remittance return with independent fee and replacement-effect options."""
        self.ensure_one()
        effects = effects.filtered(
            lambda effect: not effect.is_container
            and self.currency_id.compare_amounts(self._effect_returnable_amount(effect), 0.0) > 0
        )
        if not effects:
            raise UserError(_('No hay efectos con importes cobrados pendientes de devolución en esta remesa.'))
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
        today = payment_date or fields.Date.context_today(self)
        circular_reference = (communication or self.reference or (_('Remesa nº %s') % self.cartera_number)).strip()
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
        if effect_expenses < 0 or effect_commissions < 0:
            raise UserError(_('Los gastos y comisiones no pueden ser negativos.'))
        expenses = currency.round(effect_expenses) if impute_expenses else 0.0
        commissions = currency.round(effect_commissions) if impute_expenses else 0.0
        if expenses and (not expense_account or expense_account.deprecated):
            raise UserError(_('Selecciona una cuenta contable activa para los gastos.'))
        if commissions and (not commission_account or commission_account.deprecated):
            raise UserError(_('Selecciona una cuenta contable activa para las comisiones.'))
        for fee_account in (
            expense_account if expenses else self.env['account.account'],
            commission_account if commissions else self.env['account.account'],
        ):
            if fee_account and fee_account.company_ids and self.company_id not in fee_account.company_ids:
                raise UserError(_('Las cuentas de gastos y comisiones deben pertenecer a la compañía de la remesa.'))

        fee_total_currency = currency.round(expenses + commissions)
        fee_company = 0.0
        fee_lines = []
        for fee_amount, fee_account, label in (
            (expenses, expense_account, _('Gastos de devolución')),
            (commissions, commission_account, _('Comisiones de devolución')),
        ):
            if not fee_amount:
                continue
            fee_company_amount = currency._convert(
                fee_amount, company_currency, self.company_id, today, round=True,
            ) if currency != company_currency else fee_amount
            fee_company += fee_company_amount
            fee_lines.append((0, 0, {
                'name': '%s · %s' % (circular_reference, label),
                'account_id': fee_account.id,
                'debit': fee_company_amount,
                'credit': 0.0,
            }))

        is_customer = company_type == 'customer'
        line_values = []
        return_data = []
        total_company = 0.0
        total_currency = 0.0
        fee_currency_assigned = 0.0
        fee_company_assigned = 0.0
        ordered_effects = effects.sorted(key=lambda item: (item.due_date or date.max, item.id))
        returnable_amounts = {
            effect.id: currency.round(self._effect_returnable_amount(effect))
            for effect in ordered_effects
        }
        principal_total = sum(returnable_amounts.values())

        for index, effect in enumerate(ordered_effects):
            source = effect.move_line_id
            if not source and effect.portfolio_chain_id:
                source = effect.portfolio_chain_id.move_line_id
            # Grouped effects are reopened against the consolidated grouping account.
            if effect.group_id and effect.group_id.grouping_move_id:
                partner = effect.group_id.partner_id
                account = effect.group_id.grouping_account_id
            else:
                partner = (source.partner_id if source else False) or effect.partner_id
                account = source.account_id if source else effect.manual_account_id
            if not account and partner:
                account = (
                    partner.with_company(self.company_id).property_account_receivable_id if is_customer
                    else partner.with_company(self.company_id).property_account_payable_id
                )
            if not partner:
                raise UserError(_('El efecto %s no tiene un cliente o proveedor asociado.') % effect.display_name)
            if not account or not account.reconcile:
                raise UserError(_('El efecto %s no tiene una cuenta conciliable para registrar la devolución.') % effect.display_name)

            amount = returnable_amounts[effect.id]
            if currency.is_zero(amount):
                continue
            company_amount = currency._convert(
                amount, company_currency, self.company_id, today, round=True,
            ) if currency != company_currency else amount

            # Allocate imputed fees proportionally so each optional replacement
            # effect receives its own principal + fee share. The last line takes
            # the rounding residue, keeping the total exact.
            if impute_expenses and fee_total_currency and principal_total:
                if index == len(ordered_effects) - 1:
                    fee_share = currency.round(fee_total_currency - fee_currency_assigned)
                else:
                    fee_share = currency.round(fee_total_currency * amount / principal_total)
                fee_currency_assigned += fee_share
                if index == len(ordered_effects) - 1:
                    fee_company_share = company_currency.round(fee_company - fee_company_assigned)
                else:
                    fee_company_share = currency._convert(
                        fee_share, company_currency, self.company_id, today, round=True,
                    ) if currency != company_currency else fee_share
                fee_company_assigned += fee_company_share
            else:
                fee_share = 0.0
                fee_company_share = 0.0

            new_effect = self.env['account.effect']
            replacement_amount = currency.round(amount + fee_share) if (create_new_effect and impute_expenses) else amount
            if create_new_effect:
                new_effect = self.env['account.effect'].with_context(cartera_skip_manual_opening=True).create({
                    'company_id': effect.company_id.id,
                    'company_type': effect.company_type,
                    'partner_id': partner.id,
                    'manual_account_id': account.id,
                    'manual_nature': effect.manual_nature or 'ordinary',
                    'reference': circular_reference or (_('Pendiente tras devolución de %s') % (effect.reference or effect.name)),
                    'invoice_reference': effect.invoice_reference,
                    'due_date': today,
                    'effect_type': 'effect',
                    'bank_journal_id': journal.id,
                    'partner_bank_id': effect.partner_bank_id.id if effect.partner_bank_id else False,
                    'payment_direction': effect.payment_direction,
                    'amount': replacement_amount,
                    'currency_id': currency.id,
                    'state': 'pending',
                })

            receivable_debit = is_customer
            line_values.append((0, 0, {
                'name': _('Devolución de %s') % effect.name,
                'account_id': account.id,
                'partner_id': partner.id,
                'currency_id': currency.id,
                'amount_currency': amount if receivable_debit else -amount,
                'debit': company_amount if receivable_debit else 0.0,
                'credit': company_amount if not receivable_debit else 0.0,
                'date_maturity': today,
            }))
            # The replacement effect is deliberately not linked to the return
            # move line: manual effects must not acquire an origin journal entry.
            return_data.append((effect, new_effect, amount, replacement_amount, company_amount, fee_company_share))
            total_company += company_amount
            total_currency += amount

        if is_customer is False and fee_company > total_company + company_currency.rounding:
            raise UserError(_('Los gastos y comisiones no pueden superar el importe devuelto por el proveedor.'))

        line_values.extend(fee_lines)
        # With grouped bank entries, produce one liquidity line. Otherwise keep
        # a bank line per returned effect, still respecting the fee allocation.
        if group_bank_entries or len(return_data) <= 1:
            bank_amount = total_company + fee_company if is_customer else total_company - fee_company
            if bank_amount < -company_currency.rounding:
                raise UserError(_('El importe neto bancario no puede ser negativo.'))
            bank_amount = max(0.0, bank_amount)
            bank_debit = not is_customer
            line_values.append((0, 0, {
                'name': circular_reference,
                'account_id': bank_account.id,
                'debit': bank_amount if bank_debit else 0.0,
                'credit': bank_amount if not bank_debit else 0.0,
            }))
        else:
            for effect, _new_effect, _amount, _replacement, company_amount, fee_share in return_data:
                bank_amount = company_amount + fee_share if is_customer else company_amount - fee_share
                if bank_amount < -company_currency.rounding:
                    raise UserError(_('El importe neto bancario no puede ser negativo.'))
                bank_amount = max(0.0, bank_amount)
                bank_debit = not is_customer
                line_values.append((0, 0, {
                    'name': _('%s · %s') % (circular_reference, effect.name),
                    'account_id': bank_account.id,
                    'debit': bank_amount if bank_debit else 0.0,
                    'credit': bank_amount if not bank_debit else 0.0,
                }))

        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': today,
            'journal_id': journal.id,
            'ref': _('%s Devuelto') % circular_reference,
            'effect_remittance_id': self.id,
            'line_ids': line_values,
        })
        move.action_post()

        for effect, returned_effect, amount, replacement_amount, _company_amount, _fee_share in return_data:
            # account.effect.create() already registers the new manual effect in
            # the situation history; avoid writing a duplicate pending event.
            was_fully_settled = effect.currency_id.is_zero(effect._cartera_pending_amount())
            if was_fully_settled:
                effect.write({'state': 'returned', 'paid_date': today, 'payment_id': False})
                effect._log_situation('returned', _('Efecto devuelto mediante asiento %s') % move.name)
            self.env['account.effect.payment.history'].create({
                'effect_id': effect.id,
                'date': today,
                'move_id': move.id,
                'journal_id': journal.id,
                'amount': amount,
                'operation_type': 'returned',
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
            'allocation_line_ids': [(0, 0, {'effect_id': effect.id, 'amount': amount}) for effect, _new_effect, amount, _replacement, _company_amount, _fee_share in return_data],
            'type': 'returned',
        })
        for group in effects.mapped('group_id'):
            group._compute_totals()
            group._sync_container_effect()
        self._compute_totals()
        self._sync_container_effect()
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_add_pending_effects(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Solo se pueden añadir efectos a una remesa pendiente.'))
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
            history.portfolio_effect_ids.write({'active': False, 'payment_id': False})
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

    def unlink(self):
        for remittance in self:
            effects = remittance.effect_ids.filtered(lambda effect: not effect.is_container)
            if effects or remittance._has_active_payments() or remittance.payment_history_ids:
                raise UserError(_('Solo se puede eliminar una remesa vacía y sin pagos.'))
            move = remittance.initial_move_id
            if move and move.state == 'posted' and move.line_ids:
                raise UserError(_('No se puede eliminar una remesa con un asiento inicial publicado.'))
            if move and move.state == 'draft':
                move.button_cancel()
            remittance.with_context(cartera_skip_container_sync=True).write({'initial_move_id': False})
        return super().unlink()

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
            if remittance.state == 'draft' and not remittance._has_active_payments():
                remittance._ensure_initial_move()
        return True


    def action_saldar_entero(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('El saldado íntegro solo está disponible antes del primer saldado. Para continuar una remesa parcial, utiliza Saldar parcialmente.'))
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
