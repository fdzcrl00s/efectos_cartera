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
    # When only one liquidity journal exists it is unambiguous; otherwise use
    # the first configured journal as the default while leaving it editable.
    return journals[:1].id


class AccountEffectGroup(models.Model):
    _name = 'account.effect.group'
    _description = 'Agrupación de efectos'
    _order = 'date desc, id desc'

    name = fields.Char(string='Nombre', compute='_compute_name', store=True)
    cartera_number = fields.Char(string='Nº Cartera', required=True, readonly=True, copy=False)
    company_id = fields.Many2one('res.company', string='Empresa', required=True, readonly=True, default=lambda self: self.env.company)
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
    grouping_account_id = fields.Many2one(
        'account.account', string='Cuenta de agrupación',
        domain="[('deprecated', '=', False), ('reconcile', '=', True), ('company_ids', 'in', company_id)]",
        check_company=True,
        help='Cuenta de clientes/proveedores en la que quedará representado el saldo agrupado. Se propone la cuenta de cobro/pago definida en la ficha del cliente/proveedor si todos los terceros de la agrupación comparten la misma; si no está definida o difiere, debe seleccionarse manualmente según el plan contable.',
    )
    bank_journal_id = fields.Many2one(
        'account.journal', string='Diario de asiento', domain="[('type', 'in', ('bank', 'cash'))]",
        default=lambda self: _default_cartera_bank_journal(self.env),
    )
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
    has_valid_grouping_move = fields.Boolean(string='Asiento inicial válido', compute='_compute_has_valid_grouping_move', store=False)

    @api.model
    def _partner_grouping_account(self, partners, company, company_type):
        """Return a default grouping account only when all partners share it.

        The Odoo company (res.company) and the customer/supplier (res.partner)
        remain unchanged and separate. This only reads the partner's
        company-dependent receivable/payable property.
        """
        Account = self.env['account.account']
        partners = partners.exists()
        if not partners or not company:
            return Account
        property_name = (
            'property_account_receivable_id'
            if company_type == 'customer'
            else 'property_account_payable_id'
        )
        account_by_partner = [
            partner.with_company(company)[property_name]
            for partner in partners
        ]
        if any(not account for account in account_by_partner):
            return Account
        account_ids = {account.id for account in account_by_partner}
        if len(account_ids) != 1:
            return Account
        account = account_by_partner[0]
        if (
            account.deprecated
            or not account.reconcile
            or (account.company_ids and company not in account.company_ids)
        ):
            return Account
        return account

    @api.onchange('partner_id', 'company_type', 'company_id')
    def _onchange_partner_grouping_account(self):
        for group in self:
            account = group._partner_grouping_account(
                group.partner_id, group.company_id, group.company_type
            )
            # A partner property is a default only. If it is not configured,
            # do not erase a manually selected grouping account.
            if account and not group.grouping_account_id:
                group.grouping_account_id = account[:1]

    @api.depends('company_type')
    def _compute_payment_direction(self):
        for record in self:
            record.payment_direction = 'receive' if record.company_type == 'customer' else 'send'

    @api.depends('cartera_number')
    def _compute_name(self):
        for record in self:
            record.name = _('Agrupación nº %s') % record.cartera_number

    def _assign_cartera_number(self):
        for group in self:
            if not group.cartera_number or group.cartera_number == '/':
                number = self.env['account.effect']._next_cartera_number()
                group.with_context(cartera_skip_auto_group_move=True).write({'cartera_number': number})
        return True

    def _grouping_move_is_valid(self):
        self.ensure_one()
        effects = self.effect_ids.filtered(lambda effect: not effect.is_container and effect.state not in ('returned', 'uncollectible'))
        moves = (self.grouping_move_ids | self.grouping_move_id).filtered(lambda move: move and move.state != 'cancel')
        if not effects or not moves or any(move.state != 'posted' for move in moves):
            return False
        lines = moves.mapped('line_ids').filtered(lambda line: line.effect_group_id == self)
        detail_lines = lines.filtered('effect_group_effect_id')
        summary_lines = lines.filtered(lambda line: not line.effect_group_effect_id)
        detail_effects = detail_lines.mapped('effect_group_effect_id')
        if set(detail_effects.ids) != set(effects.ids):
            return False
        for effect in effects:
            effect_lines = detail_lines.filtered(lambda line: line.effect_group_effect_id == effect)
            total = sum(abs(line.amount_currency) for line in effect_lines)
            if effect.currency_id.compare_amounts(total, effect.amount) != 0:
                return False
        detail_total = sum(abs(line.amount_currency) for line in detail_lines)
        summary_total = sum(abs(line.amount_currency) for line in summary_lines)
        if not self.partner_id or not self.grouping_account_id or not summary_lines:
            return False
        if any(line.account_id != self.grouping_account_id for line in summary_lines):
            return False
        if any(line.partner_id != self.partner_id for line in summary_lines):
            return False
        if len(summary_lines) != 1:
            return False
        if self.currency_id.compare_amounts(detail_total, self.amount_total) != 0:
            return False
        if self.currency_id.compare_amounts(summary_total, self.amount_total) != 0:
            return False
        company_balance = sum(moves.mapped('line_ids').mapped('debit')) - sum(moves.mapped('line_ids').mapped('credit'))
        return self.company_id.currency_id.is_zero(company_balance)

    @api.depends('grouping_move_id.state', 'grouping_move_ids.state', 'effect_ids.amount', 'effect_ids.state', 'partner_id', 'grouping_account_id')
    def _compute_has_valid_grouping_move(self):
        for group in self:
            group.has_valid_grouping_move = group._grouping_move_is_valid()

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
                record.amount_pending = sum(e._cartera_pending_amount() for e in effects if e.state not in ('returned', 'uncollectible'))

    def _get_effect_paid_amount(self, effect):
        """Sum valid allocations already assigned to a grouped effect."""
        self.ensure_one()
        lines = self.env['account.effect.container.payment.line'].search([
            ('effect_id', '=', effect.id),
            ('history_id.type', 'in', ('paid', 'returned')),
        ])
        paid = sum(lines.filtered(lambda line: line.history_id.type == 'paid').mapped('amount'))
        returned = sum(lines.filtered(lambda line: line.history_id.type == 'returned').mapped('amount'))
        return max(0.0, paid - returned)

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
            if not transfer_line:
                raise UserError(_('No se puede cerrar la agrupación: falta la reclasificación contable del efecto %s.') % effect.display_name)
            if not source:
                # A standalone manual effect has no source open item by design.
                # Its transfer line was created by the grouping entry itself;
                # there is no original line to reconcile against. The group
                # summary line is settled normally, and the effect is closed
                # in portfolio state below.
                if effect.move_id or not effect.manual_account_id:
                    raise UserError(_('No se puede cerrar la agrupación: el efecto %s no tiene un apunte de origen ni una cuenta manual válida.') % effect.display_name)
                if transfer_line.account_id != effect.manual_account_id:
                    raise UserError(_('La cuenta de origen de la reclasificación no coincide con la cuenta del efecto manual %s.') % effect.display_name)
                continue
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
        """Create or refresh the single initial reclassification entry."""
        self.ensure_one()
        if not self.bank_journal_id:
            raise UserError(_('No hay un diario bancario/caja configurado para la agrupación.'))
        if self.bank_journal_id.company_id != self.company_id or self.bank_journal_id.type not in ('bank', 'cash') or not self.bank_journal_id.default_account_id:
            raise UserError(_('El diario de la agrupación debe ser de banco/caja, pertenecer a la compañía y tener cuenta de liquidez.'))

        effects = self.effect_ids.filtered(
            lambda effect: not effect.is_container and effect.state in ('grouped', 'remitted', 'pending')
        )
        if not effects:
            return self.grouping_move_id
        if not self.partner_id:
            raise UserError(_('Selecciona el cliente/proveedor único al que se trasladará el saldo de la agrupación.'))

        grouped = {}
        move_lines = []
        for effect in effects:
            source = effect.move_line_id
            if not source or source.reconciled or source.move_id.state != 'posted':
                source = effect._ensure_manual_open_item_line()
            if (not source or source.reconciled or source.move_id.state != 'posted') and effect.move_id:
                source = effect._resolve_invoice_source_line(force=True)

            if source and not source.reconciled and source.move_id.state == 'posted':
                account = source.account_id
                partner = source.partner_id or effect.partner_id
                currency = source.currency_id or self.company_id.currency_id
                company_amount = abs(source.amount_residual)
                currency_amount = abs(
                    source.amount_residual_currency
                    if source.currency_id and source.currency_id != self.company_id.currency_id
                    else source.amount_residual
                )
                expected_balance_sign = 1 if self.company_type == 'customer' else -1
                if source.balance * expected_balance_sign <= 0:
                    raise UserError(_('El efecto %s tiene un saldo contable de signo contrario al tipo de cartera de la agrupación.') % effect.display_name)
            else:
                # A manual effect without an origin line is intentionally
                # accounting-free until it is grouped. At this point the
                # selected account becomes the source leg of the transfer.
                if effect.move_id:
                    raise UserError(_(
                        'El efecto %(effect)s no tiene un vencimiento contable abierto en su factura %(invoice)s.'
                    ) % {'effect': effect.display_name, 'invoice': effect.move_id.display_name})
                account = effect.manual_account_id
                partner = effect.partner_id
                currency = effect.currency_id
                currency_amount = effect._cartera_pending_amount()
                if not account:
                    raise UserError(_('El efecto manual %s no tiene una cuenta destino.') % effect.display_name)
                if account.deprecated or not account.reconcile:
                    raise UserError(_('La cuenta %s del efecto %s debe estar activa y permitir conciliación.') % (account.display_name, effect.display_name))
                if account.company_ids and self.company_id not in account.company_ids:
                    raise UserError(_('La cuenta %s no pertenece a la compañía de la agrupación.') % account.display_name)
                company_amount = currency._convert(
                    currency_amount, self.company_id.currency_id, self.company_id,
                    self.date or fields.Date.context_today(self), round=True,
                ) if currency != self.company_id.currency_id else currency_amount

            if not account or not account.reconcile:
                raise UserError(_('La cuenta del efecto %s no permite conciliación.') % effect.display_name)
            if currency != effect.currency_id:
                raise UserError(_('La moneda del efecto %s no coincide con la moneda de su vencimiento contable.') % effect.display_name)
            if effect.currency_id.compare_amounts(effect.amount, currency_amount) != 0:
                raise UserError(_('El importe del efecto %s (%s) no coincide con su saldo pendiente (%s).') % (effect.display_name, effect.amount, currency_amount))
            if not partner:
                raise UserError(_('El efecto %s no tiene cliente/proveedor para contabilizar su agrupación.') % effect.display_name)

            key = (account.id, partner.id, currency.id)
            bucket = grouped.setdefault(key, {
                'account': account, 'partner': partner, 'currency': currency,
                'company': 0.0, 'currency_amount': 0.0,
            })
            bucket['company'] += company_amount
            bucket['currency_amount'] += currency_amount
            sign_source = -1 if self.company_type == 'customer' else 1
            move_lines.append((0, 0, {
                'name': effect.name or effect.display_name,
                'account_id': account.id,
                'partner_id': partner.id,
                'currency_id': currency.id,
                'amount_currency': sign_source * currency_amount,
                'debit': company_amount if sign_source > 0 else 0.0,
                'credit': company_amount if sign_source < 0 else 0.0,
                'date_maturity': self.due_date or self.date,
                'effect_group_id': self.id,
                'effect_group_effect_id': effect.id,
            }))

        grouping_account = self.grouping_account_id
        if not grouping_account:
            manual_without_source = effects.filtered(
                lambda effect: not effect.move_id and not effect.move_line_id and not effect.opening_move_id
            )
            manual_accounts = manual_without_source.mapped('manual_account_id')
            source_accounts = self.env['account.account']
            for effect in effects - manual_without_source:
                source = effect.move_line_id or effect._ensure_manual_open_item_line()
                if source:
                    source_accounts |= source.account_id
            if manual_without_source and len(effects) == len(manual_without_source):
                partner_account = self._partner_grouping_account(
                    self.partner_id, self.company_id, self.company_type
                )
                grouping_account = partner_account if partner_account and partner_account not in manual_accounts else self.env['account.account']
            elif len(source_accounts) == 1:
                grouping_account = source_accounts[:1]
            else:
                grouping_account = self._partner_grouping_account(
                    self.partner_id, self.company_id, self.company_type
                )
            if grouping_account:
                self.with_context(cartera_skip_auto_group_move=True).write({'grouping_account_id': grouping_account.id})
            else:
                raise UserError(_('Indica la cuenta destino de la agrupación. Para efectos manuales sin apunte de origen debe ser distinta de la cuenta destino de origen.'))
        manual_without_source = effects.filtered(
            lambda effect: not effect.move_id and not effect.move_line_id and not effect.opening_move_id
        )
        if any(effect.manual_account_id == grouping_account for effect in manual_without_source):
            raise UserError(_('La cuenta destino de la agrupación debe ser distinta de la cuenta destino de origen de los efectos manuales.'))
        if grouping_account.company_ids and self.company_id not in grouping_account.company_ids:
            raise UserError(_('La cuenta de agrupación no pertenece a la compañía de la agrupación.'))
        if not grouping_account.reconcile or grouping_account.deprecated:
            raise UserError(_('La cuenta de agrupación debe estar activa y permitir conciliación.'))
        # Source lines retain their original customer/supplier, so the audit
        # trail and eventual invoice reconciliation stay individually traceable.
        # The destination side is consolidated into ONE balance line for the
        # selected group partner, on the grouping balance account.
        total_company = sum(bucket['company'] for bucket in grouped.values())
        total_currency = sum(bucket['currency_amount'] for bucket in grouped.values())
        target_currency = self.currency_id
        sign_group = 1 if self.company_type == 'customer' else -1
        move_lines.append((0, 0, {
            'name': self.name,
            'account_id': grouping_account.id,
            'partner_id': self.partner_id.id,
            'currency_id': target_currency.id,
            'amount_currency': sign_group * total_currency,
            'debit': total_company if sign_group > 0 else 0.0,
            'credit': total_company if sign_group < 0 else 0.0,
            'date_maturity': self.due_date or self.date,
            'effect_group_id': self.id,
        }))

        # While the grouping is still unpaid, adding/removing effects rebuilds
        # this same initial move instead of accumulating duplicate entries.
        existing_moves = (self.grouping_move_ids | self.grouping_move_id).sorted(key=lambda move: (move.id != self.grouping_move_id.id, move.id))
        main_move = existing_moves[:1]
        if self.state in ('partial', 'paid') or self._has_active_payments():
            if main_move and main_move.state == 'posted':
                return main_move
            raise UserError(_('No se puede reconstruir el asiento inicial después de haber iniciado los saldados.'))
        if main_move:
            if main_move.state == 'posted':
                reconciled_lines = main_move.line_ids.filtered('reconciled')
                if reconciled_lines:
                    reconciled_lines.remove_move_reconcile()
                main_move.button_draft()
            elif main_move.state == 'cancel':
                main_move.button_draft()
            if main_move.state != 'draft':
                raise UserError(_('No se puede actualizar el asiento inicial de la agrupación.'))
            main_move.write({
                'date': self.date,
                'journal_id': self.bank_journal_id.id,
                'ref': _('Agrupado'),
                'effect_group_ids': [(6, 0, [self.id])],
                'line_ids': [(5, 0, 0)] + move_lines,
            })
        else:
            main_move = self.env['account.move'].create({
                'move_type': 'entry',
                'date': self.date,
                'journal_id': self.bank_journal_id.id,
                'ref': _('Agrupado'),
                'effect_group_ids': [(6, 0, [self.id])],
                'line_ids': move_lines,
            })

        # Retire obsolete incremental opening moves from earlier versions.
        for extra in existing_moves - main_move:
            if extra.state == 'posted':
                if extra.line_ids.filtered('reconciled'):
                    extra.line_ids.filtered('reconciled').remove_move_reconcile()
                extra.button_draft()
            if extra.state == 'draft':
                extra.button_cancel()
        main_move.action_post()
        self.with_context(cartera_skip_auto_group_move=True).write({
            'grouping_move_id': main_move.id,
            'grouping_move_ids': [(6, 0, [main_move.id])],
        })
        self._compute_totals()
        self._sync_container_effect()
        if not self._grouping_move_is_valid():
            raise UserError(_('El asiento inicial de la agrupación no cuadra con el importe de los efectos. No se habilitará el saldado.'))
        return main_move

    def action_generate_grouping_move(self):
        self.ensure_one()
        self._ensure_grouping_move()
        if not self.grouping_move_id:
            raise UserError(_(
                'No se ha podido crear el asiento inicial automáticamente. '
                'Selecciona primero el diario bancario de la agrupación y vuelve a guardar o confirmar.'
            ))
        move = self.grouping_move_id
        return {
            'type': 'ir.actions.act_window', 'name': _('Asiento inicial de agrupación'),
            'res_model': 'account.move', 'view_mode': 'form', 'res_id': move.id, 'target': 'current',
        }

    def action_confirm_grouping(self):
        """Confirm the draft grouping and ensure its initial move exists."""
        self.ensure_one()
        if not self.effect_ids.filtered(lambda effect: not effect.is_container):
            raise UserError(_('Añade al menos un efecto antes de confirmar la agrupación.'))
        if not self.partner_id:
            raise UserError(_('Selecciona el cliente/proveedor único al que se trasladará el saldo de la agrupación.'))
        self._ensure_grouping_move()
        if not self.grouping_move_id:
            raise UserError(_(
                'La agrupación todavía no tiene asiento inicial. Selecciona un diario bancario/caja '
                'y vuelve a confirmar.'
            ))
        self._sync_container_effect()
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def _ensure_grouping_move(self):
        """Create/refresh the initial move once the grouping has effects."""
        Journal = self.env['account.journal']
        for group in self:
            if group.state not in ('draft', 'partial', 'remitted'):
                continue
            effects = group.effect_ids.filtered(
                lambda effect: not effect.is_container and effect.state in ('grouped', 'pending', 'remitted')
            )
            if not effects:
                # An empty pending grouping has no portfolio accounting balance.
                # Cancel the reusable opening move and release its relation so
                # the empty grouping can be deleted without leaving entries.
                if group.state == 'draft' and not group._has_active_payments():
                    moves = (group.grouping_move_ids | group.grouping_move_id)
                    for move in moves:
                        if move.state == 'posted':
                            reconciled = move.line_ids.filtered('reconciled')
                            if reconciled:
                                reconciled.remove_move_reconcile()
                            move.button_draft()
                        if move.state == 'draft':
                            move.button_cancel()
                    group.with_context(cartera_skip_auto_group_move=True).write({
                        'grouping_move_id': False,
                        'grouping_move_ids': [(5, 0, 0)],
                    })
                    group._compute_totals()
                    group._sync_container_effect()
                continue
            group._assign_cartera_number()
            if not group.partner_id:
                # A grouping with multiple source customers/suppliers must be
                # assigned its single destination partner in the form first.
                continue
            if group.state in ('partial', 'remitted') and group.grouping_move_id and group.grouping_move_id.state == 'posted':
                continue
            if group._has_active_payments() and group.grouping_move_id and group.grouping_move_id.state == 'posted':
                continue
            manual_without_source = effects.filtered(
                lambda effect: not effect.move_id and not effect.move_line_id and not effect.opening_move_id
            )
            manual_accounts = manual_without_source.mapped('manual_account_id')
            # A grouping destination that is also the source account of a
            # manual effect would cancel the reclassification instead of
            # moving the balance. Clear an unsafe inherited/default account
            # and let the user choose a distinct destination in the form.
            if group.grouping_account_id and group.grouping_account_id in manual_accounts:
                group.with_context(cartera_skip_auto_group_move=True).write({'grouping_account_id': False})
            if not group.grouping_account_id:
                source_accounts = self.env['account.account']
                for effect in effects - manual_without_source:
                    source = effect.move_line_id or effect._ensure_manual_open_item_line()
                    if source:
                        source_accounts |= source.account_id
                partner_account = group._partner_grouping_account(
                    group.partner_id, group.company_id, group.company_type
                )
                default_account = self.env['account.account']
                if len(source_accounts) == 1 and source_accounts[:1] not in manual_accounts:
                    default_account = source_accounts[:1]
                elif partner_account and partner_account not in manual_accounts:
                    default_account = partner_account
                if default_account:
                    group.with_context(cartera_skip_auto_group_move=True).write({
                        'grouping_account_id': default_account.id
                    })
                else:
                    # Keep the grouping editable for an explicit destination account.
                    continue
            if not group.bank_journal_id:
                candidates = effects.mapped('bank_journal_id').filtered(
                    lambda journal: journal.company_id == group.company_id and journal.type in ('bank', 'cash') and journal.default_account_id
                )
                if not candidates:
                    candidates = Journal.search([
                        ('company_id', '=', group.company_id.id),
                        ('type', 'in', ('bank', 'cash')),
                        ('default_account_id', '!=', False),
                    ], order='sequence, id')
                journal = candidates[:1]
                if journal:
                    group.with_context(cartera_skip_auto_group_move=True).write({'bank_journal_id': journal.id})
            if not group.bank_journal_id:
                raise UserError(_('Configura un diario bancario/caja con cuenta de liquidez para generar automáticamente el asiento inicial de la agrupación.'))
            group._create_grouping_move()
        return True

    def write(self, vals):
        result = super().write(vals)
        if self.env.context.get('cartera_skip_auto_group_move'):
            return result
        for group in self:
            if 'partner_id' in vals and 'grouping_account_id' not in vals and not group.grouping_account_id and group.partner_id:
                partner_account = group._partner_grouping_account(
                    group.partner_id, group.company_id, group.company_type
                )
                manual_accounts = group.effect_ids.filtered(
                    lambda effect: not effect.is_container and not effect.move_id
                    and not effect.move_line_id and not effect.opening_move_id
                ).mapped('manual_account_id')
                if partner_account and partner_account not in manual_accounts:
                    group.with_context(cartera_skip_auto_group_move=True).write({
                        'grouping_account_id': partner_account.id
                    })
            # Keep the circular/reference on every already-posted grouping entry.
            if 'reference' in vals:
                group.grouping_move_ids.filtered(lambda move: move.state == 'posted').write({
                    'ref': _('Agrupado'),
                })
            # A journal chosen after effects were added is enough to confirm the
            # grouping: the initial reclassification entry is generated here.
            if any(key in vals for key in ('bank_journal_id', 'grouping_account_id', 'reference', 'date', 'due_date', 'effect_ids', 'partner_id', 'company_type')):
                group._ensure_grouping_move()
                group._sync_container_effect()
        return result

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('cartera_number'):
                vals['cartera_number'] = '/'
        records = super().create(vals_list)
        for record in records:
            if not record.grouping_account_id and record.partner_id:
                partner_account = record._partner_grouping_account(
                    record.partner_id, record.company_id, record.company_type
                )
                manual_accounts = record.effect_ids.filtered(
                    lambda effect: not effect.is_container and not effect.move_id
                    and not effect.move_line_id and not effect.opening_move_id
                ).mapped('manual_account_id')
                if partner_account and partner_account not in manual_accounts:
                    record.with_context(cartera_skip_auto_group_move=True).write({
                        'grouping_account_id': partner_account.id
                    })
            # Allocate the portfolio number when the grouping is created,
            # not later when its first effect is added.
            record._assign_cartera_number()
            record._sync_container_effect()
        if any('effect_ids' in vals for vals in vals_list):
            records._ensure_grouping_move()
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
            'bank_journal_id': self.bank_journal_id.id if self.bank_journal_id else False,
            'partner_bank_id': self.partner_bank_id.id if self.partner_bank_id else False,
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
        self._compute_totals()
        if effects and self.currency_id.is_zero(self.amount_pending):
            paid_date = payment_date or fields.Date.context_today(self)
            self.write({'state': 'paid', 'paid_date': paid_date})
            self._reconcile_original_effects()
            # Paid tranches are historical cartera operations and must remain
            # visible/actionable. Only the still-pending continuation is closed.
            pending_helpers = self.portfolio_effect_ids.filtered(
                lambda e: e.is_portfolio_effect and e.active and e.state == 'pending'
            )
            pending_helpers.write({'active': False, 'payment_id': False})
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
        active_portfolio = self.portfolio_effect_ids.filtered(
            lambda e: e.is_portfolio_effect and e.active
        )
        # Paid tranches must remain in the portfolio history. Only pending
        # helper rows represent the current residual and may be resized/closed.
        pending_helpers = active_portfolio.filtered(lambda item: item.state == 'pending')
        if self.currency_id.is_zero(pending) or self.currency_id.compare_amounts(pending, self.amount_total) >= 0:
            # If the latest payment was annulled, the grouping itself is again
            # the pending item. Do not leave a duplicate full-value continuation.
            pending_helpers.write({'active': False, 'payment_id': False})
            return self.env['account.effect']
        helper = pending_helpers[:1]
        vals = {
            'company_id': self.company_id.id,
            'company_type': self.company_type,
            'partner_id': self.partner_id.id if self.partner_id else False,
            'move_id': False, 'move_line_id': False,
            'reference': self.reference or False, 'invoice_reference': False,
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
        (pending_helpers - helper).write({'active': False, 'payment_id': False})
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
            'target': 'main',
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
            'target': 'main',
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
        if self.state != 'draft' or self._has_active_payments():
            raise UserError(_('Solo se pueden añadir efectos a una agrupación pendiente y sin pagos.'))
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
        self._ensure_grouping_move()
        if not self._grouping_move_is_valid():
            raise UserError(_('No se puede saldar: el asiento inicial de la agrupación debe estar publicado y cuadrado con el importe total.'))
        # The grouping has ONE consolidated target line for its selected
        # destination partner. Never look for the original source partner here:
        # that would make a grouping of several customers impossible to settle.
        accounting_lines = self._get_grouping_lines().filtered(
            lambda line: line.account_id == self.grouping_account_id
            and line.partner_id == self.partner_id
            and line.currency_id == effects[:1].currency_id
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
        self._ensure_grouping_move()
        if not self._grouping_move_is_valid():
            raise UserError(_('No se puede saldar: primero debe existir un asiento inicial publicado y cuadrado con el importe de la agrupación.'))
        effects = self.effect_ids.filtered(
            lambda e: not e.is_container and e.state in ('grouped', 'pending', 'remitted')
            and not e.currency_id.is_zero(self._get_effect_pending_amount(e))
        )
        return self._payment_register_action(effects, _('Saldar agrupación'))

    def action_create_remittance(self):
        self.ensure_one()
        if self.company_id != self.env.company:
            raise UserError(_('Activa primero la compañía de la agrupación para crear su remesa. La remesa utilizará la cuenta bancaria de esa compañía.'))
        effects = self.effect_ids.filtered(lambda e: not e.is_container and e.state in ('grouped', 'pending', 'remitted') and not e.remittance_id and not e.currency_id.is_zero(self._get_effect_pending_amount(e)))
        if not effects:
            raise UserError(_('La agrupación no contiene efectos pendientes de remesar.'))

        currencies = effects.mapped('currency_id')
        if len(currencies) > 1:
            raise UserError(_('No se pueden remesar efectos de distintas monedas.'))

        # A remittance represents the company's bank batch, not the
        # customer's/supplier's bank details stored on the grouping.  Let the
        # remittance model select the active company's own partner bank.
        remittance_vals = {
            'company_id': self.company_id.id,
            'company_type': self.company_type,
            'currency_id': self.currency_id.id,
        }
        # Omitting an empty value preserves the model default (first configured
        # bank journal), instead of explicitly clearing it during create().
        if self.bank_journal_id:
            remittance_vals['bank_journal_id'] = self.bank_journal_id.id
        remittance = self.env['account.effect.remittance'].create(remittance_vals)
        self._compute_totals()
        group_state = 'partial' if self.currency_id.compare_amounts(self.amount_pending, self.amount_total) < 0 else 'remitted'
        self.write({'remittance_id': remittance.id, 'state': group_state})
        effects.write({'remittance_id': remittance.id, 'state': 'remitted'})
        self._sync_container_effect()
        remittance._compute_totals()
        remittance._sync_container_effect()
        remittance._ensure_initial_move()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Remesa'),
            'res_model': 'account.effect.remittance',
            'view_mode': 'form',
            'res_id': remittance.id,
            'target': 'main',
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


    def unlink(self):
        for group in self:
            effects = group.effect_ids.filtered(lambda effect: not effect.is_container)
            if effects or group._has_active_payments() or group.all_payment_history_ids:
                raise UserError(_('Solo se puede eliminar una agrupación vacía y sin pagos.'))
            moves = (group.grouping_move_ids | group.grouping_move_id)
            if any(move.state == 'posted' and move.line_ids for move in moves):
                raise UserError(_('No se puede eliminar una agrupación con asientos publicados.'))
            for move in moves:
                if move.state == 'draft':
                    move.button_cancel()
            group.with_context(cartera_skip_auto_group_move=True).write({
                'grouping_move_id': False,
                'grouping_move_ids': [(5, 0, 0)],
            })
        return super().unlink()

    def action_open_accounting_entries(self):
        self.ensure_one()
        move_ids = set(self.all_payment_history_ids.mapped('move_id').ids)
        move_ids.update(self.grouping_move_id.ids)
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

    def action_devolver_portfolio_effect(self, tranche):
        self.ensure_one()
        tranche.ensure_one()
        if not tranche.is_portfolio_effect or tranche.container_group_id != self or tranche.state != 'paid':
            raise UserError(_('Solo se puede devolver una cuota de agrupación que esté saldada.'))
        history = self.env['account.effect.container.payment.history'].search([
            ('portfolio_effect_ids', 'in', tranche.id), ('group_ids', 'in', self.id),
            ('type', '=', 'paid'), ('move_id.state', '=', 'posted'),
        ], order='date desc, id desc', limit=1)
        if not history:
            raise UserError(_('No se ha encontrado el pago original de esta cuota.'))
        if self.env['account.effect.container.payment.history'].search_count([
            ('source_history_id', '=', history.id), ('type', '=', 'returned'),
        ]):
            raise UserError(_('Esta cuota ya se ha devuelto.'))

        allocations = history.allocation_line_ids.filtered(lambda line: line.effect_id.group_id == self)
        if not allocations:
            raise UserError(_('El histórico del pago no contiene el detalle de efectos necesario para devolver esta cuota.'))
        journal = (history.payment_ids | history.payment_id).mapped('journal_id').filtered(
            lambda item: item.company_id == self.company_id and item.type in ('bank', 'cash') and item.default_account_id
        )[:1]
        journal = journal or self.bank_journal_id
        if not journal or journal.company_id != self.company_id or journal.type not in ('bank', 'cash') or not journal.default_account_id:
            raise UserError(_('Configura un diario bancario con cuenta de liquidez para devolver la cuota.'))

        # Aggregate the refund by receivable/payable account and partner while
        # retaining allocation lines per original effect in the audit history.
        buckets = {}
        total_company = 0.0
        for allocation in allocations:
            effect = allocation.effect_id
            account = self.grouping_account_id
            partner = self.partner_id
            if not account or not account.reconcile or not partner:
                raise UserError(_('La agrupación no tiene una cuenta conciliable y un cliente/proveedor de destino configurados.'))
            key = (account.id, partner.id, self.currency_id.id)
            bucket = buckets.setdefault(key, {
                'account': account, 'partner': partner, 'currency': self.currency_id,
                'amount': 0.0, 'effects': self.env['account.effect'],
            })
            bucket['amount'] += allocation.amount
            bucket['effects'] |= effect

        line_values = []
        is_customer = self.company_type == 'customer'
        today = fields.Date.context_today(self)
        for bucket in buckets.values():
            company_amount = bucket['currency']._convert(
                bucket['amount'], self.company_id.currency_id, self.company_id, today, round=True,
            ) if bucket['currency'] != self.company_id.currency_id else bucket['amount']
            total_company += company_amount
            line_values.append((0, 0, {
                'name': _('Devolución · Agrupación nº %s') % self.cartera_number,
                'account_id': bucket['account'].id,
                'partner_id': bucket['partner'].id if bucket['partner'] else False,
                'currency_id': bucket['currency'].id,
                'amount_currency': bucket['amount'] if is_customer else -bucket['amount'],
                'debit': company_amount if is_customer else 0.0,
                'credit': company_amount if not is_customer else 0.0,
                'effect_group_id': self.id,
                'effect_ids': [(6, 0, bucket['effects'].ids)],
            }))
        bank_line = (0, 0, {
            'name': _('Devolución · Agrupación nº %s') % self.cartera_number,
            'account_id': journal.default_account_id.id,
            'debit': 0.0 if is_customer else total_company,
            'credit': total_company if is_customer else 0.0,
        })
        label = _('Devolución de Agrupación nº %s') % self.cartera_number
        return_move_vals = {
            'move_type': 'entry', 'date': today, 'journal_id': journal.id,
            'ref': label, 'effect_group_ids': [(4, self.id)],
            'line_ids': line_values + [bank_line],
        }
        if history.remittance_id:
            return_move_vals['effect_remittance_id'] = history.remittance_id.id
        move = self.env['account.move'].create(return_move_vals)
        move.action_post()
        returned_history = self.env['account.effect.container.payment.history'].create({
            'group_id': self.id,
            'group_ids': [(4, self.id)],
            'remittance_id': history.remittance_id.id if history.remittance_id else False,
            'date': today,
            'reference': label,
            'move_id': move.id,
            'effect_ids': [(6, 0, allocations.mapped('effect_id').ids)],
            'portfolio_effect_ids': [(6, 0, [tranche.id])],
            'source_history_id': history.id,
            'amount': sum(allocations.mapped('amount')),
            'currency_id': self.currency_id.id,
            'type': 'returned',
            'allocation_line_ids': [(0, 0, {'effect_id': line.effect_id.id, 'amount': line.amount}) for line in allocations],
        })
        tranche.write({'state': 'returned', 'paid_date': today, 'payment_id': False})
        # A returned payment reopens the grouping balance, never the individual
        # invoices. Original invoice reconciliations remain as the group's source.
        related_effects = allocations.mapped('effect_id')
        related_effects.filtered(lambda effect: effect.state == 'paid').write({
            'state': 'remitted' if self.remittance_id else 'grouped',
            'paid_date': False,
            'payment_id': False,
        })
        self._compute_totals()
        self._update_payment_state_from_effects(today)
        if history.remittance_id:
            history.remittance_id._compute_totals()
            history.remittance_id._update_payment_state_from_effects(today)
        return {'type': 'ir.actions.client', 'tag': 'reload'}

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
                return custom_history.remittance_id.action_anular_saldado()
            custom_history.move_id._reverse_cartera_payment_entry(note=_('Anulación del pago de agrupación'))
            linked_payments = custom_history.payment_ids | custom_history.payment_id
            if linked_payments:
                linked_payments.with_context(cartera_internal_state_update=True).write({'state': 'canceled'})
            custom_history.portfolio_effect_ids.write({'active': False, 'payment_id': False})
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
        payments = payments.exists().sorted(key=lambda payment: (payment.date or date.min, payment.id))[-1:]
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
