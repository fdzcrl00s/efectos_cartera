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

    @api.depends('effect_id', 'currency_id')
    def _compute_effect_options(self):
        for wizard in self:
            effect = wizard.effect_id
            wizard.total_effect = effect.amount if effect else wizard.amount

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
        if cartera_mode:
            account_626 = self._find_account_by_code('626')
            if account_626:
                vals['expense_account_id'] = account_626.id
                vals['commission_account_id'] = account_626.id
            if effect_id:
                effect = self.env['account.effect'].browse(effect_id).exists()
                if effect:
                    vals['effect_id'] = effect.id
                    vals['total_effect'] = effect.amount
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

        if self.effect_expenses or self.effect_commissions:
            payment = False
            if self.effect_id:
                payment = self.effect_id._get_reconciled_payment()
                if not payment:
                    payment = self.effect_id.payment_id
            adjustment = self._create_effect_adjustment_entry(payment)
            if adjustment and self.effect_id:
                self.effect_id.write({'adjustment_move_id': adjustment.id})

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
        return result
