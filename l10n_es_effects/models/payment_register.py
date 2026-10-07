from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountPaymentRegister(models.TransientModel):
    _inherit = 'account.payment.register'

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
        domain="[('deprecated', '=', False)]",
    )
    effect_commissions = fields.Monetary(
        string='Comisiones',
        currency_field='currency_id',
        default=0.0,
    )
    commission_account_id = fields.Many2one(
        'account.account',
        string='Cuenta de comisiones',
        domain="[('deprecated', '=', False)]",
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
            ('company_id', '=', company.id),
            ('deprecated', '=', False),
        ], order='code', limit=1)

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        effect_id = self.env.context.get('effect_id')
        if effect_id:
            effect = self.env['account.effect'].browse(effect_id).exists()
            if effect:
                vals['effect_id'] = effect.id
                vals['total_effect'] = effect.amount
                account_626 = self._find_account_by_code('626')
                if account_626:
                    vals['expense_account_id'] = account_626.id
                    vals['commission_account_id'] = account_626.id
        return vals

    def _validate_effect_options(self):
        self.ensure_one()
        if not self.effect_id:
            return
        if self.effect_expenses < 0 or self.effect_commissions < 0:
            raise UserError(_('Los gastos y las comisiones no pueden ser negativos.'))
        if self.effect_expenses and not self.expense_account_id:
            raise UserError(_('Indica la cuenta de gastos.'))
        if self.effect_commissions and not self.commission_account_id:
            raise UserError(_('Indica la cuenta de comisiones.'))

    def _create_effect_adjustment_entry(self, payment):
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
                    'name': self.communication or payment.name,
                    'account_id': account.id,
                    'partner_id': self.partner_id.id,
                    'debit': amount if self.payment_type == 'inbound' else 0.0,
                    'credit': amount if self.payment_type == 'outbound' else 0.0,
                }))
            lines.append((0, 0, {
                'name': self.communication or payment.name,
                'account_id': bank_account.id,
                'debit': total if self.payment_type == 'outbound' else 0.0,
                'credit': total if self.payment_type == 'inbound' else 0.0,
            }))
        else:
            for amount, account in line_specs:
                lines = [
                    (0, 0, {
                        'name': self.communication or payment.name,
                        'account_id': account.id,
                        'partner_id': self.partner_id.id,
                        'debit': amount if self.payment_type == 'inbound' else 0.0,
                        'credit': amount if self.payment_type == 'outbound' else 0.0,
                    }),
                    (0, 0, {
                        'name': self.communication or payment.name,
                        'account_id': bank_account.id,
                        'debit': amount if self.payment_type == 'outbound' else 0.0,
                        'credit': amount if self.payment_type == 'inbound' else 0.0,
                    }),
                ]
                move = self.env['account.move'].create({
                    'move_type': 'entry',
                    'date': self.payment_date,
                    'journal_id': journal.id,
                    'ref': self.communication or payment.name,
                    'line_ids': lines,
                })
                move.action_post()
                return move
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'date': self.payment_date,
            'journal_id': journal.id,
            'ref': self.communication or payment.name,
            'line_ids': lines,
        })
        move.action_post()
        return move

    def action_create_payments(self):
        self.ensure_one()
        self._validate_effect_options()
        result = super().action_create_payments()

        # The native payment is created/reconciled first. Only then create the
        # separate adjustment entry, preserving Odoo's standard payment flow.
        if self.effect_id and (self.effect_expenses or self.effect_commissions):
            payment = self.effect_id.move_line_id.reconciled_payment_ids[:1]
            if not payment:
                payment = self.effect_id.payment_id
            if payment:
                adjustment = self._create_effect_adjustment_entry(payment)
                if adjustment:
                    self.effect_id.write({'adjustment_move_id': adjustment.id})
        return result
