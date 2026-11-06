from datetime import date
from odoo import api, fields, models, _
from odoo.tools.misc import format_date
from odoo.exceptions import UserError


def _default_effect_bank_journal(env):
    journals = env['account.journal'].search([
        ('company_id', '=', env.company.id), ('type', '=', 'bank'),
        ('default_account_id', '!=', False),
    ], order='sequence, id')
    return journals[:1].id


def _default_effect_opening_journal(env):
    return env['account.journal'].search([
        ('company_id', '=', env.company.id), ('type', '=', 'general'),
    ], order='sequence, id', limit=1).id


class AccountEffect(models.Model):
    _name = 'account.effect'
    _description = 'Efecto de cartera'
    _rec_name = 'display_label'
    _order = 'due_date desc, id desc'

    name = fields.Char(string='Nº Efecto', required=True, readonly=True, copy=False, default='/')
    cartera_number = fields.Char(string='Nº Cartera', readonly=True, copy=False, index=True)
    display_label = fields.Char(string='Nombre', compute='_compute_display_labels', store=True)
    display_reference = fields.Char(string='Referencia', compute='_compute_display_labels', store=True)
    display_situation = fields.Char(string='Situación', compute='_compute_display_labels', store=True)
    situation_state = fields.Selection([('pending', 'Pendiente'), ('paid', 'Saldado'), ('returned', 'Devuelto')], string='Situación', compute='_compute_situation_state', store=True)
    container_status_state = fields.Selection([('pending', 'Pendiente'), ('partial', 'Saldada parcialmente'), ('paid', 'Saldada'), ('returned', 'Devuelto')], string='Estado de cartera', compute='_compute_container_status_state', store=False)
    container_editable = fields.Boolean(string='Contenedor editable', compute='_compute_container_controls')
    has_accounting_entries = fields.Boolean(string='Tiene asientos contables', compute='_compute_container_controls')
    has_container_payments = fields.Boolean(string='Tiene pagos de cartera', compute='_compute_container_controls')
    has_manual_payments = fields.Boolean(string='Tiene saldados manuales', compute='_compute_container_controls')
    has_initial_grouping_move = fields.Boolean(string='Tiene asiento inicial', compute='_compute_container_controls')
    has_returnable_effects = fields.Boolean(string='Tiene efectos saldados para devolver', compute='_compute_container_controls')
    situation_ref = fields.Reference(
        selection=[('account.effect.group', 'Agrupación'), ('account.effect.remittance', 'Remesa')],
        string='Situación', compute='_compute_situation_ref', store=False
    )
    invoice_reference = fields.Char(string='Referencia factura', readonly=True)
    company_id = fields.Many2one('res.company', string='Empresa', required=True, readonly=True, default=lambda self: self.env.company)
    partner_id = fields.Many2one('res.partner', string='Empresa')
    grouping_account_id = fields.Many2one(
        'account.account', related='container_group_id.grouping_account_id',
        string='Cuenta de agrupación', readonly=False,
        domain="[('deprecated', '=', False), ('reconcile', '=', True), ('company_ids', 'in', company_id)]",
    )
    manual_category = fields.Selection([('employee_tax', 'Empleados y tributos')], string='Categoría manual', index=True, copy=False)
    manual_account_id = fields.Many2one(
        'account.account', string='Cuenta del efecto',
        domain="[('deprecated', '=', False), ('reconcile', '=', True), ('company_ids', 'in', company_id)]",
        check_company=True, copy=False,
        help='Cuenta contable del apunte de origen vinculado al efecto manual.'
    )
    manual_nature = fields.Selection(
        [('ordinary', 'Ordinaria'), ('exceptional', 'Excepcional')],
        string='Naturaleza del efecto manual', default='ordinary', copy=False,
    )
    beneficiary_name = fields.Char(string='Beneficiario / organismo')
    opening_journal_id = fields.Many2one(
        'account.journal', string='Diario de origen',
        domain="[('company_id', '=', company_id), ('type', '=', 'general')]",
        default=lambda self: _default_effect_opening_journal(self.env),
        copy=False,
    )
    opening_move_id = fields.Many2one(
        'account.move', string='Asiento de origen', readonly=True, copy=False,
        ondelete='restrict',
    )
    company_type = fields.Selection([('customer', 'Cliente'), ('supplier', 'Proveedor')], string='Tipo de empresa', required=True, readonly=True, default=lambda self: 'customer' if self.env.context.get('default_company_type') != 'supplier' else 'supplier')
    move_id = fields.Many2one('account.move', string='Factura', readonly=True, index=True)
    move_line_id = fields.Many2one('account.move.line', string='Apunte contable de origen', ondelete='restrict', index=True, check_company=True)
    reference = fields.Char(string='Concepto')
    invoice_name = fields.Char(string='Nombre factura', related='move_id.name', readonly=True)
    due_date = fields.Date(string='Fecha de vencimiento', required=True, index=True)
    effect_type = fields.Selection([
        ('effect', 'Efecto'),
        ('group', 'Agrupación'),
        ('remittance', 'Remesa'),
    ], string='Tipo de efecto', required=True, default='effect')
    bank_journal_id = fields.Many2one(
        'account.journal', string='Banco', domain="[('type', '=', 'bank')]",
        default=lambda self: _default_effect_bank_journal(self.env),
    )
    partner_bank_id = fields.Many2one('res.partner.bank', string='Cuenta destino')
    payment_direction = fields.Selection([('receive', 'Recibir dinero'), ('send', 'Enviar dinero')], string='Tipo de pago', required=True, default=lambda self: 'receive' if self.env.context.get('default_company_type') != 'supplier' else 'send')
    amount = fields.Monetary(string='Total', required=True)
    currency_id = fields.Many2one('res.currency', required=True, default=lambda self: self.env.company.currency_id)
    amount_pending = fields.Monetary(string='Total pendiente', compute='_compute_amount_pending', currency_field='currency_id', store=True)
    payment_state = fields.Selection([('pending', 'Pendiente'), ('partial', 'Parcial'), ('paid', 'Saldado')], string='Estado del pago', compute='_compute_payment_state', store=True)
    paid_date = fields.Date(string='Fecha de saldado', readonly=True, copy=False)
    display_payment_state = fields.Char(string='Estado del pago', compute='_compute_display_payment_state', store=True)
    state = fields.Selection([('pending', 'Pendiente'), ('grouped', 'Agrupado'), ('remitted', 'Remesado'), ('paid', 'Saldado'), ('returned', 'Devuelto'), ('uncollectible', 'Incobrable')], string='Situación', required=True, default='pending', index=True)
    group_id = fields.Many2one('account.effect.group', string='Agrupación', readonly=True, ondelete='set null')
    remittance_id = fields.Many2one('account.effect.remittance', string='Remesa', readonly=True, ondelete='set null')
    adjustment_move_id = fields.Many2one('account.move', string='Asiento de gastos/comisiones', readonly=True, copy=False)
    payment_id = fields.Many2one('account.payment', string='Pago', readonly=True, copy=False)
    payment_move_id = fields.Many2one('account.move', string='Asiento de pago', related='payment_id.move_id', readonly=True)
    payment_history_ids = fields.One2many('account.effect.payment.history', 'effect_id', string='Histórico pagos', readonly=True)
    situation_history_ids = fields.One2many('account.effect.situation.history', 'effect_id', string='Histórico situaciones', readonly=True)
    portfolio_effect_ids = fields.Many2many('account.effect', compute='_compute_portfolio_effects', string='Efectos de la misma Cartera')
    associated_effect_ids = fields.Many2many('account.effect', compute='_compute_associated_effects', string='Efectos agrupados')
    container_payment_history_ids = fields.Many2many('account.effect.container.payment.history', compute='_compute_container_payment_history', string='Histórico Pagos')
    notes = fields.Text(string='Notas')
    active = fields.Boolean(default=True)
    is_container = fields.Boolean(
        string='Registro de cartera',
        default=False,
        readonly=True,
        copy=False,
        index=True,
    )
    is_portfolio_effect = fields.Boolean(
        string='Efecto de la misma cartera',
        default=False,
        readonly=True,
        copy=False,
        index=True,
    )
    portfolio_chain_id = fields.Many2one(
        'account.effect',
        string='Cartera origen',
        readonly=True,
        copy=False,
        ondelete='cascade',
        index=True,
    )
    container_group_id = fields.Many2one(
        'account.effect.group',
        string='Agrupación representada',
        readonly=True,
        copy=False,
        ondelete='cascade',
    )
    container_remittance_id = fields.Many2one(
        'account.effect.remittance',
        string='Remesa representada',
        readonly=True,
        copy=False,
        ondelete='cascade',
    )

    _sql_constraints = [('move_line_unique', 'unique(move_line_id)', 'Solo puede existir un efecto por vencimiento contable.')]


    @api.depends(
        'is_container', 'move_line_id', 'move_line_id.move_id', 'move_line_id.move_id.state',
        'container_group_id', 'container_group_id.state',
        'container_group_id.grouping_move_id', 'container_group_id.grouping_move_ids.state',
        'container_group_id.effect_ids.state', 'container_remittance_id',
        'container_remittance_id.state', 'container_remittance_id.effect_ids.state',
        'container_remittance_id.payment_history_ids.type',
        'container_remittance_id.payment_history_ids.allocation_line_ids.amount',
        'container_remittance_id.payment_history_ids.allocation_line_ids.effect_id',
        'group_id', 'group_id.state', 'group_id.grouping_move_id', 'group_id.grouping_move_ids.state',
        'remittance_id', 'remittance_id.state', 'remittance_id.effect_ids.state',
        'payment_id', 'payment_id.move_id.state', 'payment_history_ids.move_id.state',
        'payment_history_ids.is_reversed',
        'container_payment_history_ids.type', 'container_payment_history_ids.move_id.state',
        'adjustment_move_id.state', 'payment_move_id.state',
    )
    def _compute_container_controls(self):
        for effect in self:
            group = effect.container_group_id or effect.group_id
            remittance = effect.container_remittance_id or effect.remittance_id
            effect.container_editable = bool(
                (effect.is_container and (
                    (group and group.state == 'draft')
                    or (remittance and remittance.state == 'draft')
                ))
                or (not effect.is_container and effect.state == 'pending'
                    and not effect.group_id and not effect.remittance_id
                    and not effect.payment_id)
            )
            effect.has_initial_grouping_move = bool(
                (group and group._grouping_move_is_valid())
                or (remittance and remittance._initial_move_is_valid())
            )
            histories = effect.container_payment_history_ids
            if remittance:
                histories |= remittance.payment_history_ids
            if group:
                histories |= group.all_payment_history_ids
            moves = effect.payment_move_id | effect.adjustment_move_id | effect.opening_move_id
            if effect.move_line_id:
                moves |= effect.move_line_id.move_id
            moves |= effect.payment_history_ids.mapped('move_id')
            moves |= histories.mapped('move_id')
            if group:
                moves |= group.grouping_move_id | group.grouping_move_ids
            if remittance:
                moves |= remittance.effect_ids.mapped('group_id.grouping_move_id')
                moves |= remittance.effect_ids.mapped('group_id.grouping_move_ids')
                moves |= self.env['account.move'].search([('effect_remittance_id', '=', remittance.id)])
            effect.has_accounting_entries = bool(moves.filtered(lambda move: move and move.state != 'cancel'))
            paid_histories = histories.filtered(lambda history: history.type == 'paid')
            effect.has_container_payments = bool(
                paid_histories.filtered(lambda history: history.move_id and history.move_id.state == 'posted')
                or (effect.payment_id and effect.payment_id.state not in ('draft', 'canceled'))
            )
            effect.has_manual_payments = bool(effect.payment_history_ids.filtered(
                lambda history: history.move_id and history.move_id.state == 'posted' and not history.is_reversed
            ))
            effect.has_returnable_effects = bool(
                remittance and any(
                    remittance.currency_id.compare_amounts(remittance._effect_returnable_amount(item), 0.0) > 0
                    for item in remittance.effect_ids.filtered(lambda child: not child.is_container)
                )
            )

    @api.model
    def _next_cartera_number(self):
        """Allocate a shared sequence number without numbering empty containers.

        The sequence is global across groupings and remittances. Before asking
        ir.sequence for the next number, align it with the highest number that
        already exists in the database (important when upgrading older builds).
        """
        sequence = self.env['ir.sequence'].search([('code', '=', 'account.effect.cartera')], limit=1)
        if not sequence:
            raise UserError(_('No está configurada la secuencia Nº Cartera. Actualiza los datos del módulo.'))
        # This sequence is owned by the cartera module and is global across
        # groups and remittances. Lock it before reading existing numbers so
        # concurrent transactions cannot allocate the same next value.
        self.env.cr.execute('SELECT id FROM ir_sequence WHERE id = %s FOR UPDATE', [sequence.id])
        existing_values = (
            self.env['account.effect.group'].search([('cartera_number', 'not in', (False, '/', ''))]).mapped('cartera_number')
            + self.env['account.effect.remittance'].search([('cartera_number', 'not in', (False, '/', ''))]).mapped('cartera_number')
        )
        numeric_values = []
        for value in existing_values:
            try:
                numeric_values.append(int(value))
            except (TypeError, ValueError):
                continue
        # Re-align on every allocation so an empty/deleted last container does
        # not permanently consume a number.
        minimum_next = max(numeric_values or [0]) + 1
        sequence.invalidate_recordset(['number_next', 'number_next_actual'])
        if int(sequence.number_next_actual or sequence.number_next or 1) != minimum_next:
            sequence.number_next_actual = minimum_next
        return self.env['ir.sequence'].next_by_code('account.effect.cartera') or '/'

    @api.onchange('effect_type')
    def _onchange_effect_type(self):
        for effect in self:
            if effect.effect_type != 'effect':
                effect.move_id = False
                effect.partner_id = False if effect.effect_type == 'remittance' else effect.partner_id
                effect.amount = 0.0
                effect.invoice_reference = False
                effect.reference = False
            if effect.effect_type == 'effect' and not effect.due_date:
                effect.due_date = fields.Date.context_today(self)

    @api.onchange('move_line_id')
    def _onchange_move_line_id(self):
        for effect in self:
            line = effect.move_line_id
            if not line or effect.is_container or effect.is_portfolio_effect:
                continue
            if line.company_id:
                effect.company_id = line.company_id
            effect.manual_account_id = line.account_id
            effect.partner_id = line.partner_id or effect.partner_id
            effect.currency_id = line.currency_id or line.company_id.currency_id
            residual = line.amount_residual_currency if line.currency_id and line.currency_id != line.company_id.currency_id else line.amount_residual
            effect.amount = abs(residual)
            effect.company_type = 'customer' if residual > 0 else 'supplier'
            effect.payment_direction = 'receive' if residual > 0 else 'send'
            effect.due_date = line.date_maturity or line.move_id.invoice_date_due or line.move_id.date
            if not effect.reference:
                effect.reference = line.move_id.ref or line.name or line.move_id.name

    @api.model_create_multi
    def create(self, vals_list):
        records = self.browse()
        effect_vals = []
        for vals in vals_list:
            effect_type = vals.get('effect_type', 'effect')
            is_container = bool(vals.get('is_container'))
            if effect_type != 'effect' and not is_container:
                container_vals = {
                    'company_id': vals.get('company_id') or self.env.company.id,
                    'company_type': vals.get('company_type') or 'customer',
                    'currency_id': vals.get('currency_id') or self.env.company.currency_id.id,
                    'date': vals.get('due_date') or fields.Date.context_today(self),
                    'due_date': vals.get('due_date') or fields.Date.context_today(self),
                    'partner_bank_id': vals.get('partner_bank_id') or False,
                    'payment_direction': vals.get('payment_direction') or ('receive' if (vals.get('company_type') or 'customer') == 'customer' else 'send'),
                    'reference': vals.get('reference') or False,
                    'notes': vals.get('notes') or False,
                    'partner_id': vals.get('partner_id') or False,
                }
                # Preserve the group/remittance model default when the user did
                # not specify a bank; an explicit False would defeat its default.
                if vals.get('bank_journal_id'):
                    container_vals['bank_journal_id'] = vals['bank_journal_id']
                if effect_type == 'group':
                    container = self.env['account.effect.group'].create(container_vals)
                else:
                    container_vals.pop('partner_id', None)
                    container_vals['company_type'] = vals.get('company_type') or False
                    container = self.env['account.effect.remittance'].create(container_vals)
                records |= container.container_effect_id
                continue
            if not is_container and not vals.get('partner_id') and not vals.get('manual_category'):
                raise UserError(_('Indica el cliente o proveedor.'))
            if vals.get('manual_category') == 'employee_tax':
                vals.setdefault('company_type', 'supplier')
                vals.setdefault('payment_direction', 'send')
                vals.setdefault('reference', vals.get('beneficiary_name') or _('Pago manual'))

            # A manual effect is a portfolio-control record linked to an
            # already posted, open accounting item. It must never create an
            # accounting origin entry of its own.
            if (
                not is_container
                and (vals.get('effect_type') or 'effect') == 'effect'
                and not vals.get('move_id')
                and not vals.get('is_portfolio_effect')
                and not vals.get('portfolio_chain_id')
                and not self.env.context.get('cartera_skip_manual_opening')
            ):
                source_id = vals.get('move_line_id')
                if not source_id:
                    raise UserError(_('Para crear un efecto manual, selecciona un apunte contable existente y pendiente.'))
                source = self.env['account.move.line'].browse(source_id).exists()
                company_id = vals.get('company_id') or self.env.company.id
                if not source or source.move_id.state != 'posted' or source.company_id.id != company_id:
                    raise UserError(_('El apunte contable de origen debe estar publicado y pertenecer a la compañía del efecto.'))
                vals.setdefault('company_id', company_id)
                if source.reconciled or not source.account_id.reconcile or source.account_id.deprecated:
                    raise UserError(_('El apunte de origen debe estar abierto y pertenecer a una cuenta que permita conciliación.'))
                if source.partner_id and vals.get('partner_id') and source.partner_id.id != vals.get('partner_id'):
                    raise UserError(_('El tercero del efecto no coincide con el apunte contable de origen.'))
                if source.partner_id and not vals.get('partner_id'):
                    vals['partner_id'] = source.partner_id.id
                source_currency = source.currency_id or source.company_id.currency_id
                effect_currency = self.env['res.currency'].browse(vals.get('currency_id')) if vals.get('currency_id') else source_currency
                vals.setdefault('currency_id', source_currency.id)
                residual = source.amount_residual_currency if source.currency_id and source.currency_id != source.company_id.currency_id else source.amount_residual
                if effect_currency != source_currency:
                    raise UserError(_('La moneda del efecto debe coincidir con la moneda del apunte contable.'))
                amount = vals.get('amount') or 0.0
                if source_currency.compare_amounts(abs(residual), 0.0) <= 0:
                    raise UserError(_('El apunte contable seleccionado no tiene saldo pendiente.'))
                if source_currency.compare_amounts(amount, abs(residual)) != 0:
                    raise UserError(_('El importe del efecto debe coincidir con el saldo pendiente completo del apunte contable. Los pagos parciales se registrarán al saldar el efecto.'))
                duplicate = self.search([('move_line_id', '=', source.id)], limit=1)
                if duplicate:
                    raise UserError(_('El apunte contable ya está vinculado al efecto %s.') % duplicate.display_name)
                vals['manual_account_id'] = source.account_id.id
                vals['company_type'] = 'customer' if residual > 0 else 'supplier'
                vals['payment_direction'] = 'receive' if residual > 0 else 'send'

            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('account.effect') or '/'
            records |= super(AccountEffect, self).create(vals)
        # Invoice effects resolve their invoice maturity line. Manual effects
        # already point to an existing account.move.line; no opening move is
        # generated when they are created.
        for effect in records.filtered(lambda item: not item.is_container and not item.is_portfolio_effect and not item.move_line_id):
            if effect.move_id:
                effect._resolve_invoice_source_line()
        for effect in records:
            effect._log_situation(effect.state, _('Efecto creado'))
        return records

    def _resolve_invoice_source_line(self, force=False):
        """Find and attach the open receivable/payable line for an invoice effect.

        ``force`` is used by grouping when an older effect points to a line that
        has since been reconciled or replaced. It re-evaluates the invoice's
        currently open payment-term lines rather than trusting that stale link.
        """
        self.ensure_one()
        current = self.move_line_id
        if current and not force and not current.reconciled:
            residual = abs(current.amount_residual_currency if current.currency_id and current.currency_id != self.company_id.currency_id else current.amount_residual)
            if not self.currency_id.is_zero(residual):
                return current
        if not self.move_id:
            return current if current and not current.reconciled else self.env['account.move.line']

        account_type = 'asset_receivable' if self.company_type == 'customer' else 'liability_payable'
        candidates = self.move_id.line_ids.filtered(lambda line:
            line.account_id.account_type == account_type
            and not line.reconciled
            and (not self.partner_id or line.partner_id == self.partner_id)
            and not self.company_id.currency_id.is_zero(line.amount_residual)
        )
        if self.due_date:
            due_matches = candidates.filtered(lambda line:
                (line.date_maturity or self.move_id.invoice_date_due or self.move_id.invoice_date) == self.due_date
            )
            if due_matches:
                candidates = due_matches

        expected = self._settlement_pending_amount() or self.amount
        exact = candidates.filtered(lambda line:
            self.currency_id.compare_amounts(
                abs(line.amount_residual_currency if line.currency_id and line.currency_id != self.company_id.currency_id else line.amount_residual),
                expected,
            ) == 0
        )
        if len(exact) == 1:
            source = exact
        elif len(candidates) == 1:
            source = candidates
        else:
            raise UserError(_(
                'El efecto %(effect)s no tiene un vencimiento contable abierto y único en la factura %(invoice)s. '
                'Revisa la fecha, el importe y los vencimientos sin conciliar.'
            ) % {'invoice': self.move_id.display_name, 'effect': self.display_name})

        existing = self.search([('move_line_id', '=', source.id), ('id', '!=', self.id)], limit=1)
        if existing:
            raise UserError(_(
                'El vencimiento %(line)s de la factura %(invoice)s ya está asociado al efecto %(effect)s.'
            ) % {'line': source.display_name, 'invoice': self.move_id.display_name, 'effect': existing.display_name})
        self.with_context(cartera_internal_effect_line=True).write({'move_line_id': source.id})
        return source

    def _ensure_manual_open_item_line(self):
        """Recover the receivable/payable line from an existing manual opening move.

        Older/manual records may retain their opening move while their move_line_id
        relation is empty. Re-link that line before grouping instead of asking the
        user to recreate the effect or posting a duplicate opening entry.
        """
        self.ensure_one()
        if (
            self.move_line_id
            and not self.move_line_id.reconciled
            and self.move_line_id.move_id.state == 'posted'
        ):
            return self.move_line_id
        move = self.opening_move_id
        if not move or move.state != 'posted':
            return self.env['account.move.line']
        candidates = move.line_ids.filtered(lambda line:
            line.effect_id == self
            and not line.reconciled
            and line.account_id.reconcile
            and (not self.partner_id or line.partner_id == self.partner_id)
        )
        if len(candidates) == 1:
            self.with_context(cartera_internal_effect_line=True).write({'move_line_id': candidates.id})
            return candidates
        return self.env['account.move.line']

    def _manual_offset_account(self):
        """Legacy helper used only to maintain opening moves from older versions."""
        self.ensure_one()
        if self.company_type == 'customer':
            code = '778' if self.manual_nature == 'exceptional' else '769'
        else:
            code = '678' if self.manual_nature == 'exceptional' else '669'
        Account = self.env['account.account']
        accounts = Account.search([
            ('code', '=like', code + '%'),
            ('deprecated', '=', False),
            ('company_ids', 'in', self.company_id.id),
        ], order='code, id')
        exact = accounts.filtered(lambda account: account.code == code)[:1]
        account = exact or accounts[:1]
        if not account:
            raise UserError(_(
                'No existe la cuenta %(code)s en el plan contable de %(company)s. ' 
                'Configura esa cuenta antes de crear el efecto manual.'
            ) % {'code': code, 'company': self.company_id.display_name})
        if account.deprecated:
            raise UserError(_('La cuenta automática %s está obsoleta.') % account.display_name)
        return account

    def _create_manual_opening_move(self, force_rebuild=False):
        """Maintain legacy opening moves; new manual effects use an existing item."""
        self.ensure_one()
        if self.is_container or self.is_portfolio_effect or self.move_id:
            return self.opening_move_id
        # A manually selected source line is an existing accounting origin,
        # not a line generated by this effect. Never replace it or manufacture
        # a new 669/769/678/778 entry if that source later changes status.
        if self.move_line_id and self.move_line_id.move_id != self.opening_move_id:
            if self.move_line_id.move_id.state != 'posted' or self.move_line_id.reconciled:
                raise UserError(_('El apunte contable de origen ya no está abierto. No se generará un asiento sustitutorio.'))
            if self.manual_account_id and self.move_line_id.account_id != self.manual_account_id:
                raise UserError(_('La cuenta del efecto ya no coincide con su apunte contable de origen.'))
            return self.opening_move_id

        existing_move = self.opening_move_id
        if not existing_move:
            raise UserError(_('El módulo no genera asientos de origen para efectos manuales. Vincula el efecto a un apunte contable existente y publicado.'))
        if force_rebuild and existing_move:
            if existing_move.state == 'posted':
                if existing_move.line_ids.filtered('reconciled'):
                    raise UserError(_('No se puede modificar el asiento de origen porque ya tiene apuntes conciliados. Anula primero los saldados.'))
                existing_move.button_draft()
            elif existing_move.state == 'cancel':
                existing_move.button_draft()
            elif existing_move.state != 'draft':
                raise UserError(_('El asiento de origen del efecto no se puede actualizar en su estado actual.'))
            self.with_context(cartera_internal_effect_line=True).write({'move_line_id': False})
        else:
            if self.move_line_id and not self.move_line_id.reconciled and self.move_line_id.move_id.state == 'posted':
                return self.opening_move_id
            if self.move_line_id and self.move_line_id.move_id.state != 'posted':
                self.with_context(cartera_internal_effect_line=True).write({'move_line_id': False})
            if self.opening_move_id:
                recovered_line = self._ensure_manual_open_item_line()
                if recovered_line:
                    return self.opening_move_id
                if self.opening_move_id.state == 'posted':
                    raise UserError(_('El asiento de origen del efecto %s existe, pero no contiene una línea abierta recuperable.') % self.display_name)
                if self.opening_move_id.state != 'cancel':
                    raise UserError(_('El asiento de origen del efecto %s no está publicado.') % self.display_name)
                self.with_context(cartera_internal_effect_line=True).write({'opening_move_id': False})
                existing_move = self.env['account.move']

        account = self.manual_account_id
        if not account:
            # Compatibility for legacy records: the open item identifies the
            # balance account, even though the old counterpart field is gone.
            if self.move_line_id:
                account = self.move_line_id.account_id
            elif existing_move:
                candidates = existing_move.line_ids.filtered(
                    lambda line: line.effect_id == self and line.account_id.reconcile
                )
                account = candidates[:1].account_id if len(candidates) == 1 else self.env['account.account']
        if not account:
            raise UserError(_('Selecciona la cuenta de balance del efecto manual.'))
        if account.deprecated or not account.reconcile:
            raise UserError(_('La cuenta %s debe estar activa y permitir conciliación.') % account.display_name)
        if account.company_ids and self.company_id not in account.company_ids:
            raise UserError(_('La cuenta %s no pertenece a la compañía %s.') % (account.display_name, self.company_id.display_name))

        offset = self._manual_offset_account()
        if offset == account:
            raise UserError(_('La cuenta automática %s no puede ser la misma que la cuenta del efecto.') % offset.display_name)
        journal = self.opening_journal_id or self.env['account.journal'].search([
            ('company_id', '=', self.company_id.id), ('type', '=', 'general'),
        ], order='sequence, id', limit=1)
        if not journal or journal.company_id != self.company_id or journal.type != 'general':
            raise UserError(_('Configura un diario de operaciones varias de la misma compañía para el asiento original.'))

        company_currency = self.company_id.currency_id
        accounting_date = existing_move.date if existing_move else fields.Date.context_today(self)
        amount_company = self.currency_id._convert(
            self.amount, company_currency, self.company_id, accounting_date, round=True,
        ) if self.currency_id != company_currency else self.amount
        is_receivable = self.company_type == 'customer'
        # Customer right: debit the selected balance account / credit income.
        # Supplier obligation: debit expense / credit the selected balance account.
        balance_debit = amount_company if is_receivable else 0.0
        balance_credit = 0.0 if is_receivable else amount_company
        balance_currency = self.amount if is_receivable else -self.amount
        offset_debit = 0.0 if is_receivable else amount_company
        offset_credit = amount_company if is_receivable else 0.0
        offset_currency = -self.amount if is_receivable else self.amount
        line_values = [
            (0, 0, {
                'name': self.reference or _('Efecto manual nº %s') % self.name,
                'account_id': account.id,
                'partner_id': self.partner_id.id if self.partner_id else False,
                'currency_id': self.currency_id.id,
                'amount_currency': balance_currency,
                'debit': balance_debit,
                'credit': balance_credit,
                'date_maturity': self.due_date,
                'effect_id': self.id,
            }),
            (0, 0, {
                'name': self.reference or _('Cuenta PGC automática %s') % offset.code,
                'account_id': offset.id,
                'partner_id': self.partner_id.id if self.partner_id else False,
                'currency_id': self.currency_id.id,
                'amount_currency': offset_currency,
                'debit': offset_debit,
                'credit': offset_credit,
            }),
        ]
        move_vals = {
            'move_type': 'entry',
            'date': accounting_date,
            'journal_id': journal.id,
            'ref': _('Efecto manual nº %s') % self.name,
        }
        if existing_move:
            existing_move.write(dict(move_vals, line_ids=[(5, 0, 0)] + line_values))
            move = existing_move
        else:
            move = self.env['account.move'].create(dict(move_vals, line_ids=line_values))
        move.action_post()
        source = move.line_ids.filtered(lambda line: line.effect_id == self)[:1]
        if not source or source.reconciled:
            raise UserError(_('No se ha podido crear un vencimiento contable abierto para el efecto manual.'))
        self.with_context(cartera_internal_effect_line=True).write({
            'opening_move_id': move.id,
            'move_line_id': source.id,
            'manual_account_id': account.id,
        })
        return move

    def write(self, vals):
        if self.env.context.get('cartera_internal_effect_line'):
            return super().write(vals)
        # Internal synchronization updates the portfolio projection, not the
        # grouping/remittance itself. User edits are always propagated while a
        # container is pending; no special edit-mode action/context is needed.
        if self.env.context.get('cartera_sync_container'):
            return super().write(vals)

        vals = dict(vals)
        external_manual_sources = self.filtered(
            lambda effect: not effect.move_id and effect.move_line_id
            and effect.move_line_id.move_id != effect.opening_move_id
            and not effect.is_container and not effect.is_portfolio_effect
        )
        if external_manual_sources:
            if 'move_line_id' in vals:
                raise UserError(_('El apunte contable de origen de un efecto manual no se puede sustituir.'))
            for effect in external_manual_sources:
                source = effect.move_line_id
                if 'manual_account_id' in vals and vals['manual_account_id'] != source.account_id.id:
                    raise UserError(_('La cuenta del efecto debe seguir siendo la cuenta del apunte contable de origen.'))
                if 'partner_id' in vals and source.partner_id and vals['partner_id'] != source.partner_id.id:
                    raise UserError(_('El tercero no puede cambiarse porque el apunte contable de origen ya tiene otro tercero.'))
                if 'company_type' in vals:
                    residual = source.amount_residual_currency if source.currency_id and source.currency_id != source.company_id.currency_id else source.amount_residual
                    expected_type = 'customer' if residual > 0 else 'supplier'
                    if vals['company_type'] != expected_type:
                        raise UserError(_('El tipo de efecto viene determinado por el signo del saldo contable de origen.'))
        manual_source_fields = {
            'manual_account_id', 'manual_nature', 'amount', 'due_date', 'partner_id',
            'company_type', 'currency_id', 'reference', 'opening_journal_id',
        }
        rebuild_manual = bool(manual_source_fields.intersection(vals))
        manual_records = self.filtered(lambda effect: not effect.is_container and not effect.is_portfolio_effect and not effect.move_id and effect.manual_account_id)
        if rebuild_manual:
            if 'manual_account_id' in vals and not vals['manual_account_id'] and manual_records:
                raise UserError(_('Un efecto manual debe conservar una cuenta de balance seleccionada.'))
            for effect in manual_records:
                active_histories = effect.payment_history_ids.filtered(
                    lambda history: history.move_id and history.move_id.state == 'posted' and not history.is_reversed
                )
                if effect.group_id or effect.remittance_id or effect.state != 'pending' or active_histories:
                    raise UserError(_('No se puede cambiar la cuenta, el importe o los datos contables de un efecto manual después de agruparlo, remesarlo o saldarlo.'))
        previous_groups = self.mapped('group_id') if 'group_id' in vals else self.env['account.effect.group']
        for effect in self.filtered('is_container'):
            container_vals = {}
            for field_name in ('due_date', 'reference', 'bank_journal_id', 'partner_bank_id', 'company_type', 'partner_id', 'grouping_account_id'):
                if field_name in vals and (field_name != 'grouping_account_id' or effect.container_group_id):
                    container_vals[field_name] = vals[field_name]
            if not container_vals:
                continue
            if effect.container_group_id:
                group = effect.container_group_id
                if group.state not in ('draft', 'partial'):
                    raise UserError(_('Solo se pueden modificar los datos de una agrupación pendiente o parcialmente saldada.'))
                group.write(container_vals)
            elif effect.container_remittance_id:
                remittance = effect.container_remittance_id
                if remittance.state != 'draft':
                    raise UserError(_('Solo se pueden modificar los datos de una remesa pendiente.'))
                # The partner of a remittance is the company, never a single customer.
                remittance.write({key: value for key, value in container_vals.items() if key != 'partner_id'})
                remittance._compute_totals()
                remittance._sync_container_effect()

            # The container record is a projection of the real business object;
            # its fields are refreshed by _sync_container_effect().
            for field_name in ('due_date', 'reference', 'bank_journal_id', 'partner_bank_id', 'company_type', 'partner_id', 'grouping_account_id'):
                vals.pop(field_name, None)

        result = super().write(vals)

        if rebuild_manual:
            for effect in manual_records.filtered(lambda item: not item.group_id and not item.remittance_id and item.manual_account_id):
                effect._create_manual_opening_move(force_rebuild=bool(effect.opening_move_id))

        # Adding or moving effects into a draft grouping triggers the initial
        # accounting entry automatically when a bank/cash journal is available.
        if 'group_id' in vals:
            new_groups = self.mapped('group_id').filtered(lambda group: group and group.state in ('draft', 'partial', 'remitted'))
            affected_groups = (previous_groups | new_groups).filtered(lambda group: group and group.state in ('draft', 'partial', 'remitted'))
            affected_groups._ensure_grouping_move()
            for group in affected_groups:
                group._compute_totals()
                group._sync_container_effect()
        return result

    @api.depends('portfolio_chain_id', 'portfolio_chain_id.amount', 'portfolio_chain_id.state', 'active', 'container_group_id', 'container_remittance_id')
    def _compute_portfolio_effects(self):
        for effect in self:
            if effect.portfolio_chain_id:
                root = effect.portfolio_chain_id
                effects = (root | self.search([('portfolio_chain_id', '=', root.id), ('active', '=', True)])).exists()
            elif effect.is_container and effect.container_remittance_id:
                effects = effect
            elif effect.is_container and effect.container_group_id:
                effects = self.search([
                    ('container_group_id', '=', effect.container_group_id.id),
                    ('active', '=', True),
                ])
            elif effect.remittance_id:
                effects = effect.remittance_id.container_effect_id or self.browse()
            elif effect.group_id:
                effects = self.search([
                    ('container_group_id', '=', effect.group_id.id),
                    ('active', '=', True),
                ])
            else:
                effects = self.browse()
            effect.portfolio_effect_ids = effects

    def _compute_container_payment_history(self):
        history_model = self.env['account.effect.container.payment.history']
        for effect in self:
            history = history_model
            if effect.is_container and effect.container_remittance_id:
                history |= effect.container_remittance_id.payment_history_ids
            elif effect.is_container and effect.container_group_id:
                history |= effect.container_group_id.all_payment_history_ids
            else:
                if effect.remittance_id:
                    history |= effect.remittance_id.payment_history_ids.filtered(
                        lambda item: effect in item.effect_ids
                    )
                if effect.group_id:
                    history |= effect.group_id.all_payment_history_ids.filtered(
                        lambda item: effect in item.effect_ids
                    )
            effect.container_payment_history_ids = history

    def _compute_associated_effects(self):
        for effect in self:
            if effect.is_container and effect.container_remittance_id:
                effects = effect.container_remittance_id.effect_ids.filtered(lambda e: not e.is_container)
            elif effect.is_container and effect.container_group_id:
                effects = effect.container_group_id.effect_ids.filtered(lambda e: not e.is_container)
            elif effect.remittance_id:
                effects = effect.remittance_id.effect_ids.filtered(lambda e: not e.is_container)
            elif effect.group_id:
                effects = effect.group_id.effect_ids.filtered(lambda e: not e.is_container)
            else:
                effects = self.browse()
            effect.associated_effect_ids = effects

    @api.depends(
        'group_id', 'group_id.cartera_number',
        'remittance_id', 'remittance_id.cartera_number',
        'container_group_id', 'container_group_id.cartera_number',
        'container_remittance_id', 'container_remittance_id.cartera_number',
    )
    def _compute_situation_ref(self):
        for effect in self:
            situation = False
            # Original effects keep their group/remittance link after payment.
            # Partial-payment tranches and residual effects carry the container
            # relation instead, so they must expose the same traceability.
            if effect.remittance_id:
                situation = 'account.effect.remittance,%s' % effect.remittance_id.id
            elif effect.group_id:
                situation = 'account.effect.group,%s' % effect.group_id.id
            elif effect.container_remittance_id:
                situation = 'account.effect.remittance,%s' % effect.container_remittance_id.id
            elif effect.container_group_id:
                situation = 'account.effect.group,%s' % effect.container_group_id.id
            effect.situation_ref = situation

    @api.depends('state', 'is_container', 'group_id', 'group_id.cartera_number', 'group_id.date', 'remittance_id', 'remittance_id.cartera_number', 'remittance_id.date', 'container_group_id.state', 'container_group_id.cartera_number', 'container_remittance_id.state', 'container_remittance_id.cartera_number')
    def _compute_situation_state(self):
        for effect in self:
            if effect.is_container and effect.container_remittance_id:
                effect.situation_state = 'paid' if effect.container_remittance_id.state == 'paid' else 'pending'
            elif effect.is_container and effect.container_group_id:
                effect.situation_state = 'paid' if effect.container_group_id.state == 'paid' else 'pending'
            elif effect.state == 'paid':
                effect.situation_state = 'paid'
            elif effect.state == 'returned':
                effect.situation_state = 'returned'
            else:
                effect.situation_state = 'pending'

    def _compute_container_status_state(self):
        for effect in self:
            if effect.is_container and effect.container_remittance_id:
                state = effect.container_remittance_id.state
                effect.container_status_state = {
                    'draft': 'pending',
                    'partial': 'partial',
                    'paid': 'paid',
                    'cancelled': 'returned',
                }.get(state, 'pending')
            elif effect.is_container and effect.container_group_id:
                state = effect.container_group_id.state
                effect.container_status_state = (
                    'paid' if state == 'paid'
                    else ('partial' if state == 'partial' else ('returned' if state == 'cancelled' else 'pending'))
                )
            else:
                effect.container_status_state = 'paid' if effect.state == 'paid' else ('returned' if effect.state == 'returned' else 'pending')

    @api.depends(
        'reference', 'invoice_reference', 'name', 'group_id.cartera_number', 'group_id.date',
        'remittance_id.cartera_number', 'remittance_id.date', 'remittance_id.state',
        'container_group_id.cartera_number', 'container_group_id.date', 'container_group_id.state',
        'container_group_id.paid_date', 'container_remittance_id.cartera_number',
        'container_remittance_id.date', 'container_remittance_id.state', 'container_remittance_id.paid_date',
        'cartera_number', 'effect_type', 'state', 'paid_date'
    )
    def _compute_display_labels(self):
        for effect in self:
            effect.display_reference = '' if effect.is_container or effect.group_id or effect.remittance_id else (effect.invoice_reference or effect.reference or '')
            if effect.is_container and effect.container_remittance_id:
                remittance = effect.container_remittance_id
                effect.display_label = _('Remesa nº %s') % remittance.cartera_number
                if remittance.state == 'paid':
                    effect.display_situation = _('Cobrado - %s') % (format_date(self.env, remittance.paid_date or remittance.date, date_format='dd/MM/yyyy') if (remittance.paid_date or remittance.date) else '')
                elif remittance.state == 'partial':
                    effect.display_situation = _('Saldado parcialmente - %s') % (format_date(self.env, remittance.paid_date or remittance.date, date_format='dd/MM/yyyy') if (remittance.paid_date or remittance.date) else '')
                else:
                    effect.display_situation = _('Pendiente')
            elif effect.is_container and effect.container_group_id:
                group = effect.container_group_id
                effect.display_label = _('Agrupación nº %s') % group.cartera_number
                situation_date = format_date(self.env, group.paid_date or group.date, date_format='dd/MM/yyyy') if (group.paid_date or group.date) else ''
                if group.state == 'paid':
                    effect.display_situation = _('Saldado - %s') % situation_date
                elif group.state == 'partial':
                    effect.display_situation = _('Saldado parcialmente - %s') % situation_date
                else:
                    effect.display_situation = _('Pendiente')
            else:
                if effect.invoice_reference:
                    effect.display_label = _('Efecto de %s') % effect.invoice_reference
                else:
                    effect.display_label = _('Efecto nº %s') % effect.name
                if effect.state == 'grouped' and effect.group_id:
                    effect.display_situation = _('Agrupado en nº %s - %s') % (effect.group_id.cartera_number, format_date(self.env, effect.group_id.date, date_format='dd/MM/yyyy') if effect.group_id.date else '')
                elif effect.state == 'remitted' and effect.remittance_id:
                    effect.display_situation = _('Remesado en nº %s - %s') % (effect.remittance_id.cartera_number, format_date(self.env, effect.remittance_id.date, date_format='dd/MM/yyyy') if effect.remittance_id.date else '')
                elif effect.state == 'paid':
                    if effect.remittance_id:
                        effect.display_situation = _('Saldado desde remesa - %s') % (format_date(self.env, effect.paid_date, date_format='dd/MM/yyyy') if effect.paid_date else '')
                    else:
                        effect.display_situation = _('Saldado - %s') % (format_date(self.env, effect.paid_date, date_format='dd/MM/yyyy') if effect.paid_date else '')
                elif effect.state == 'returned':
                    effect.display_situation = _('Devuelto')
                else:
                    effect.display_situation = _('Pendiente')

    @api.depends(
        'amount', 'move_line_id.amount_residual', 'move_line_id.amount_residual_currency',
        'move_line_id.currency_id', 'move_line_id.reconciled', 'state', 'is_container',
        'group_id.amount_pending', 'group_id.state', 'group_id.grouping_move_id.state',
        'group_id.payment_history_ids.type',
        'group_id.payment_history_ids.allocation_line_ids.amount',
        'group_id.payment_history_ids.allocation_line_ids.effect_id',
        'remittance_id.amount_pending', 'container_group_id.amount_pending',
        'container_remittance_id.amount_pending',
    )
    def _compute_amount_pending(self):
        for effect in self:
            if effect.is_container and effect.container_remittance_id:
                effect.amount_pending = effect.container_remittance_id.amount_pending
            elif effect.is_container and effect.container_group_id:
                effect.amount_pending = effect.container_group_id.amount_pending
            elif effect.state in ('paid', 'returned', 'uncollectible'):
                effect.amount_pending = 0.0
            elif effect.group_id and effect.group_id.grouping_move_id and effect.group_id.grouping_move_id.state == 'posted':
                # A grouped receivable is settled as one portfolio item. Keep the
                # original invoice/effect amount visible; the grouping itself,
                # its paid tranches and its pending continuation show settlement.
                effect.amount_pending = effect.amount if effect.group_id.state == 'partial' else effect.group_id._get_effect_pending_amount(effect)
            elif effect.move_line_id and not effect.move_line_id.reconciled:
                effect.amount_pending = abs(effect.move_line_id.amount_residual_currency if effect.move_line_id.currency_id and effect.move_line_id.currency_id != effect.company_id.currency_id else effect.move_line_id.amount_residual)
            else:
                effect.amount_pending = effect.amount if effect.active else 0.0

    def _settlement_pending_amount(self):
        self.ensure_one()
        if self.state in ('paid', 'returned', 'uncollectible'):
            return 0.0
        if self.group_id and self.group_id.grouping_move_id and self.group_id.grouping_move_id.state == 'posted':
            return self.group_id._get_effect_pending_amount(self)
        if self.move_line_id:
            if not self.move_line_id.reconciled:
                return abs(self.move_line_id.amount_residual_currency if self.move_line_id.currency_id and self.move_line_id.currency_id != self.company_id.currency_id else self.move_line_id.amount_residual)
            return 0.0
        # Continuation effects and legacy records can have no direct move line.
        if self.active and self.state in ('pending', 'grouped', 'remitted'):
            return self.amount
        return 0.0

    def _cartera_pending_amount(self):
        """Pending amount used by group/remittance selectors, including legacy rows."""
        self.ensure_one()
        amount = self._settlement_pending_amount()
        if self.currency_id and self.currency_id.is_zero(amount) and self.state in ('pending', 'grouped', 'remitted'):
            return self.amount
        return amount

    @api.depends('move_line_id.reconciled', 'move_line_id.amount_residual', 'move_line_id.amount_residual_currency', 'state', 'amount_pending', 'is_container')
    def _compute_payment_state(self):
        for effect in self:
            if effect.is_container:
                effect.payment_state = 'paid' if effect.state == 'paid' or effect.amount_pending <= 0 else 'pending'
            elif effect.state == 'paid':
                effect.payment_state = 'paid'
            elif effect.state in ('grouped', 'remitted') and effect.currency_id.compare_amounts(effect.amount_pending, effect.amount) >= 0:
                effect.payment_state = 'pending'
            elif effect.currency_id.is_zero(effect.amount_pending):
                effect.payment_state = 'paid'
            elif effect.currency_id.compare_amounts(effect.amount_pending, effect.amount) < 0:
                effect.payment_state = 'partial'
            else:
                effect.payment_state = 'pending'

    @api.depends(
        'payment_state', 'paid_date', 'state',
        'container_group_id.state', 'container_remittance_id.state',
    )
    def _compute_display_payment_state(self):
        for effect in self:
            if effect.is_container:
                if effect.container_remittance_id:
                    r = effect.container_remittance_id
                    effect.display_payment_state = _('Saldado') if r.state == 'paid' else (_('Saldado parcial') if r.state == 'partial' else _('Pendiente'))
                elif effect.container_group_id:
                    group_state = effect.container_group_id.state
                    effect.display_payment_state = (
                        _('Saldado') if group_state == 'paid'
                        else (_('Saldado parcial') if group_state == 'partial' else _('Pendiente'))
                    )
                else:
                    effect.display_payment_state = _('Saldado') if effect.state == 'paid' else _('Pendiente')
            elif effect.state == 'grouped':
                effect.display_payment_state = _('Agrupado')
            elif effect.state == 'remitted':
                effect.display_payment_state = _('Remesado')
            elif effect.state == 'paid':
                effect.display_payment_state = _('Saldado')
            elif effect.state == 'returned':
                effect.display_payment_state = _('Devuelto')
            else:
                effect.display_payment_state = _('Pendiente')

    def _log_situation(self, state, note=None):
        normalized = 'paid' if state == 'paid' else ('returned' if state == 'returned' else 'pending')
        self.env['account.effect.situation.history'].create([{'effect_id': e.id, 'state': normalized, 'note': note} for e in self])

    def _set_state(self, state, note=None):
        self.write({'state': state})
        self._log_situation(state, note)

    def _ensure_same_currency(self, effects):
        if len(effects.mapped('currency_id')) > 1:
            raise UserError(_('No se pueden mezclar efectos de distintas monedas en una misma agrupación o remesa.'))

    def _validate_selection(self, effects, allowed_states):
        effects = effects.filtered(lambda e: not e.is_container and e.state in allowed_states and not e.remittance_id and not e.is_portfolio_effect)
        if not effects:
            raise UserError(_('Selecciona efectos válidos para esta operación.'))
        companies = effects.mapped('company_id')
        types = set(effects.mapped('company_type'))
        if len(companies) > 1 or len(types) > 1:
            raise UserError(_('No se pueden mezclar compañías o tipos de empresa distintos.'))
        self._ensure_same_currency(effects)
        return effects

    def action_group_selected(self):
        effects = self._validate_selection(self, ('pending',))
        company = effects.mapped('company_id')[:1]
        company_type = next(iter(set(effects.mapped('company_type'))))
        partners = effects.mapped('partner_id')
        currency = effects.mapped('currency_id')[:1]
        journals = effects.mapped('bank_journal_id')
        group_vals = {
            'company_id': company.id,
            'company_type': company_type,
            'partner_id': partners.id if len(partners) == 1 else False,
            'currency_id': currency.id,
        }
        if len(journals) == 1:
            group_vals['bank_journal_id'] = journals.id
        # Prefer the actual source balance account when all selected effects
        # use the same one. Otherwise use a shared partner property as a
        # default; if there is no unambiguous account, the group form lets the
        # user select it from the installed chart of accounts.
        source_accounts = effects.mapped('move_line_id.account_id')
        if len(source_accounts) == 1:
            group_vals['grouping_account_id'] = source_accounts.id
        else:
            partner_account = self.env['account.effect.group']._partner_grouping_account(
                partners, company, company_type
            )
            if partner_account:
                group_vals['grouping_account_id'] = partner_account.id
        group = self.env['account.effect.group'].create(group_vals)
        group._assign_cartera_number()
        effects.write({'group_id': group.id, 'cartera_number': group.cartera_number})
        group._compute_totals()
        group._sync_container_effect()
        effects._set_state('grouped', _('Agrupación %s') % group.name)
        if group.grouping_account_id and group.partner_id:
            group._ensure_grouping_move()
        if group.grouping_account_id and group.partner_id and not group._grouping_move_is_valid():
            raise UserError(_(
                'No se ha podido crear el asiento inicial de la agrupación. '
                'Comprueba que todos los efectos conservan un vencimiento contable abierto, '
                'que hay un diario bancario/caja válido y que el asiento cuadra con el total.'
            ))
        # Use the same portfolio projection as the menu/list actions to avoid
        # mixing two forms and creating duplicate breadcrumbs.
        return group.action_open_effect()

    def action_create_remittance_selected(self):
        effects = self._validate_selection(self, ('pending', 'grouped'))
        company = effects.mapped('company_id')[:1]
        if company != self.env.company:
            raise UserError(_('Activa primero la compañía de los efectos para crear la remesa. La compañía de la remesa será siempre la compañía activa.'))
        company_type = next(iter(set(effects.mapped('company_type'))))
        currency = effects.mapped('currency_id')[:1]
        journals = effects.mapped('bank_journal_id')
        remittance_vals = {
            'company_id': company.id,
            'company_type': company_type,
            'currency_id': currency.id,
        }
        if len(journals) == 1:
            remittance_vals['bank_journal_id'] = journals.id
        remittance = self.env['account.effect.remittance'].create(remittance_vals)
        remittance._assign_cartera_number()
        groups = effects.mapped('group_id')
        if groups:
            for group in groups:
                group._compute_totals()
                group_state = 'partial' if group.currency_id.compare_amounts(group.amount_pending, group.amount_total) < 0 else 'remitted'
                group.write({'remittance_id': remittance.id, 'state': group_state})
                group._sync_container_effect()
        effects.write({'remittance_id': remittance.id, 'cartera_number': remittance.cartera_number})
        effects._set_state('remitted', _('Remesa %s') % remittance.name)
        remittance._compute_totals()
        container_effect = remittance._sync_container_effect()
        # Create the initial remittance transfer entry at the same time the
        # remittance is saved; subsequent draft changes rebuild this same move.
        remittance._ensure_initial_move()
        if not remittance._initial_move_is_valid():
            raise UserError(_('No se han podido añadir los efectos: el asiento inicial de la remesa no está publicado y cuadrado. Comprueba el diario y los vencimientos contables.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Remesa %s') % remittance.cartera_number,
            'res_model': 'account.effect',
            'view_mode': 'form',
            'res_id': container_effect.id,
        }

    def action_generate_grouping_move(self):
        self.ensure_one()
        if not self.is_container or not self.container_group_id:
            raise UserError(_('Este registro no representa una agrupación.'))
        return self.container_group_id.action_generate_grouping_move()

    def action_add_pending_effects(self):
        self.ensure_one()
        if self.container_remittance_id:
            return self.container_remittance_id.action_add_pending_effects()
        if self.container_group_id:
            return self.container_group_id.action_add_pending_effects()
        raise UserError(_('Este registro no representa una agrupación o remesa.'))

    def action_saldar_entero(self):
        self.ensure_one()
        if self.container_remittance_id:
            return self.container_remittance_id.action_saldar_entero()
        if self.container_group_id:
            return self.container_group_id.action_saldar()
        return self.action_saldar()

    def action_saldar_parcial(self):
        self.ensure_one()
        if self.container_remittance_id:
            return self.container_remittance_id.action_saldar_parcial()
        if self.container_group_id:
            raise UserError(_('Las agrupaciones se saldan desde Saldar (entero), modificando el importe si es necesario.'))
        raise UserError(_('Este efecto no pertenece a una agrupación o remesa.'))

    def action_devolver_efectos(self):
        self.ensure_one()
        if self.container_remittance_id:
            return self.container_remittance_id.action_devolver_efectos()
        raise UserError(_('La devolución de varios efectos solo está disponible desde una remesa.'))

    def action_saldar(self):
        self.ensure_one()
        if self.is_container:
            if self.container_group_id:
                return self.container_group_id.action_saldar()
            if self.container_remittance_id:
                return self.container_remittance_id.action_saldar_entero()
            raise UserError(_('Este registro de cartera no tiene un contenedor asociado.'))
        if self.group_id:
            return self.group_id.action_saldar()
        if self.remittance_id:
            return self.remittance_id.action_saldar_parcial()
        if self.manual_account_id and (not self.move_id or self.move_id.move_type == 'entry'):
            return self._manual_payment_wizard_action()
        if self.portfolio_chain_id and not self.move_line_id:
            root = self.portfolio_chain_id
            if root.move_line_id and not root.move_line_id.reconciled:
                return {
                    'name': _('Saldar'),
                    'type': 'ir.actions.act_window',
                    'res_model': 'account.payment.register',
                    'view_mode': 'form',
                    'target': 'new',
                    'context': {
                        'active_model': 'account.move.line',
                        'active_ids': [root.move_line_id.id],
                        'effect_id': root.id,
                        'cartera_effect_ids': [root.id],
                        'cartera_amount_editable': True,
                        'cartera_effect_amount_override': self.amount,
                        'cartera_portfolio_child_id': self.id,
                    },
                }
            # Manual effects have no invoice due line. Their residuals are
            # standalone effects too, so send them through the same native
            # account.payment wizard rather than hiding/denying Saldar.
            return self._manual_payment_wizard_action()
        if self.state in ('returned', 'uncollectible'):
            raise UserError(_('Este efecto no tiene un vencimiento contable pendiente de pago.'))
        if not self.move_line_id:
            return self._manual_payment_wizard_action()
        if self.move_line_id.reconciled:
            raise UserError(_('Este efecto no tiene un vencimiento contable pendiente de pago.'))
        return {'name': _('Saldar'), 'type': 'ir.actions.act_window', 'res_model': 'account.payment.register', 'view_mode': 'form', 'target': 'new', 'context': {'active_model': 'account.move.line', 'active_ids': [self.move_line_id.id], 'effect_id': self.id, 'cartera_effect_ids': [self.id], 'cartera_amount_editable': True}}

    def _manual_payment_wizard_action(self):
        self.ensure_one()
        if not self.manual_account_id and not self.move_line_id:
            raise UserError(_('El efecto manual no tiene una cuenta de balance conciliable.'))
        return {
            'name': _('Saldar efecto'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.effect.manual.payment.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_effect_id': self.id},
        }

    def action_register_payment(self):
        return self.action_saldar()

    def action_open_container(self):
        self.ensure_one()
        # A paid/remaining tranche created by a partial group settlement is a
        # child of the grouping. Open the grouping portfolio itself, not the
        # synthetic tranche as a standalone effect.
        if self.is_portfolio_effect and self.container_group_id:
            return self.container_group_id.action_open_effect()
        if self.container_remittance_id:
            # Always open the remittance's portfolio effect. This keeps the
            # same effect-centric form regardless of where the remittance is
            # opened from (main list, grouped effect, or remittance action).
            return {
                'type': 'ir.actions.act_window',
                'name': _('Remesa %s') % self.container_remittance_id.cartera_number,
                'res_model': 'account.effect',
                'view_mode': 'form',
                'res_id': self.id,
            }
        if self.container_group_id:
            effect = self.container_group_id._sync_container_effect()
            return {
                'type': 'ir.actions.act_window',
                'name': _('Agrupación %s') % self.container_group_id.cartera_number,
                'res_model': 'account.effect',
                'view_mode': 'form',
                'views': [(self.env.ref('l10n_es_effects.view_account_effect_form').id, 'form')],
                'res_id': effect.id,
            }
        return False

    @api.model
    def _sync_container_effects(self):
        # Recompute stored portfolio balances so records created by older V3
        # test versions are normalized when the main cartera is opened.
        effects = self.search([])
        effects._compute_amount_pending()
        effects._compute_payment_state()
        effects.flush_recordset(['amount_pending', 'payment_state'])
        groups = self.env['account.effect.group'].search([])
        remittances = self.env['account.effect.remittance'].search([])
        for group in groups:
            group._compute_totals()
            group._sync_container_effect()
        for remittance in remittances:
            remittance._compute_totals()
            remittance._sync_container_effect()
        return True

    @api.model
    def action_open_manual_effects(self):
        self._sync_container_effects()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Efectos de empleados y tributos'),
            'res_model': 'account.effect',
            'view_mode': 'list,form',
            'views': [(self.env.ref('l10n_es_effects.view_account_effect_list').id, 'list'), (False, 'form')],
            'domain': [('manual_category', '=', 'employee_tax')],
            'context': {'default_company_type': 'supplier', 'default_effect_type': 'effect', 'default_manual_category': 'employee_tax', 'default_payment_direction': 'send', 'cartera_new_mode': True},
        }

    def action_open_effects(self, company_type):
        self._sync_container_effects()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Efectos de clientes') if company_type == 'customer' else _('Efectos de proveedores'),
            'res_model': 'account.effect',
            'view_mode': 'list,form',
            'views': [
                (self.env.ref('l10n_es_effects.view_account_effect_list').id, 'list'),
                (False, 'form'),
            ],
            'domain': [('company_type', '=', company_type)],
            'context': {'default_company_type': company_type, 'default_effect_type': 'effect'},
        }

    def action_open_invoice(self):
        self.ensure_one()
        if not self.move_id:
            raise UserError(_('Este efecto no está asociado a una factura.'))
        return {'type': 'ir.actions.act_window', 'name': _('Factura'), 'res_model': 'account.move', 'view_mode': 'form', 'res_id': self.move_id.id}


    def action_open_payment(self):
        self.ensure_one()
        if not self.payment_id:
            raise UserError(_('Este efecto no tiene un pago de Odoo asociado.'))
        return self.payment_id.action_open_business_doc()

    def action_open_accounting_entries(self):
        self.ensure_one()
        move_ids = set(self.payment_move_id.ids)
        move_ids.update(self.opening_move_id.ids)
        if self.move_line_id:
            move_ids.add(self.move_line_id.move_id.id)
        move_ids.update(self.payment_history_ids.mapped('payment_id.move_id').ids)
        move_ids.update(self.payment_history_ids.mapped('move_id').ids)
        move_ids.update(self.container_payment_history_ids.mapped('move_id').ids)
        move_ids.update(self.container_group_id.grouping_move_id.ids)
        move_ids.update(self.container_group_id.grouping_move_ids.ids)
        move_ids.update(self.group_id.grouping_move_id.ids)
        move_ids.update(self.group_id.grouping_move_ids.ids)
        move_ids.update(self.container_remittance_id.effect_ids.mapped('group_id.grouping_move_ids').ids)
        if self.adjustment_move_id:
            move_ids.add(self.adjustment_move_id.id)
        if not move_ids:
            raise UserError(_('No hay asientos contables asociados a este efecto.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Asientos contables'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', list(move_ids))],
            'context': {'create': False},
        }

    def _latest_payment_for_effects(self, effects):
        payments = effects.mapped('payment_id').filtered(lambda p: p)
        return payments.sorted(key=lambda p: (p.date or date.min, p.id), reverse=True)[:1]

    def action_anular_saldado(self):
        self.ensure_one()
        if self.is_container:
            if self.container_group_id:
                return self.container_group_id.action_anular_saldado()
            if self.container_remittance_id:
                return self.container_remittance_id.action_anular_saldado()
        if self.is_portfolio_effect and self.container_group_id:
            history = self.env['account.effect.container.payment.history'].search([
                ('portfolio_effect_ids', 'in', self.id), ('type', '=', 'paid'),
                ('move_id.state', '=', 'posted'),
            ], order='date desc, id desc', limit=1)
            if history and history.remittance_id:
                latest = history.remittance_id.payment_history_ids.filtered(
                    lambda item: item.type == 'paid' and item.move_id and item.move_id.state == 'posted'
                ).sorted(key=lambda item: (item.date or date.min, item.id))[-1:]
                if not latest or latest[0] != history:
                    raise UserError(_('Solo se puede anular el último saldado de la remesa. Anula primero los pagos posteriores.'))
                return history.remittance_id.action_anular_saldado()
            if history and history.group_id:
                latest = history.group_id.all_payment_history_ids.filtered(
                    lambda item: item.type == 'paid' and item.move_id and item.move_id.state == 'posted'
                ).sorted(key=lambda item: (item.date or date.min, item.id))[-1:]
                if not latest or latest[0] != history:
                    raise UserError(_('Solo se puede anular el último saldado de la agrupación. Anula primero los pagos posteriores.'))
                return history.group_id.action_anular_saldado()
        if self.payment_id and self.payment_id.cartera_consolidated:
            history = self.payment_id.cartera_container_history_id
            if history and history.remittance_id:
                return history.remittance_id.action_anular_saldado()
            if history and history.group_id:
                return history.group_id.action_anular_saldado()
        # Consolidated cartera settlements are represented by a journal entry,
        # not by one account.payment per individual effect. Delegate annulment
        # to the container so the entire shared bank operation is reversed.
        if not self.payment_id and self.remittance_id:
            return self.remittance_id.action_anular_saldado()
        if not self.payment_id and self.group_id:
            return self.group_id.action_anular_saldado()
        if self.state != 'paid' and not self.has_manual_payments:
            raise UserError(_('Solo se puede anular un efecto saldado.'))
        if not self.payment_id:
            histories = self.payment_history_ids.filtered(
                lambda history: history.move_id and history.move_id.state == 'posted' and not history.is_reversed
            ).sorted(key=lambda history: history.id, reverse=True)
            if histories:
                history = histories[0]
                reversal = history.move_id._reverse_cartera_payment_entry(
                    reversal_date=fields.Date.context_today(self), note=_('Anulación de saldado manual')
                )
                history.write({'is_reversed': True, 'reversal_move_id': reversal.id, 'note': _('Saldado anulado mediante %s') % reversal.name})
                restore_state = 'remitted' if self.remittance_id else ('grouped' if self.group_id else 'pending')
                self.write({'state': restore_state, 'paid_date': False})
                self._log_situation(restore_state, _('Saldado manual anulado · %s') % reversal.name)
                return {'type': 'ir.actions.client', 'tag': 'reload'}
            raise UserError(_('No se ha encontrado un asiento de saldado manual pendiente de anulación.'))
        payment = self._latest_payment_for_effects(self)
        if not payment:
            raise UserError(_('No se ha encontrado el pago de Odoo asociado al efecto.'))
        related = self.search([('payment_id', '=', payment.id), ('is_container', '=', False)])
        chain_children = self.search([('portfolio_chain_id', 'in', related.ids), ('active', '=', True)]) if related else self.browse()
        downstream_paid = chain_children.filtered(
            lambda child: child.payment_id and child.payment_id.state not in ('draft', 'canceled')
        )
        if downstream_paid:
            raise UserError(_(
                'Este efecto tiene pagos posteriores aplicados a un efecto residual. '
                'Anula primero el último pago de la cadena y después vuelve a intentarlo.'
            ))
        if payment.state not in ('draft', 'canceled'):
            payment.action_cancel()
        if chain_children:
            chain_children.write({'active': False})
        for effect in related:
            restore_state = 'remitted' if effect.remittance_id else ('grouped' if effect.group_id else 'pending')
            # Individual partial payments split the original amount between
            # the settled record and one active continuation. Recombine them
            # when the payment is annulled, otherwise the original amount is
            # permanently truncated in the portfolio.
            restored_amount = effect.amount + sum(
                child.amount for child in chain_children.filtered(lambda item: item.portfolio_chain_id == effect)
            )
            effect.write({
                'amount': restored_amount,
                'state': restore_state,
                'paid_date': False,
                'payment_id': False,
            })
            effect.move_line_id.invalidate_recordset(['amount_residual', 'amount_residual_currency', 'reconciled']) if effect.move_line_id else None
            effect._compute_amount_pending()
            effect._compute_payment_state()
            effect._log_situation(restore_state, _('Saldado anulado · Pago %s') % payment.display_name)
        for child in chain_children:
            child.write({'active': False, 'payment_id': False})
        for group in related.mapped('group_id'):
            group._update_payment_state_from_effects()
        for remittance in related.mapped('remittance_id'):
            remittance._update_payment_state_from_effects()
        return True

    def action_devolver(self):
        self.ensure_one()
        if self.is_portfolio_effect and self.container_group_id:
            return self.container_group_id.action_devolver_portfolio_effect(self)
        if self.is_container:
            raise UserError(_('La devolución debe realizarse desde un efecto individual.'))
        if self.state != 'paid':
            raise UserError(_('Solo se puede devolver un efecto saldado.'))
        today = fields.Date.context_today(self)
        original_payment = self.payment_id
        original_move_line = self.move_line_id
        if not original_payment:
            joint_history = self.env['account.effect.container.payment.history'].search([
                ('effect_ids', 'in', self.id),
                ('type', '=', 'paid'),
                ('move_id.state', '=', 'posted'),
            ], order='date desc, id desc', limit=1)
            if joint_history:
                raise UserError(_(
                    'Este efecto se liquidó dentro de un asiento conjunto de agrupación o remesa. '
                    'No puede devolverse de forma aislada porque afectaría al saldo compartido. '
                    'Anula primero el último pago desde la agrupación o remesa.'
                ))
        # A returned effect must put the accounting due line back in an unpaid
        # state before the new pending effect takes ownership of it.
        if original_payment and original_payment.state not in ('draft', 'canceled'):
            original_payment.action_cancel()
        vals = {
            'company_id': self.company_id.id,
            'company_type': self.company_type,
            'partner_id': self.partner_id.id,
            'manual_account_id': self.manual_account_id.id if self.manual_account_id else False,
            'manual_nature': self.manual_nature or 'ordinary',
            'move_id': self.move_id.id if self.move_id else False,
            'move_line_id': original_move_line.id if original_move_line else False,
            'reference': _('Devuelto de efecto de %s') % self.name,
            'invoice_reference': self.invoice_reference,
            'due_date': today,
            'effect_type': 'effect',
            'bank_journal_id': self.bank_journal_id.id if self.bank_journal_id else False,
            'partner_bank_id': self.partner_bank_id.id if self.partner_bank_id else False,
            'payment_direction': self.payment_direction,
            'amount': self.amount,
            'currency_id': self.currency_id.id,
            'state': 'pending',
            'active': True,
        }
        # The original effect remains as historical returned evidence; the new
        # pending effect becomes the sole owner of the accounting due line.
        self.write({'state': 'returned', 'payment_id': False, 'move_line_id': False})
        returned = self.env['account.effect'].create(vals)
        self._log_situation('returned', _('Efecto devuelto'))
        returned._log_situation('pending', _('Nuevo efecto pendiente tras devolución de %s') % self.name)
        if original_payment:
            history_vals = {
                'effect_id': self.id,
                'date': today,
                'payment_id': original_payment.id,
                'journal_id': original_payment.journal_id.id,
                'amount': self.amount,
                'note': _('Devolución de efecto'),
            }
            self.env['account.effect.payment.history'].create(history_vals)
            if self.group_id:
                self.env['account.effect.container.payment.history'].create({
                    'group_id': self.group_id.id,
                    'payment_id': original_payment.id,
                    'reference': original_payment.name or self.name,
                    'move_id': original_payment.move_id.id if original_payment.move_id else False,
                    'date': today,
                    'effect_ids': [(6, 0, [self.id])],
                    'amount': self.amount,
                    'currency_id': self.currency_id.id,
                    'type': 'returned',
                })
            if self.remittance_id:
                self.env['account.effect.container.payment.history'].create({
                    'remittance_id': self.remittance_id.id,
                    'payment_id': original_payment.id,
                    'reference': original_payment.name or self.name,
                    'move_id': original_payment.move_id.id if original_payment.move_id else False,
                    'date': today,
                    'effect_ids': [(6, 0, [self.id])],
                    'amount': self.amount,
                    'currency_id': self.currency_id.id,
                    'type': 'returned',
                })
        if self.group_id:
            self.group_id._update_payment_state_from_effects(today)
        if self.remittance_id:
            self.remittance_id._update_payment_state_from_effects(today)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Efecto devuelto'),
            'res_model': 'account.effect',
            'view_mode': 'form',
            'res_id': returned.id,
        }

    def action_edit_container(self):
        self.ensure_one()
        if not self.is_container:
            raise UserError(_('Solo se puede editar una agrupación o remesa desde su efecto de cartera.'))
        if self.container_remittance_id:
            if self.container_remittance_id.state != 'draft':
                raise UserError(_('Solo se puede editar una remesa pendiente.'))
        elif self.container_group_id:
            if self.container_group_id.state not in ('draft', 'partial'):
                raise UserError(_('Solo se puede editar una agrupación pendiente o parcialmente saldada.'))
        else:
            raise UserError(_('Este efecto no está vinculado a una agrupación o remesa.'))
        action = {
            'type': 'ir.actions.act_window',
            'name': self.display_label,
            'res_model': 'account.effect',
            'view_mode': 'form',
            'views': [(self.env.ref('l10n_es_effects.view_account_effect_form').id, 'form')],
            'res_id': self.id,
            'target': 'current',
            'context': dict(self.env.context, cartera_edit_mode=False),
        }
        return action

    def action_finish_container_edit(self):
        # Kept for compatibility with databases that still have the old button
        # cached in the client. It no longer opens the same form a second time.
        self.ensure_one()
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_add_selected_to_group(self):
        group_id = self.env.context.get('group_id')
        if not group_id:
            raise UserError(_('No se ha indicado la agrupación de destino.'))
        group = self.env['account.effect.group'].browse(group_id).exists()
        if not group:
            raise UserError(_('No se ha encontrado la agrupación.'))
        if group.state != 'draft' or group._has_active_payments():
            raise UserError(_('Solo se puede editar una agrupación pendiente.'))
        selected = self.filtered(lambda e: not e.is_container and not e.is_portfolio_effect and e.state == 'pending' and not e.group_id and not e.remittance_id)
        if not selected:
            raise UserError(_('Selecciona al menos un efecto pendiente.'))
        if any(e.company_id != group.company_id for e in selected):
            raise UserError(_('No se pueden mezclar compañías.'))
        if any(e.currency_id != group.currency_id for e in selected):
            raise UserError(_('No se pueden mezclar monedas.'))
        if any(e.company_type != group.company_type for e in selected):
            raise UserError(_('No se pueden mezclar clientes y proveedores en una misma agrupación.'))
        group._assign_cartera_number()
        selected.write({
            'group_id': group.id,
            'remittance_id': False,
            'cartera_number': group.cartera_number,
            'state': 'grouped',
        })
        group._compute_totals()
        group._sync_container_effect()
        if not group.partner_id:
            unique_partners = group.effect_ids.filtered(lambda item: not item.is_container).mapped('partner_id')
            if len(unique_partners) == 1:
                group.write({'partner_id': unique_partners.id})
        if group.partner_id:
            group._ensure_grouping_move()
            # If neither the source account nor the partner property gives an
            # unambiguous grouping account, leave the effects attached so the
            # user can choose the account on the grouping form.
            if group.grouping_account_id and not group._grouping_move_is_valid():
                raise UserError(_('No se han podido agrupar los efectos: el asiento inicial no está publicado y cuadrado. Comprueba el cliente/proveedor de destino, la cuenta de agrupación, el diario y los vencimientos contables abiertos.'))
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_add_selected_to_remittance(self):
        remittance_id = self.env.context.get('remittance_id')
        if not remittance_id:
            raise UserError(_('No se ha indicado la remesa de destino.'))
        remittance = self.env['account.effect.remittance'].browse(remittance_id).exists()
        if not remittance:
            raise UserError(_('No se ha encontrado la remesa.'))
        if remittance.company_id != self.env.company:
            raise UserError(_('Activa la compañía de la remesa antes de añadir efectos.'))
        if remittance.state != 'draft' or remittance._has_active_payments():
            raise UserError(_('Solo se pueden añadir efectos a una remesa pendiente y sin pagos.'))

        selected = self.filtered(lambda e: not e.remittance_id and (
            (not e.is_container and not e.is_portfolio_effect and e.state == 'pending')
            or (e.is_container and e.effect_type == 'group' and e.container_group_id and e.container_group_id.state == 'draft')
        ))
        if not selected:
            raise UserError(_('Selecciona al menos un efecto pendiente o una agrupación pendiente.'))

        direct_effects = selected.filtered(lambda e: not e.is_container)
        group_containers = selected.filtered(lambda e: e.is_container and e.container_group_id)
        group_effects = group_containers.mapped('container_group_id.effect_ids').filtered(
            lambda e: not e.is_container and e.state in ('pending', 'grouped') and not e.remittance_id
            and not e.currency_id.is_zero(e._settlement_pending_amount())
        )
        effects = (direct_effects | group_effects).exists()
        if not effects:
            raise UserError(_('No hay efectos pendientes disponibles para añadir a la remesa.'))
        if any(e.company_id != remittance.company_id for e in effects):
            raise UserError(_('No se pueden mezclar compañías.'))
        if len(effects.mapped('currency_id')) > 1 or any(e.currency_id != remittance.currency_id for e in effects):
            raise UserError(_('No se pueden mezclar monedas.'))
        types = set(effects.mapped('company_type'))
        if remittance.company_type and types and types != {remittance.company_type}:
            raise UserError(_('No se pueden mezclar clientes y proveedores en una misma remesa.'))
        if types:
            remittance.company_type = next(iter(types))

        effects.write({
            'remittance_id': remittance.id,
            'cartera_number': remittance.cartera_number,
            'state': 'remitted',
        })
        groups = effects.mapped('group_id') | group_containers.mapped('container_group_id')
        candidate_journals = effects.mapped('bank_journal_id') | groups.mapped('bank_journal_id')
        if not remittance.bank_journal_id and len(candidate_journals) == 1:
            remittance.bank_journal_id = candidate_journals.id
        for group in groups:
            values = {'remittance_id': remittance.id, 'state': 'remitted'}
            if not group.bank_journal_id and remittance.bank_journal_id:
                values['bank_journal_id'] = remittance.bank_journal_id.id
            group.write(values)
            group._ensure_grouping_move()
            if group.effect_ids.filtered(lambda child: not child.is_container) and not group.grouping_move_id:
                raise UserError(_(
                    'No se puede añadir la agrupación %(group)s a la remesa porque todavía no tiene '
                    'asiento inicial. Abre la agrupación, selecciona su diario bancario y guarda.'
                ) % {'group': group.display_name})
            group._sync_container_effect()
        remittance._compute_totals()
        remittance._sync_container_effect()
        remittance._ensure_initial_move()
        if effects and not remittance._initial_move_is_valid():
            raise UserError(_('No se han podido añadir los efectos: el asiento inicial de la remesa no está publicado y cuadrado. Comprueba el diario y los vencimientos contables.'))
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_create_from_menu(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Crear efecto'),
            'res_model': 'account.effect',
            'view_mode': 'form',
            'views': [(self.env.ref('l10n_es_effects.view_account_effect_form').id, 'form')],
            'target': 'current',
            'context': {
                'default_company_type': self.env.context.get('default_company_type', 'customer'),
                'default_effect_type': 'effect',
                'default_due_date': fields.Date.context_today(self),
                'default_manual_category': self.env.context.get('default_manual_category'),
                'cartera_new_mode': True,
            },
        }

    def action_new_effect(self):
        return {'type': 'ir.actions.act_window', 'name': _('Crear efecto'), 'res_model': 'account.effect', 'view_mode': 'form', 'target': 'current', 'context': dict(self.env.context)}

    def action_ungroup_selected(self):
        """Desvincula los efectos de agrupaciones/remesas sin marcar devolución."""
        containers = self.filtered('is_container')
        for container in containers:
            if container.container_remittance_id:
                if container.container_remittance_id._has_active_payments():
                    raise UserError(_('No se pueden quitar efectos de una remesa que tiene pagos activos. Anula primero los pagos asociados a la remesa.'))
                return container.container_remittance_id.action_ungroup_selected()
            if container.container_group_id:
                return container.container_group_id.action_ungroup_selected()
        for effect in self:
            if effect.state == 'paid':
                continue
            group = effect.group_id
            remittance = effect.remittance_id
            if remittance and group:
                # Quitar un efecto de una remesa no deshace su agrupación.
                effect.write({
                    'remittance_id': False,
                    'state': 'grouped',
                    'cartera_number': group.cartera_number,
                })
                effect._log_situation('grouped', _('Efecto retirado de la remesa'))
            else:
                effect.write({
                    'group_id': False,
                    'remittance_id': False,
                    'state': 'pending',
                    'cartera_number': False,
                })
                effect._log_situation('pending', _('Efecto desagrupado/desremesado'))
            if group:
                group._compute_totals()
            if remittance:
                remittance._compute_totals()
        return True

    def _get_reconciled_payment(self):
        self.ensure_one()
        if not self.move_line_id:
            return self.env['account.payment']
        if self.move_line_id.payment_id:
            return self.move_line_id.payment_id
        counterpart_lines = (
            self.move_line_id.matched_debit_ids.mapped('debit_move_id')
            | self.move_line_id.matched_credit_ids.mapped('credit_move_id')
        )
        payments = counterpart_lines.mapped('payment_id')
        return payments[:1]

    def _mark_paid_from_payment(self, payment_date=False):
        effects = self.filtered(lambda e: not e.is_container and e.move_line_id and e.move_line_id.reconciled)
        if effects:
            paid_date = payment_date or fields.Date.context_today(self)
            paid_vals = {'state': 'paid', 'paid_date': paid_date}
            effects.write(paid_vals)
            for effect in effects:
                payment = effect._get_reconciled_payment()
                if payment:
                    effect.payment_id = payment.id
            effects._log_situation('paid', _('Efecto saldado'))
            groups = effects.mapped('group_id')
            remittances = effects.mapped('remittance_id')
            for group in groups:
                group._update_payment_state_from_effects(paid_date)
            for remittance in remittances:
                remittance._update_payment_state_from_effects(paid_date)
        return effects

    def action_refresh_payment_state(self):
        """Refresh the payment status of the selected effects."""
        self._compute_payment_state()
        return True

    def action_update_changes(self):
        """Refresh payment status and portfolio relationships."""
        self._compute_payment_state()
        self._compute_display_labels()
        return True

    def action_mark_returned(self):
        effects = self.filtered(lambda e: e.state not in ('paid', 'uncollectible'))
        effects._set_state('returned', _('Marcado como devuelto'))

    def action_mark_uncollectible(self):
        effects = self.filtered(lambda e: e.state != 'paid')
        effects._set_state('uncollectible', _('Marcado como incobrable'))
