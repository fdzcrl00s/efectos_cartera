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
        if amount <= effect.currency_id.rounding and effect.state in ('pending', 'grouped', 'remitted'):
            return effect.amount
        return amount

    @api.depends('effect_id', 'cartera_effect_ids', 'currency_id')
    def _compute_effect_options(self):
        for wizard in self:
            if wizard.env.context.get('cartera_portfolio_child_id'):
                child = wizard.env['account.effect'].browse(wizard.env.context.get('cartera_portfolio_child_id')).exists()
                wizard.cartera_max_amount = child.amount if child else 0.0
            elif wizard.cartera_effect_ids:
                wizard.cartera_max_amount = sum(wizard._cartera_effect_pending_value(e) for e in wizard.cartera_effect_ids if e.move_line_id)
            elif wizard.effect_id:
                wizard.cartera_max_amount = wizard.effect_id._settlement_pending_amount() or wizard.effect_id.amount
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
            account_626 = self._find_account_by_code('626')
            if account_626:
                vals['expense_account_id'] = account_626.id
                vals['commission_account_id'] = account_626.id
        if effect_id:
            effect = self.env['account.effect'].browse(effect_id).exists()
            if effect:
                vals['effect_id'] = effect.id
        if effects:
            vals['cartera_effect_ids'] = [(6, 0, effects.ids)]
            if portfolio_child:
                vals['total_effect'] = portfolio_child.amount
                vals['amount'] = vals['total_effect']
            else:
                vals['total_effect'] = sum(self._cartera_effect_pending_value(e) for e in effects if e.move_line_id)
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

        # Bank counterpart is always the opposite side of the expense/commission lines.
        # This keeps the native payment/reconciliation untouched.
        lines = []
        total = sum(amount for amount, _account in line_specs)
        if self.group_bank_entries:
            for amount, account in line_specs:
                lines.append((0, 0, {
                    'name': self.communication or (payment.name if payment else _('Liquidación de cartera')),
                    'account_id': account.id,
                    'partner_id': self.partner_id.id,
                    'debit': amount if self.payment_type == 'inbound' else 0.0,
                    'credit': amount if self.payment_type == 'outbound' else 0.0,
                }))
            lines.append((0, 0, {
                'name': self.communication or (payment.name if payment else _('Liquidación de cartera')),
                'account_id': bank_account.id,
                'debit': total if self.payment_type == 'outbound' else 0.0,
                'credit': total if self.payment_type == 'inbound' else 0.0,
            }))
        else:
            for amount, account in line_specs:
                lines = [
                    (0, 0, {
                        'name': self.communication or (payment.name if payment else _('Liquidación de cartera')),
                        'account_id': account.id,
                        'partner_id': self.partner_id.id,
                        'debit': amount if self.payment_type == 'inbound' else 0.0,
                        'credit': amount if self.payment_type == 'outbound' else 0.0,
                    }),
                    (0, 0, {
                        'name': self.communication or (payment.name if payment else _('Liquidación de cartera')),
                        'account_id': bank_account.id,
                        'debit': amount if self.payment_type == 'outbound' else 0.0,
                        'credit': amount if self.payment_type == 'inbound' else 0.0,
                    }),
                ]
                move = self.env['account.move'].create({
                    'move_type': 'entry',
                    'date': self.payment_date,
                    'journal_id': journal.id,
                    'ref': self.communication or (payment.name if payment else _('Liquidación de cartera')),
                    'line_ids': lines,
                })
                move.action_post()
                return move
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': self.payment_date,
            'journal_id': journal.id,
            'ref': self.communication or (payment.name if payment else _('Liquidación de cartera')),
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
                'reference': False, 'invoice_reference': False,
                'due_date': payment_date, 'effect_type': 'effect',
                'bank_journal_id': group.bank_journal_id.id if group.bank_journal_id else False,
                'partner_bank_id': group.partner_bank_id.id if group.partner_bank_id else False,
                'payment_direction': group.payment_direction,
                'amount': pending, 'currency_id': group.currency_id.id,
                'state': 'pending', 'is_container': True, 'is_portfolio_effect': True,
                'container_group_id': group.id, 'container_remittance_id': False,
                'cartera_number': group.cartera_number, 'active': True,
            }
            new_effect = self.env['account.effect'].create(vals)
            created |= new_effect
            new_effect._log_situation('pending', _('Pendiente tras saldado parcial de la agrupación'))
        return created

    def _create_individual_partial_portfolio_effects(self, effects, payment_date):
        created = self.env['account.effect']
        for effect in effects.filtered(lambda e: not e.is_container):
            root = effect.portfolio_chain_id or effect
            if root.move_line_id and not root.move_line_id.reconciled:
                residual = root._settlement_pending_amount()
            else:
                residual = 0.0
            if residual <= effect.currency_id.rounding or residual >= effect.amount - effect.currency_id.rounding:
                continue
            vals = {
                'company_id': effect.company_id.id, 'company_type': effect.company_type,
                'partner_id': effect.partner_id.id if effect.partner_id else False,
                'move_id': root.move_id.id if root.move_id else (effect.move_id.id if effect.move_id else False),
                'move_line_id': False,
                'reference': False, 'invoice_reference': effect.invoice_reference,
                'due_date': payment_date, 'effect_type': 'effect',
                'bank_journal_id': effect.bank_journal_id.id if effect.bank_journal_id else False,
                'partner_bank_id': effect.partner_bank_id.id if effect.partner_bank_id else False,
                'payment_direction': effect.payment_direction, 'amount': residual,
                'currency_id': effect.currency_id.id, 'state': 'pending',
                'is_container': False, 'is_portfolio_effect': True,
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

    def action_create_payments(self):
        self.ensure_one()
        self._validate_effect_options()
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
        result = super().action_create_payments()

        explicit_ids = self.env.context.get('cartera_effect_ids') or []
        effects = self.env['account.effect'].browse(explicit_ids).exists()
        if not effects:
            active_line_ids = self.env.context.get('active_ids', [])
            effects = self.env['account.effect'].search([('is_container', '=', False), ('move_line_id', 'in', active_line_ids)])
        payment_date = self.payment_date or fields.Date.context_today(self)
        before_amounts = {e.id: e.amount for e in effects}
        accounting_effects = portfolio_root if portfolio_child and portfolio_root else effects
        payment = accounting_effects.mapped(lambda e: e._get_reconciled_payment())[:1]

        # The child effect is the cartera record, while the root effect carries
        # the accounting due line. Handle that chain explicitly.
        if portfolio_child and portfolio_root:
            residual = portfolio_root._settlement_pending_amount()
            original = portfolio_child.amount
            if residual <= portfolio_root.currency_id.rounding:
                portfolio_child.write({'state': 'paid', 'paid_date': payment_date, 'payment_id': payment.id if payment else False})
            elif residual < original - portfolio_root.currency_id.rounding:
                portfolio_child.write({'state': 'paid', 'paid_date': payment_date, 'payment_id': payment.id if payment else False})
                self._create_individual_partial_portfolio_effects(portfolio_child, payment_date)
            if payment and portfolio_child.payment_id:
                portfolio_child._log_situation('paid', _('Efecto saldado mediante pago %s') % payment.display_name)
        else:
            # Capture residuals immediately after the native payment, before the
            # cartera state is changed to paid. This determines whether a
            # continuation effect is required.
            individual_partial = self.env['account.effect']
            for effect in effects.filtered(lambda e: not e.is_container and not e.group_id and not e.remittance_id and e.move_line_id):
                residual = effect._settlement_pending_amount()
                original = before_amounts.get(effect.id, effect.amount)
                if residual > effect.currency_id.rounding and residual < original - effect.currency_id.rounding:
                    individual_partial |= effect
            effects._mark_paid_from_payment(payment_date)
            if payment and individual_partial:
                for effect in individual_partial:
                    effect.write({'state': 'paid', 'paid_date': payment_date, 'payment_id': payment.id})
                self._create_individual_partial_portfolio_effects(individual_partial, payment_date)

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

        if remittance_id and payment:
            remittance = self.env['account.effect.remittance'].browse(remittance_id).exists()
            if remittance:
                self._create_container_payment_history(payment, effects, 'remittance', remittance)
        if group_id and payment:
            group = self.env['account.effect.group'].browse(group_id).exists()
            if group:
                self._create_container_payment_history(payment, effects, 'group', group)
        return result

