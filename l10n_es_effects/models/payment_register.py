from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

    cartera_mode = fields.Boolean(string='Modo cartera', readonly=True, default=lambda self: bool(self.env.context.get('effect_id') or self.env.context.get('group_id') or self.env.context.get('remittance_id')))
    effect_id = fields.Many2one(
        'account.effect',
        string='Efecto',
        readonly=True,
    )
    cartera_effect_ids = fields.Many2many('account.effect', string='Efectos de cartera', readonly=True)
    total_effect = fields.Monetary(
        string='Total efecto',
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

    @api.depends('effect_id', 'cartera_effect_ids', 'currency_id')
    def _compute_effect_options(self):
        for wizard in self:
            if wizard.cartera_effect_ids:
                wizard.total_effect = sum(wizard.cartera_effect_ids.mapped('amount_pending'))
            else:
                effect = wizard.effect_id
                wizard.total_effect = effect.amount_pending if effect else wizard.amount

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
        if not effects:
            effects = self.env['account.effect'].search([
                ('move_line_id', 'in', active_ids),
                ('is_container', '=', False),
            ]) if active_ids else self.env['account.effect']
        remittance_id = self.env.context.get('remittance_id')
        if remittance_id:
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
            vals['total_effect'] = sum(effects.mapped('amount_pending'))
            if cartera_mode:
                vals['amount'] = sum(effects.mapped('amount_pending'))
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
        # Agrupaciones generan un nuevo efecto de cartera por el pendiente.
        # Las remesas NO generan nuevos efectos en saldados parciales: la propia
        # remesa mantiene siempre su único efecto de cartera.
        created = self.env['account.effect']
        for effect in effects.filtered(lambda e: e.group_id and not e.is_container and e.move_line_id and not e.move_line_id.reconciled):
            pending = effect.amount_pending
            if pending <= 0 or pending >= effect.amount:
                continue
            domain = [
                ('is_portfolio_effect', '=', True),
                ('move_id', '=', effect.move_id.id),
                ('amount', '=', pending),
                ('state', '=', 'pending'),
                ('container_group_id', '=', effect.group_id.id),
            ]
            existing = self.env['account.effect'].search(domain, limit=1)
            if existing:
                continue
            vals = {
                'company_id': effect.company_id.id,
                'company_type': effect.company_type,
                'partner_id': effect.partner_id.id,
                'move_id': effect.move_id.id if effect.move_id else False,
                'move_line_id': False,
                'reference': _('Pendiente de %s') % effect.name,
                'invoice_reference': effect.invoice_reference,
                'due_date': payment_date,
                'effect_type': 'effect',
                'bank_journal_id': effect.bank_journal_id.id if effect.bank_journal_id else False,
                'partner_bank_id': effect.partner_bank_id.id if effect.partner_bank_id else False,
                'payment_direction': effect.payment_direction,
                'amount': pending,
                'currency_id': effect.currency_id.id,
                'state': 'pending',
                'is_container': True,
                'is_portfolio_effect': True,
                'container_group_id': effect.group_id.id,
                'container_remittance_id': False,
                'cartera_number': effect.group_id.cartera_number,
                'active': True,
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
        result = super().action_create_payments()

        active_line_ids = self.env.context.get('active_ids', [])
        effects = self.env['account.effect'].search([
            ('is_container', '=', False),
            ('move_line_id', 'in', active_line_ids),
        ])
        payment_date = self.payment_date or fields.Date.context_today(self)
        effects._mark_paid_from_payment(payment_date)
        payment = self.effect_id._get_reconciled_payment() if self.effect_id else effects.mapped(lambda e: e._get_reconciled_payment())[:1]
        if payment:
            partial_effects = effects.filtered(lambda e: e.move_line_id and not e.move_line_id.reconciled and e.amount_pending < e.amount)
            partial_effects.write({'payment_id': payment.id})
        self._create_partial_portfolio_effects(effects, payment_date)

        if self.effect_expenses or self.effect_commissions:
            adjustment = self._create_effect_adjustment_entry(payment)
            if adjustment:
                effects.write({'adjustment_move_id': adjustment.id})

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
                if payment:
                    self._create_container_payment_history(payment, effects, 'remittance', remittance)
        if group_id:
            group = self.env['account.effect.group'].browse(group_id).exists()
            if group and payment:
                self._create_container_payment_history(payment, effects, 'group', group)
        return result
