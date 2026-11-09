from datetime import date
from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    cartera_mode = fields.Boolean(string='Modo cartera', readonly=True, default=lambda self: bool(self.env.context.get('effect_id') or self.env.context.get('group_id') or self.env.context.get('remittance_id')))
    cartera_amount_editable = fields.Boolean(string='Importe editable', readonly=True, default=lambda self: bool(self.env.context.get('cartera_amount_editable')))
    effect_id = fields.Many2one(
        'account.effect',
        string='Efecto',
        readonly=True,
    )
    cartera_effect_ids = fields.Many2many('account.effect', string='Efectos de cartera', readonly=True)
    total_effect = fields.Monetary(
        string='Total efecto',
        currency_field='currency_id',
        readonly=False,
    )
    cartera_max_amount = fields.Monetary(
        string='Máximo liquidable',
        currency_field='currency_id',
        compute='_compute_effect_options',
        readonly=True,
    )
    effect_balance = fields.Boolean(
        string='Cuadre del efecto',
        default=False,
    )
    effect_expenses = fields.Monetary(
        string='Gastos',
        currency_field='currency_id',
        default=0.0,
    )
    expense_account_id = fields.Many2one(
        'account.account',
        string='Cuenta de gastos',
        domain="[('deprecated', '=', False), ('company_ids', 'in', company_id)]",
    )
    effect_commissions = fields.Monetary(
        string='Comisiones',
        currency_field='currency_id',
        default=0.0,
    )
    commission_account_id = fields.Many2one(
        'account.account',
        string='Cuenta de comisiones',
        domain="[('deprecated', '=', False), ('company_ids', 'in', company_id)]",
    )
    group_bank_entries = fields.Boolean(
        string='Agrupar apuntes en banco',
        default=False,
        help='Si está marcado, los gastos y comisiones se contabilizan en un único asiento con un único apunte contra el banco.',
    )

    def _cartera_effect_pending_value(self, effect):
        amount = effect._settlement_pending_amount()
        if effect.currency_id.is_zero(amount) and effect.state in ('pending', 'grouped', 'remitted'):
            return abs(effect.amount)
        return amount

    @api.depends('effect_id', 'cartera_effect_ids', 'currency_id')
    def _compute_effect_options(self):
        for wizard in self:
            if wizard.env.context.get('cartera_portfolio_child_id'):
                child = wizard.env['account.effect'].browse(wizard.env.context.get('cartera_portfolio_child_id')).exists()
                wizard.cartera_max_amount = abs(child.amount) if child else 0.0
            elif wizard.cartera_effect_ids:
                wizard.cartera_max_amount = sum(wizard._cartera_effect_pending_value(e) for e in wizard.cartera_effect_ids)
            elif wizard.effect_id:
                wizard.cartera_max_amount = wizard.effect_id._settlement_pending_amount() or abs(wizard.effect_id.amount)
            else:
                wizard.cartera_max_amount = wizard.amount

    @api.onchange('effect_balance')
    def _onchange_effect_balance(self):
        for wizard in self:
            if wizard.effect_balance:
                account = wizard._find_account_by_code('769')
                if account:
                    wizard.expense_account_id = account
            else:
                account = wizard._find_account_by_code('626')
                if account:
                    wizard.expense_account_id = account

    @api.model
    def _find_account_by_code(self, code):
        company = self.company_id or self.env.company
        return self.env['account.account'].search([
            ('code', '=like', code + '%'),
            ('company_ids', 'in', company.id),
            ('deprecated', '=', False),
        ], order='code', limit=1)

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        effect_id = self.env.context.get('effect_id')
        cartera_mode = bool(effect_id or self.env.context.get('group_id') or self.env.context.get('remittance_id'))
        vals['cartera_mode'] = cartera_mode
        active_ids = self.env.context.get('active_ids') or []
        explicit_effect_ids = self.env.context.get('cartera_effect_ids') or []
        # In payment register, active_ids are account.move.line ids. Prefer the
        # explicit cartera effect ids supplied by a remittance/group action and
        # otherwise resolve the due lines back to their effects.
        effects = self.env['account.effect'].browse(explicit_effect_ids).exists()
        portfolio_child_id = self.env.context.get('cartera_portfolio_child_id')
        portfolio_child = self.env['account.effect'].browse(portfolio_child_id).exists() if portfolio_child_id else self.env['account.effect']
        portfolio_root = portfolio_child.portfolio_chain_id if portfolio_child else self.env['account.effect']
        if portfolio_child and portfolio_root:
            # The child is the cartera effect being settled, while the original
            # accounting due line remains the reconciliation line.
            effects = portfolio_child
        if not effects:
            effects = self.env['account.effect'].search([
                ('move_line_id', 'in', active_ids),
                ('is_container', '=', False),
            ]) if active_ids else self.env['account.effect']
        remittance_id = self.env.context.get('remittance_id')
        if remittance_id and not portfolio_child:
            remittance = self.env['account.effect.remittance'].browse(remittance_id).exists()
            if remittance:
                remittance_effects = remittance.effect_ids.filtered(
                    lambda e: e.move_line_id and e.move_line_id.id in active_ids
                )
                if remittance_effects:
                    effects = remittance_effects
        if cartera_mode:
            group_id = self.env.context.get('group_id')
            remittance_id = self.env.context.get('remittance_id')
            container_journal = self.env['account.journal']
            if group_id:
                container_journal = self.env['account.effect.group'].browse(group_id).exists().bank_journal_id
            elif remittance_id:
                container_journal = self.env['account.effect.remittance'].browse(remittance_id).exists().bank_journal_id
            if not container_journal and effect_id:
                individual_effect = self.env['account.effect'].browse(effect_id).exists()
                if individual_effect and individual_effect.bank_journal_id:
                    container_journal = individual_effect.bank_journal_id
            if not container_journal and portfolio_child:
                container_journal = portfolio_child.bank_journal_id
            if not container_journal:
                journals = self.env['account.journal'].search([
                    ('company_id', '=', self.env.company.id),
                    ('type', '=', 'bank'),
                    ('default_account_id', '!=', False),
                ], order='sequence, id')
                if not journals:
                    journals = self.env['account.journal'].search([
                        ('company_id', '=', self.env.company.id),
                        ('type', '=', 'cash'),
                        ('default_account_id', '!=', False),
                    ], order='sequence, id')
                container_journal = journals[:1]
            if container_journal:
                vals['journal_id'] = container_journal.id
            account_626 = self._find_account_by_code('626')
            if account_626:
                vals['expense_account_id'] = account_626.id
                vals['commission_account_id'] = account_626.id
        if effect_id:
            effect = self.env['account.effect'].browse(effect_id).exists()
            if effect:
                vals['effect_id'] = effect.id
                if not vals.get('communication'):
                    vals['communication'] = _('Efecto nº %s') % (effect.cartera_number or effect.name)
        if not vals.get('communication') and len(effects) == 1:
            single_effect = effects[0]
            vals['communication'] = _('Efecto nº %s') % (single_effect.cartera_number or single_effect.name)
        if effects:
            vals['cartera_effect_ids'] = [(6, 0, effects.ids)]
            if portfolio_child:
                vals['total_effect'] = abs(portfolio_child.amount)
                vals['amount'] = vals['total_effect']
            else:
                vals['total_effect'] = sum(self._cartera_effect_pending_value(e) for e in effects)
                if cartera_mode:
                    vals['amount'] = vals['total_effect']
        elif cartera_mode:
            remittance_id = self.env.context.get('remittance_id')
            group_id = self.env.context.get('group_id')
            if remittance_id:
                remittance = self.env['account.effect.remittance'].browse(remittance_id).exists()
                if remittance:
                    vals['total_effect'] = remittance.amount_pending
                    vals['amount'] = remittance.amount_pending
            elif group_id:
                group = self.env['account.effect.group'].browse(group_id).exists()
                if group:
                    vals['total_effect'] = group.amount_pending
                    vals['amount'] = group.amount_pending
        override = self.env.context.get('cartera_effect_amount_override')
        if cartera_mode and override is not None:
            vals['total_effect'] = override
            vals['amount'] = override
        return vals

    def _validate_effect_options(self):
        self.ensure_one()
        if not self.cartera_mode:
            return
        if self.effect_expenses < 0 or self.effect_commissions < 0:
            raise UserError(_('Los gastos y las comisiones no pueden ser negativos.'))
        if self.effect_expenses and not self.expense_account_id:
            raise UserError(_('Indica la cuenta de gastos.'))
        if self.effect_commissions and not self.commission_account_id:
            raise UserError(_('Indica la cuenta de comisiones.'))

    def _create_effect_adjustment_entry(self, payment=None):
        self.ensure_one()
        self._validate_effect_options()
        expenses = self.effect_expenses
        commissions = self.effect_commissions
        if not expenses and not commissions:
            return self.env['account.move']

        journal = self.journal_id
        if journal.type not in ('bank', 'cash'):
            raise UserError(_('El diario utilizado para saldar debe ser de banco o caja para contabilizar gastos y comisiones.'))

        company = self.company_id
        bank_account = journal.default_account_id
        if not bank_account:
            # Fall back to the journal's liquidity account when available.
            bank_lines = journal._get_journal_inbound_outstanding_payment_accounts()
            bank_account = bank_lines[:1] if bank_lines else self.env['account.account']
        if not bank_account:
            raise UserError(_('El diario %s no tiene una cuenta de liquidez configurada.') % journal.display_name)

        line_specs = []
        amounts = [(expenses, self.expense_account_id), (commissions, self.commission_account_id)]
        for amount, account in amounts:
            if not amount:
                continue
            line_specs.append((amount, account))

        # Create one balanced adjustment move. Expense/commission accounts
        # remain separate; the bank counterpart is either one net line or one
        # counterpart per adjustment, according to the user's bank grouping option.
        lines = []
        label = self.communication or (payment.name if payment else _('Liquidación de cartera'))
        total = sum(amount for amount, _account in line_specs)
        for amount, account in line_specs:
            lines.append((0, 0, {
                'name': label,
                'account_id': account.id,
                'partner_id': self.partner_id.id,
                'debit': amount if self.payment_type == 'inbound' else 0.0,
                'credit': amount if self.payment_type == 'outbound' else 0.0,
            }))
            if not self.group_bank_entries:
                lines.append((0, 0, {
                    'name': label,
                    'account_id': bank_account.id,
                    'debit': amount if self.payment_type == 'outbound' else 0.0,
                    'credit': amount if self.payment_type == 'inbound' else 0.0,
                }))
        if self.group_bank_entries:
            lines.append((0, 0, {
                'name': label,
                'account_id': bank_account.id,
                'debit': total if self.payment_type == 'outbound' else 0.0,
                'credit': total if self.payment_type == 'inbound' else 0.0,
            }))
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': self.payment_date,
            'journal_id': journal.id,
            'ref': label,
            'line_ids': lines,
        })
        move.action_post()
        return move


    def _create_partial_portfolio_effects(self, effects, payment_date):
        """For a grouping, create a new pending portfolio effect for the remaining amount."""
        created = self.env['account.effect']
        groups = effects.filtered(lambda e: e.group_id and not e.is_container).mapped('group_id')
        for group in groups:
            group._compute_totals()
            pending = group.amount_pending
            if pending <= 0 or pending >= group.amount_total:
                continue
            vals = {
                'company_id': group.company_id.id,
                'company_type': group.company_type,
                'partner_id': group.partner_id.id if group.partner_id else False,
                'move_id': False, 'move_line_id': False,
                'reference': group.reference or False, 'invoice_reference': False,
                'due_date': payment_date, 'effect_type': 'effect',
                'bank_journal_id': group.bank_journal_id.id if group.bank_journal_id else False,
                'partner_bank_id': group.partner_bank_id.id if group.partner_bank_id else False,
                'payment_direction': group.payment_direction,
                'amount': pending if group.payment_direction == 'receive' else -pending, 'currency_id': group.currency_id.id,
                'state': 'pending', 'is_container': True, 'is_portfolio_effect': True,
                'container_group_id': group.id, 'container_remittance_id': False,
                'cartera_number': group.cartera_number, 'active': True,
            }
            new_effect = self.env['account.effect'].create(vals)
            created |= new_effect
            new_effect._log_situation('pending', _('Pendiente tras saldado parcial de la agrupación'))
        return created

    def _create_individual_partial_portfolio_effects(self, effects, payment_date, residuals=None):
        created = self.env['account.effect']
        for effect in effects.filtered(lambda e: not e.is_container):
            root = effect.portfolio_chain_id or effect
            if residuals is not None:
                residual = residuals.get(effect.id, 0.0) if isinstance(residuals, dict) else residuals
            elif root.move_line_id and not root.move_line_id.reconciled:
                residual = root._settlement_pending_amount()
            else:
                residual = 0.0
            if residual <= effect.currency_id.rounding:
                continue
            vals = {
                'company_id': effect.company_id.id, 'company_type': effect.company_type,
                'partner_id': effect.partner_id.id if effect.partner_id else False,
                'move_id': root.move_id.id if root.move_id else (effect.move_id.id if effect.move_id else False),
                'move_line_id': False,
                # The circular/concept is part of the effect's identity in the
                # portfolio workflow and must survive every partial settlement.
                'reference': effect.reference or False,
                'invoice_reference': effect.invoice_reference,
                'due_date': payment_date, 'effect_type': 'effect',
                'bank_journal_id': effect.bank_journal_id.id if effect.bank_journal_id else False,
                'partner_bank_id': effect.partner_bank_id.id if effect.partner_bank_id else False,
                'payment_direction': effect.payment_direction, 'amount': residual if effect.payment_direction == 'receive' else -residual,
                'currency_id': effect.currency_id.id, 'state': 'pending',
                'is_container': False, 'is_portfolio_effect': False,
                'portfolio_chain_id': root.id, 'cartera_number': effect.cartera_number, 'active': True,
            }
            new_effect = self.env['account.effect'].create(vals)
            created |= new_effect
            new_effect._log_situation('pending', _('Pendiente tras saldado parcial de %s') % effect.name)
        return created

    def _create_container_payment_history(self, payment, effects, container_type, container):
        if not payment or not container:
            return
        model = self.env['account.effect.container.payment.history']
        vals = {
            'payment_id': payment.id,
            'reference': payment.name or payment.memo or payment.payment_reference or '',
            'move_id': payment.move_id.id if payment.move_id else False,
            'date': payment.date,
            'effect_ids': [(6, 0, effects.ids)],
            'amount': payment.amount,
            'currency_id': payment.currency_id.id,
            'type': 'paid',
        }
        if container_type == 'group':
            vals['group_id'] = container.id
            domain = [('payment_id', '=', payment.id), ('group_id', '=', container.id)]
        else:
            vals['remittance_id'] = container.id
            domain = [('payment_id', '=', payment.id), ('remittance_id', '=', container.id)]
        if not model.search(domain, limit=1):
            model.create(vals)

    def _create_cartera_shadow_payments(self, move, history, allocations, journal, company_type, payment_direction, currency, payment_date):
        """Create native account.payment rows linked to the single posted move.

        Standalone remittance effects retain their own customer/vendor. An effect
        already transferred to a grouping uses the grouping's single destination
        partner, never its original invoice partner. All rows share the one bank
        move and do not create duplicate accounting entries.
        """
        payment_type = 'inbound' if payment_direction == 'receive' else 'outbound'
        partner_allocations = {}
        for effect, applied in allocations:
            if effect.group_id and effect.group_id.grouping_move_id:
                partner = effect.group_id.partner_id
            else:
                source = effect.move_line_id or effect.portfolio_chain_id.move_line_id
                partner = effect.partner_id or (source.partner_id if source else False)
            if not partner:
                raise UserError(_('El efecto %s no tiene un cliente/proveedor para relacionar el pago.') % effect.display_name)
            item = partner_allocations.setdefault(partner.id, {
                'partner': partner,
                'amount': 0.0,
                'effects': self.env['account.effect'],
            })
            item['amount'] += applied
            item['effects'] |= effect

        method_lines = journal.inbound_payment_method_line_ids if payment_type == 'inbound' else journal.outbound_payment_method_line_ids
        method_line = method_lines.filtered(lambda line: line.code == 'manual')[:1] or method_lines[:1]
        if not method_line:
            raise UserError(_(
                'El diario %(journal)s no tiene un método de pago %(direction)s disponible. '
                'Configura el método Manual en el diario para registrar los pagos de cartera.'
            ) % {
                'journal': journal.display_name,
                'direction': _('de cobro') if payment_type == 'inbound' else _('de pago'),
            })

        created = self.env['account.payment']
        for item in partner_allocations.values():
            partner = item['partner']
            effects = item['effects']
            invoices = effects.mapped('move_id').filtered(
                lambda invoice: invoice.partner_id.commercial_partner_id == partner.commercial_partner_id
            )
            payment = self.env['account.payment'].create({
                'date': payment_date,
                'journal_id': journal.id,
                'company_id': self.company_id.id,
                'amount': currency.round(item['amount']),
                'currency_id': currency.id,
                'payment_type': payment_type,
                'partner_type': company_type,
                'partner_id': partner.id,
                'payment_method_line_id': method_line.id,
                'memo': move.ref or history.reference or move.name,
                'payment_reference': move.ref or move.name or history.reference,
                'move_id': move.id,
                'cartera_settled': True,
                'invoice_ids': [(6, 0, invoices.ids)],
                'cartera_consolidated': True,
                'cartera_effect_ids': [(6, 0, effects.ids)],
                'cartera_container_history_id': history.id,
            })
            created |= payment
            effects.write({'payment_id': payment.id})
            for effect in effects:
                self.env['account.effect.payment.history'].create({
                    'effect_id': effect.id,
                    'date': payment_date,
                    'payment_id': payment.id,
                    'move_id': move.id,
                    'journal_id': journal.id,
                    'amount': sum(amount for allocated_effect, amount in allocations if allocated_effect == effect),
                    'note': _('Pago de cartera conjunto %s') % (move.name or move.ref or ''),
                })

        history.write({
            'payment_ids': [(6, 0, created.ids)],
            'payment_id': created.id if len(created) == 1 else False,
        })
        return created

    def _create_cartera_container_move(self):
        """Create one journal entry for a group/remittance, even with many partners.

        For a grouped effect the counterpart is the open reclassified line of its
        group. For a standalone effect it is the source receivable/payable line.
        The allocation is stored per effect, so successive partial payments are
        deterministic and auditable.
        """
        self.ensure_one()
        ctx = self.env.context
        group = self.env['account.effect.group'].browse(ctx.get('group_id')).exists() if ctx.get('group_id') else self.env['account.effect.group']
        remittance = self.env['account.effect.remittance'].browse(ctx.get('remittance_id')).exists() if ctx.get('remittance_id') else self.env['account.effect.remittance']
        if not group and not remittance:
            raise UserError(_('No se ha encontrado la agrupación o remesa que se desea saldar.'))

        effects = self.env['account.effect'].browse(ctx.get('cartera_effect_ids') or []).exists()
        if not effects:
            effects = (group.effect_ids if group else remittance.effect_ids).filtered(lambda e: not e.is_container)
        effects = effects.filtered(lambda e: not e.is_container and e.active and e.state not in ('paid', 'returned', 'uncollectible'))
        if not effects:
            raise UserError(_('No hay efectos pendientes para esta operación.'))
        if any(e.company_id != self.company_id for e in effects):
            raise UserError(_('Todos los efectos deben pertenecer a la misma compañía.'))
        currencies = effects.mapped('currency_id')
        if len(currencies) != 1 or currencies[0] != self.currency_id:
            raise UserError(_('Todos los efectos seleccionados deben tener la misma moneda que el pago.'))
        company_types = set(effects.mapped('company_type'))
        if len(company_types) != 1:
            raise UserError(_('No se pueden mezclar cobros de clientes y pagos a proveedores.'))
        company_type = next(iter(company_types))
        payment_directions = set(effects.mapped('payment_direction'))
        if len(payment_directions) != 1:
            raise UserError(_('No se pueden liquidar juntos efectos que impliquen cobros y pagos en direcciones distintas.'))
        payment_direction = next(iter(payment_directions))
        if group and any(e.group_id != group for e in effects):
            raise UserError(_('La agrupación contiene efectos que no pertenecen a ella.'))
        if remittance and any(e.remittance_id != remittance for e in effects):
            raise UserError(_('Hay efectos seleccionados que no pertenecen a esta remesa.'))

        pending_by_effect = {e.id: e._cartera_pending_amount() for e in effects}
        max_amount = sum(pending_by_effect.values())
        if self.currency_id.is_zero(max_amount):
            raise UserError(_('Los efectos seleccionados no tienen saldo pendiente.'))
        amount = self.total_effect
        if amount <= 0 or self.currency_id.is_zero(amount):
            raise UserError(_('El importe a saldar debe ser mayor que cero.'))
        if amount > max_amount + self.currency_id.rounding:
            raise UserError(_('El importe supera el saldo pendiente seleccionado (%s).') % max_amount)
        if not self.cartera_amount_editable and self.currency_id.compare_amounts(amount, max_amount) != 0:
            raise UserError(_('En una remesa se salda el importe íntegro de los efectos seleccionados. No se permite reducir el importe de un efecto.'))

        # A remittance must first have its opening reclassification entry.
        if remittance:
            remittance._ensure_initial_move()
            if not remittance.initial_move_id or remittance.initial_move_id.state != 'posted':
                raise UserError(_('La remesa necesita su asiento inicial publicado antes de poder saldarse.'))

        # Groups must have their initial reclassification move before a payment.
        groups = effects.mapped('group_id').filtered(lambda g: g and g.grouping_move_id)
        missing_groups = effects.mapped('group_id') - groups
        for missing_group in missing_groups:
            if not missing_group.bank_journal_id:
                fallback_journal = self.journal_id or (remittance.bank_journal_id if remittance else self.env['account.journal'])
                if not fallback_journal or fallback_journal.type not in ('bank', 'cash'):
                    raise UserError(_('La agrupación %s necesita un diario bancario para generar su asiento inicial.') % missing_group.display_name)
                missing_group.bank_journal_id = fallback_journal.id
            missing_group._create_grouping_move()
        groups = effects.mapped('group_id').filtered(lambda g: g and g.grouping_move_id and g.grouping_move_id.state == 'posted')
        if any(e.group_id and e.group_id not in groups for e in effects):
            raise UserError(_('No se ha podido generar el asiento inicial de todas las agrupaciones seleccionadas.'))

        journal = self.journal_id
        if not journal:
            journal = (group.bank_journal_id if group else remittance.bank_journal_id)
        if not journal:
            journals = effects.mapped('bank_journal_id')
            journal = journals[:1] if journals else self.env['account.journal']
        if not journal or journal.type not in ('bank', 'cash'):
            raise UserError(_('Selecciona un diario de banco o caja para registrar el pago.'))
        bank_account = journal.default_account_id
        if not bank_account:
            raise UserError(_('El diario %s no tiene una cuenta de liquidez predeterminada (por ejemplo, 572).') % journal.display_name)
        payment_date = self.payment_date or fields.Date.context_today(self)
        is_inbound = payment_direction == 'receive'
        currency = currencies[0]
        company_currency = self.company_id.currency_id

        # An editable amount is allocated by oldest maturity first. This provides
        # a stable rule for partial payments without asking the operator to split
        # the amount manually between customers/effects.
        remaining = amount
        allocations = []
        ordered = effects.sorted(key=lambda e: (e.due_date or date.max, e.id))
        for effect in ordered:
            available = pending_by_effect.get(effect.id, 0.0)
            if currency.is_zero(available) or currency.is_zero(remaining):
                continue
            applied = min(available, remaining)
            applied = currency.round(applied)
            if not currency.is_zero(applied):
                allocations.append((effect, applied))
                remaining = currency.round(remaining - applied)
        if not currency.is_zero(remaining):
            raise UserError(_('No se ha podido distribuir todo el importe entre los efectos seleccionados.'))

        buckets = {}
        groups_in_operation = self.env['account.effect.group']
        for effect, applied in allocations:
            if remittance:
                sources = remittance.initial_move_id.line_ids.filtered(
                    lambda line: line.effect_remittance_line_type == 'target'
                    and line.effect_remittance_effect_id == effect
                    and not line.reconciled
                )
                if not sources:
                    raise UserError(_('El efecto %s no tiene un apunte de destino abierto en el asiento inicial de remesa.') % effect.display_name)
                source = sources[:1]
                account = source.account_id
                partner = source.partner_id or effect.partner_id
                key = ('remittance', account.id, partner.id if partner else 0, currency.id)
            elif effect.group_id and effect.group_id.grouping_move_id:
                group_for_effect = effect.group_id
                source = effect.move_line_id
                # Effects created manually have no origin move line by design.
                # Their initial grouping entry already transfers the balance
                # from manual_account_id to the single grouping balance line;
                # settlement is therefore reconciled against that grouping line.
                if not source and (effect.move_id or not effect.manual_account_id):
                    raise UserError(_('El efecto agrupado %s no tiene un vencimiento de origen ni una cuenta manual válida.') % effect.display_name)
                account = group_for_effect.grouping_account_id
                partner = group_for_effect.partner_id
                if not account or not partner:
                    raise UserError(_('La agrupación %s necesita una cuenta de agrupación y un cliente/proveedor de destino.') % group_for_effect.display_name)
                key = ('group', group_for_effect.id, account.id, partner.id if partner else 0, currency.id)
                groups_in_operation |= group_for_effect
                sources = group_for_effect._get_grouping_lines().filtered(
                    lambda line: line.account_id == account and line.partner_id == partner
                    and line.currency_id == currency and not line.reconciled
                )
            else:
                root = effect.portfolio_chain_id or effect
                source = root.move_line_id
                account = source.account_id if source else effect.manual_account_id
                partner = (source.partner_id if source else effect.partner_id) or effect.partner_id
                if not account:
                    raise UserError(_('El efecto %s no tiene cuenta contable conciliable.') % effect.display_name)
                key = ('direct', account.id, partner.id if partner else 0, currency.id)
                sources = source if source else self.env['account.move.line']

            if not account.reconcile:
                raise UserError(_('La cuenta %s no permite conciliación y no puede liquidarse desde cartera.') % account.display_name)
            bucket = buckets.setdefault(key, {
                'kind': key[0],
                'group': effect.group_id if key[0] == 'group' else self.env['account.effect.group'],
                'account': account,
                'partner': partner,
                'currency': currency,
                'amount': 0.0,
                'effects': self.env['account.effect'],
                'sources': self.env['account.move.line'],
            })
            bucket['amount'] += applied
            bucket['effects'] |= effect
            bucket['sources'] |= sources

        if not buckets:
            raise UserError(_('No se han podido generar las contrapartidas contables del pago.'))

        total_company = 0.0
        counterpart_specs = []
        for bucket in buckets.values():
            company_amount = bucket['currency']._convert(
                bucket['amount'], company_currency, self.company_id, payment_date, round=True,
            ) if bucket['currency'] != company_currency else bucket['amount']
            total_company += company_amount
            sign = -1 if is_inbound else 1
            bucket_effect = bucket['effects'][:1]
            container_label = (
                _('Agrupación nº %s') % group.cartera_number if group
                else _('Remesa nº %s') % remittance.cartera_number
            )
            line_name = container_label + ((' · ' + self.communication.strip()) if self.communication and self.communication.strip() else '')
            if not self.communication:
                line_name += ' · ' + (bucket_effect.name or bucket_effect.display_label)
            bucket['line_name'] = line_name
            line_vals = {
                'name': line_name,
                'account_id': bucket['account'].id,
                'partner_id': bucket['partner'].id if bucket['partner'] else False,
                'currency_id': bucket['currency'].id,
                'amount_currency': sign * bucket['amount'],
                'debit': company_amount if sign > 0 else 0.0,
                'credit': company_amount if sign < 0 else 0.0,
            }
            if bucket['kind'] == 'group':
                line_vals['effect_group_id'] = bucket['group'].id
            line_vals['effect_ids'] = [(6, 0, bucket['effects'].ids)]
            counterpart_specs.append((0, 0, line_vals))
            bucket['company_amount'] = company_amount

        fee_specs = []
        if self.effect_expenses:
            fee_specs.append((self.effect_expenses, self.expense_account_id))
        if self.effect_commissions:
            fee_specs.append((self.effect_commissions, self.commission_account_id))
        fee_company = 0.0
        fee_lines = []
        for fee_amount, fee_account in fee_specs:
            fee_value = currency._convert(fee_amount, company_currency, self.company_id, payment_date, round=True) if currency != company_currency else fee_amount
            fee_company += fee_value
            fee_lines.append((0, 0, {
                'name': self.communication or _('Gastos/comisiones de cartera'),
                'account_id': fee_account.id,
                'debit': fee_value,
                'credit': 0.0,
            }))

        if is_inbound and fee_company > total_company + company_currency.rounding:
            raise UserError(_('Los gastos y comisiones no pueden superar el importe cobrado.'))
        bank_amount = total_company - fee_company if is_inbound else total_company + fee_company
        if bank_amount < 0:
            raise UserError(_('El importe neto bancario no puede ser negativo.'))
        bank_line = (0, 0, {
            'name': self.communication or _('Cobro de cartera' if is_inbound else 'Pago de cartera'),
            'account_id': bank_account.id,
            'debit': bank_amount if is_inbound else 0.0,
            'credit': bank_amount if not is_inbound else 0.0,
        })
        line_values = counterpart_specs + fee_lines + [bank_line]
        circular_reference = (self.communication or '').strip()
        if not circular_reference:
            circular_reference = (
                (group.reference if group else remittance.reference)
                or container_label
            )
        move_vals = {
            'move_type': 'entry',
            'date': payment_date,
            'journal_id': journal.id,
            'ref': _('%s Saldado') % circular_reference,
            'line_ids': line_values,
        }
        if group:
            move_vals['effect_group_ids'] = [(4, group.id)]
        if groups_in_operation:
            move_vals['effect_group_ids'] = [(6, 0, groups_in_operation.ids + ([group.id] if group and group.id not in groups_in_operation.ids else []))]
        if remittance:
            move_vals['effect_remittance_id'] = remittance.id
        move = self.env['account.move'].create(move_vals)
        move.action_post()

        # Apply the payment against the consolidated grouping balance or the
        # original open invoice lines. A single bank line remains in this move.
        for bucket, spec in zip(buckets.values(), counterpart_specs):
            payment_line = move.line_ids.filtered(lambda line: line.account_id == bucket['account'] and line.partner_id == bucket['partner'] and bool(line.effect_ids & bucket['effects']))[:1]
            if not payment_line:
                # Names may be auto-normalized by Odoo; match by custom links.
                if bucket['kind'] == 'group':
                    payment_line = move.line_ids.filtered(lambda line: line.effect_group_id == bucket['group'] and line.effect_ids & bucket['effects'] and line.account_id == bucket['account'] and line.partner_id == bucket['partner'])[:1]
                else:
                    payment_line = move.line_ids.filtered(lambda line: line.effect_ids & bucket['effects'] and line.account_id == bucket['account'] and line.partner_id == bucket['partner'])[:1]
            if not payment_line:
                raise UserError(_('No se ha localizado una contrapartida del asiento para %s.') % (bucket['partner'].display_name if bucket['partner'] else bucket['account'].display_name))
            if bucket['kind'] == 'group':
                open_lines = bucket['group']._get_grouping_lines().filtered(
                    lambda line: line.account_id == bucket['account'] and line.partner_id == bucket['partner'] and line.currency_id == bucket['currency'] and not line.reconciled
                )
                reconcile_lines = open_lines | payment_line
            else:
                reconcile_lines = bucket['sources'].filtered(lambda line: not line.reconciled) | payment_line
            if len(reconcile_lines) >= 2:
                reconcile_lines.reconcile()

        history_vals = {
            'date': payment_date,
            'reference': move.ref or move.name or '',
            'move_id': move.id,
            'effect_ids': [(6, 0, effects.ids)],
            'amount': amount,
            'currency_id': currency.id,
            'type': 'paid',
            'allocation_line_ids': [(0, 0, {'effect_id': effect.id, 'amount': applied}) for effect, applied in allocations],
        }
        if group:
            history_vals['group_id'] = group.id
            history_vals['group_ids'] = [(4, group.id)]
        if groups_in_operation:
            history_vals['group_ids'] = [(6, 0, (groups_in_operation | (group if group else self.env['account.effect.group'])).ids)]
        if remittance:
            history_vals['remittance_id'] = remittance.id
        history = self.env['account.effect.container.payment.history'].create(history_vals)
        shadow_payments = self._create_cartera_shadow_payments(
            move, history, allocations, journal, company_type, payment_direction, currency, payment_date,
        )

        # Keep a visible settled tranche for every grouping affected by this
        # instalment. The source invoice effects remain the accounting detail;
        # the tranche represents the payment operation at grouping level.
        paid_portfolio_effects = self.env['account.effect']
        groups_with_amount = {}
        for effect, applied in allocations:
            if effect.group_id:
                groups_with_amount[effect.group_id] = groups_with_amount.get(effect.group_id, 0.0) + applied
        for grouped, applied_total in groups_with_amount.items():
            tranche = self.env['account.effect'].create({
                'company_id': grouped.company_id.id,
                'company_type': grouped.company_type,
                'partner_id': grouped.partner_id.id if grouped.partner_id else False,
                'reference': grouped.reference or _('Pago parcial de agrupación %s') % grouped.cartera_number,
                'due_date': payment_date,
                'effect_type': 'effect',
                'bank_journal_id': journal.id,
                'partner_bank_id': grouped.partner_bank_id.id if grouped.partner_bank_id else False,
                'payment_direction': grouped.payment_direction,
                'amount': currency.round(applied_total) if grouped.payment_direction == 'receive' else -currency.round(applied_total),
                'currency_id': currency.id,
                'state': 'paid',
                'paid_date': payment_date,
                'payment_id': (shadow_payments.filtered(lambda p: p.partner_id == grouped.partner_id)[:1].id
                               if grouped.partner_id else False),
                'is_portfolio_effect': True,
                'container_group_id': grouped.id,
                'active': True,
            })
            paid_portfolio_effects |= tranche
        if paid_portfolio_effects:
            history.write({'portfolio_effect_ids': [(6, 0, paid_portfolio_effects.ids)]})

        for effect, applied in allocations:
            if not effect.group_id:
                effect.write({'state': 'paid', 'paid_date': payment_date})
                effect._log_situation('paid', _('Efecto saldado mediante asiento %s') % move.name)

        for grouped in groups_in_operation:
            grouped._update_payment_state_from_effects(payment_date)
        if remittance:
            remittance._update_payment_state_from_effects(payment_date)
        elif group:
            group._update_payment_state_from_effects(payment_date)

        # Keep group/remittance containers and their synthetic residual effect in sync.
        for grouped in groups_in_operation:
            grouped._compute_totals()
            grouped._sync_container_effect()
        if remittance:
            remittance._compute_totals()
            remittance._sync_container_effect()

        if group:
            return group.action_open_effect()
        if remittance:
            return remittance.action_open_effect()
        return {'type': 'ir.actions.client', 'tag': 'reload'}

    def action_create_payments(self):
        self.ensure_one()
        self._validate_effect_options()
        if self.env.context.get('group_id') or self.env.context.get('remittance_id'):
            return self._create_cartera_container_move()
        # Keep these recordsets defined for the ordinary Odoo payment-register
        # flow as well as the cartera-child flow below.
        portfolio_child_id = self.env.context.get('cartera_portfolio_child_id')
        portfolio_child = (
            self.env['account.effect'].browse(portfolio_child_id).exists()
            if portfolio_child_id else self.env['account.effect']
        )
        portfolio_root = portfolio_child.portfolio_chain_id if portfolio_child else self.env['account.effect']
        if self.cartera_mode:
            max_amount = self.cartera_max_amount or self.total_effect
            if self.total_effect <= 0:
                raise UserError(_('El total del efecto debe ser mayor que cero.'))
            if max_amount and self.total_effect > max_amount + self.currency_id.rounding:
                raise UserError(_('El total del efecto no puede superar el importe pendiente seleccionado (%s).') % max_amount)
            # Only one active native payment may represent a cartera operation.
            # Old draft payments left by previous buggy versions are cancelled
            # before a new payment is created, so an effect cannot accumulate
            # multiple draft payment records.
            explicit_ids = self.env.context.get('cartera_effect_ids') or []
            old_effects = self.env['account.effect'].browse(explicit_ids).exists()
            # The child effect is the cartera record, while the root carries
            # the accounting due line.
            if portfolio_child and portfolio_root:
                old_effects |= portfolio_root
            old_payments = old_effects.mapped('payment_id').filtered(lambda p: p and p.state == 'draft')
            # Draft payments are never a valid historical payment for a cartera
            # effect. Remove them completely before creating a new native payment.
            for old_payment in old_payments:
                old_effects.filtered(lambda e: e.payment_id == old_payment).write({'payment_id': False, 'paid_date': False})
                self.env['account.effect.payment.history'].search([('payment_id', '=', old_payment.id)]).unlink()
                self.env['account.effect.container.payment.history'].search([('payment_id', '=', old_payment.id)]).unlink()
                old_payment.unlink()
            self.amount = self.total_effect
            # A cartera settlement represents one logical bank operation.
            # Odoo's native register can otherwise create one payment per due line.
            if 'group_payment' in self._fields:
                self.group_payment = True
        result = super().action_create_payments()

        explicit_ids = self.env.context.get('cartera_effect_ids') or []
        effects = self.env['account.effect'].browse(explicit_ids).exists()
        if not effects:
            active_line_ids = self.env.context.get('active_ids', [])
            effects = self.env['account.effect'].search([('is_container', '=', False), ('move_line_id', 'in', active_line_ids)])
        payment_date = self.payment_date or fields.Date.context_today(self)
        before_amounts = {e.id: e.amount for e in effects}
        accounting_effects = portfolio_root if portfolio_child and portfolio_root else effects
        payments = accounting_effects.mapped(lambda e: e._get_reconciled_payment()).exists()
        payment = payments[:1]

        # The child effect is the cartera record, while the root effect carries
        # the accounting due line. Handle that chain explicitly.
        if portfolio_child and portfolio_root:
            residual = portfolio_root._settlement_pending_amount()
            original = abs(portfolio_child.amount)
            if residual <= portfolio_root.currency_id.rounding:
                portfolio_child.write({'state': 'paid', 'paid_date': payment_date, 'payment_id': payment.id if payment else False})
            elif residual < original - portfolio_root.currency_id.rounding:
                settled_amount = original - residual
                portfolio_child.write({'amount': settled_amount if portfolio_child.payment_direction == 'receive' else -settled_amount, 'state': 'paid', 'paid_date': payment_date, 'payment_id': payment.id if payment else False})
                self._create_individual_partial_portfolio_effects(portfolio_child, payment_date, residual)
            if payment and portfolio_child.payment_id:
                portfolio_child._log_situation('paid', _('Efecto saldado mediante pago %s') % payment.display_name)
        else:
            # Capture residuals immediately after the native payment, before the
            # cartera state is changed to paid. This determines whether a
            # continuation effect is required.
            individual_partial = self.env['account.effect']
            for effect in effects.filtered(lambda e: not e.is_container and not e.group_id and not e.remittance_id and e.move_line_id):
                residual = effect._settlement_pending_amount()
                original = abs(before_amounts.get(effect.id, effect.amount))
                if residual > effect.currency_id.rounding and residual < original - effect.currency_id.rounding:
                    individual_partial |= effect
            effects._mark_paid_from_payment(payment_date)
            if payment and individual_partial:
                partial_residuals = {}
                for effect in individual_partial:
                    residual = effect._settlement_pending_amount()
                    original = abs(before_amounts.get(effect.id, effect.amount))
                    partial_residuals[effect.id] = residual
                    settled_magnitude = original - residual
                    settled_signed = settled_magnitude if effect.payment_direction == 'receive' else -settled_magnitude
                    effect.write({'amount': settled_signed, 'state': 'paid', 'paid_date': payment_date, 'payment_id': payment.id})
                self._create_individual_partial_portfolio_effects(individual_partial, payment_date, partial_residuals)

        group_id = self.env.context.get('group_id')
        remittance_id = self.env.context.get('remittance_id')
        if group_id:
            group = self.env['account.effect.group'].browse(group_id).exists()
            if group:
                group._update_payment_state_from_effects(payment_date)
        if remittance_id:
            remittance = self.env['account.effect.remittance'].browse(remittance_id).exists()
            if remittance:
                remittance._update_payment_state_from_effects(payment_date)

        self._create_partial_portfolio_effects(effects, payment_date)

        if self.effect_expenses or self.effect_commissions:
            adjustment = self._create_effect_adjustment_entry(payment)
            if adjustment:
                effects.write({'adjustment_move_id': adjustment.id})

        if payments:
            payments.filtered(lambda item: item.move_id and item.move_id.state == 'posted').with_context(cartera_internal_state_update=True).write({'cartera_settled': True})
            history_model = self.env['account.effect.payment.history']
            for effect in effects.filtered(lambda e: not e.is_container):
                effect_payment = effect._get_reconciled_payment() or payment
                if effect_payment:
                    history_model.create({
                        'effect_id': effect.id,
                        'date': payment_date,
                        'payment_id': effect_payment.id,
                        'journal_id': effect_payment.journal_id.id,
                        'amount': abs(effect.amount) if effect.state == 'paid' else self.total_effect,
                        'note': _('Efecto saldado mediante pago %s') % effect_payment.display_name,
                    })

        if payment and payment.move_id and payment.move_id.state == 'posted':
            payment.with_context(cartera_internal_state_update=True).write({'cartera_settled': True})

        if remittance_id and payments:
            remittance = self.env['account.effect.remittance'].browse(remittance_id).exists()
            if remittance:
                for container_payment in payments:
                    self._create_container_payment_history(container_payment, effects, 'remittance', remittance)
        if group_id and payments:
            group = self.env['account.effect.group'].browse(group_id).exists()
            if group:
                for container_payment in payments:
                    self._create_container_payment_history(container_payment, effects, 'group', group)
        if self.env.context.get('effect_id') or self.env.context.get('cartera_portfolio_child_id'):
            return {'type': 'ir.actions.client', 'tag': 'reload'}
        return result

