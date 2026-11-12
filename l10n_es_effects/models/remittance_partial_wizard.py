from datetime import date

from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountEffectRemittancePartialLine(models.TransientModel):
    _name = 'account.effect.remittance.partial.line'
    _description = 'Línea de saldado parcial de remesa'
    _order = 'due_date, id'

    wizard_id = fields.Many2one('account.effect.remittance.partial.wizard', required=True, ondelete='cascade')
    effect_id = fields.Many2one('account.effect', string='Efecto', readonly=True, ondelete='restrict')
    selected = fields.Boolean(string='Saldar', default=False)
    name = fields.Char(related='effect_id.name', string='Nº Efecto', readonly=True)
    reference = fields.Char(related='effect_id.reference', string='Concepto', readonly=True)
    due_date = fields.Date(related='effect_id.due_date', string='Vencimiento', readonly=True)
    partner_id = fields.Many2one(related='effect_id.partner_id', string='Empresa', readonly=True)
    amount = fields.Monetary(related='effect_id.amount', string='Total', readonly=True, currency_field='currency_id')
    amount_pending = fields.Monetary(string='Total pendiente', compute='_compute_amount_pending', currency_field='currency_id', readonly=True)
    settlement_amount = fields.Monetary(string='Importe a saldar', compute='_compute_amount_pending', currency_field='currency_id', readonly=True)
    currency_id = fields.Many2one(related='effect_id.currency_id', readonly=True)
    payment_state = fields.Selection(related='effect_id.payment_state', string='Estado del pago', readonly=True)

    @api.depends(
        'effect_id', 'effect_id.amount', 'effect_id.state', 'effect_id.active',
        'effect_id.move_line_id.amount_residual', 'effect_id.move_line_id.amount_residual_currency',
        'effect_id.move_line_id.reconciled', 'effect_id.group_id.grouping_move_id.state',
        'effect_id.group_id.payment_history_ids.type',
        'effect_id.group_id.payment_history_ids.allocation_line_ids.amount',
        'effect_id.group_id.payment_history_ids.allocation_line_ids.effect_id',
        'effect_id.remittance_id.payment_history_ids.type',
        'effect_id.remittance_id.payment_history_ids.allocation_line_ids.amount',
    )
    def _compute_amount_pending(self):
        for line in self:
            amount = line.effect_id._cartera_pending_amount() if line.effect_id else 0.0
            line.amount_pending = amount
            line.settlement_amount = amount


class AccountEffectRemittancePartialWizard(models.TransientModel):
    _name = 'account.effect.remittance.partial.wizard'
    _description = 'Saldado parcial de remesa'

    remittance_id = fields.Many2one('account.effect.remittance', readonly=True)
    group_id = fields.Many2one('account.effect.group', readonly=True)
    line_ids = fields.One2many('account.effect.remittance.partial.line', 'wizard_id', string='Efectos')
    selected_total = fields.Monetary(string='Total seleccionado', compute='_compute_selected_total', currency_field='currency_id', readonly=True)
    currency_id = fields.Many2one(related='remittance_id.currency_id', readonly=True)

    @api.depends('line_ids.selected', 'line_ids.effect_id', 'line_ids.effect_id.amount', 'line_ids.effect_id.state', 'line_ids.amount_pending')
    def _compute_selected_total(self):
        for wizard in self:
            wizard.selected_total = sum(
                line.effect_id._cartera_pending_amount() for line in wizard.line_ids.filtered(lambda item: item.selected and item.effect_id)
            )

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        remittance_id = self.env.context.get('default_remittance_id') or self.env.context.get('remittance_id')
        group_id = self.env.context.get('default_group_id') or self.env.context.get('group_id')
        effects = self.env['account.effect']
        if remittance_id:
            remittance = self.env['account.effect.remittance'].browse(remittance_id).exists()
            if remittance:
                vals['remittance_id'] = remittance.id
                effects = remittance.effect_ids.filtered(
                    lambda e: not e.is_container
                    and e.state in ('pending', 'grouped', 'remitted')
                    and not e.currency_id.is_zero(e._cartera_pending_amount())
                )
        elif group_id:
            group = self.env['account.effect.group'].browse(group_id).exists()
            if group:
                vals['group_id'] = group.id
                effects = group.effect_ids.filtered(
                    lambda e: not e.is_container
                    and e.state in ('grouped', 'pending', 'remitted')
                    and not e.currency_id.is_zero(e._cartera_pending_amount())
                )
        if 'line_ids' in fields_list:
            vals['line_ids'] = [(0, 0, {'effect_id': effect.id, 'selected': False}) for effect in effects]
        return vals

    def action_saldar(self):
        self.ensure_one()
        # The checkbox is persisted on the transient line before this button is
        # evaluated; only valid, still-pending effects can be selected.
        selected = self.line_ids.filtered(lambda line: line.selected and line.effect_id).mapped('effect_id').filtered(
            lambda e: e.state in ('pending', 'grouped', 'remitted') and not e.currency_id.is_zero(e._cartera_pending_amount())
        )
        if not selected:
            raise UserError(_('Selecciona al menos un efecto asociado pendiente de saldar.'))
        if self.remittance_id:
            return self.remittance_id._payment_register_action(selected, _('Saldar seleccionados'))
        if self.group_id:
            return self.group_id._payment_register_action(selected, _('Saldar seleccionados'))
        raise UserError(_('No se ha encontrado la remesa o agrupación de destino.'))


class AccountEffectRemittanceReturnLine(models.TransientModel):
    _name = 'account.effect.remittance.return.line'
    _description = 'Línea de devolución de remesa'
    _order = 'paid_date, id'

    wizard_id = fields.Many2one('account.effect.remittance.return.wizard', required=True, ondelete='cascade')
    effect_id = fields.Many2one('account.effect', string='Efecto', readonly=True, ondelete='restrict')
    selected = fields.Boolean(string='Devolver', default=False)
    name = fields.Char(related='effect_id.name', string='Nº Efecto', readonly=True)
    display_label = fields.Char(related='effect_id.display_label', string='Nombre', readonly=True)
    partner_id = fields.Many2one(related='effect_id.partner_id', string='Empresa', readonly=True)
    amount = fields.Monetary(compute='_compute_amount_returnable', string='Importe disponible para devolver', readonly=True, currency_field='currency_id')
    paid_date = fields.Date(related='effect_id.paid_date', string='Fecha de saldado', readonly=True)

    @api.depends('effect_id', 'wizard_id.remittance_id.payment_history_ids.type',
                 'wizard_id.remittance_id.payment_history_ids.allocation_line_ids.amount')
    def _compute_amount_returnable(self):
        for line in self:
            remittance = line.wizard_id.remittance_id
            line.amount = remittance._effect_returnable_amount(line.effect_id) if remittance and line.effect_id else 0.0
    currency_id = fields.Many2one(related='effect_id.currency_id', readonly=True)


class AccountEffectRemittanceReturnWizard(models.TransientModel):
    _name = 'account.effect.remittance.return.wizard'
    _description = 'Devolver efectos de remesa'

    remittance_id = fields.Many2one('account.effect.remittance', required=True, readonly=True)
    company_id = fields.Many2one(related='remittance_id.company_id', readonly=True)
    currency_id = fields.Many2one(related='remittance_id.currency_id', readonly=True)
    journal_id = fields.Many2one(
        'account.journal', string='Diario', required=True,
        domain="[('company_id', '=', company_id), ('type', 'in', ('bank', 'cash')), ('default_account_id', '!=', False)]",
    )
    payment_document_id = fields.Many2one('account.effect.payment.document', string='Documento de pago', required=True)
    available_payment_document_ids = fields.Many2many('account.effect.payment.document', compute='_compute_available_payment_documents')
    payment_date = fields.Date(string='Fecha de pago', required=True, default=fields.Date.context_today)
    communication = fields.Char(string='Circular / Concepto')
    total_effect = fields.Monetary(
        string='Total efecto', currency_field='currency_id',
        compute='_compute_total_effect', readonly=True,
    )
    effect_balance = fields.Boolean(string='Cuadre del efecto', default=False)
    effect_expenses = fields.Monetary(string='Gastos', currency_field='currency_id', default=0.0)
    expense_account_id = fields.Many2one(
        'account.account', string='Cuenta de gastos',
        domain="[('company_ids', 'in', company_id), ('deprecated', '=', False)]",
        check_company=True,
    )
    effect_commissions = fields.Monetary(string='Comisiones', currency_field='currency_id', default=0.0)
    commission_account_id = fields.Many2one(
        'account.account', string='Cuenta de comisiones',
        domain="[('company_ids', 'in', company_id), ('deprecated', '=', False)]",
        check_company=True,
    )
    group_bank_entries = fields.Boolean(string='Agrupar apuntes en banco', default=False)
    # These are the only two additional return options; they are independent.
    impute_expenses = fields.Boolean(string='Imputar gastos', default=False)
    create_new_effect = fields.Boolean(string='Crear nuevo efecto', default=False)

    @api.depends('remittance_id')
    def _compute_available_payment_documents(self):
        Document = self.env['account.effect.payment.document']
        for wizard in self:
            wizard.available_payment_document_ids = Document.search([
                ('active', '=', True), ('remesable', '=', True),
            ], order='code, id')

    @api.depends(
        'remittance_id', 'remittance_id.effect_ids',
        'remittance_id.payment_history_ids',
        'remittance_id.payment_history_ids.type',
        'remittance_id.payment_history_ids.allocation_line_ids.amount',
    )
    def _compute_total_effect(self):
        for wizard in self:
            remittance = wizard.remittance_id
            total = sum(
                remittance._effect_returnable_amount(effect)
                for effect in remittance.effect_ids.filtered(lambda item: not item.is_container)
            ) if remittance else 0.0
            wizard.total_effect = remittance.currency_id.round(total) if remittance else 0.0

    @api.model
    def _find_account_by_code(self, company, code):
        return self.env['account.account'].search([
            ('code', '=like', code + '%'),
            ('company_ids', 'in', company.id),
            ('deprecated', '=', False),
        ], order='code, id', limit=1)

    @api.onchange('effect_balance')
    def _onchange_effect_balance(self):
        for wizard in self:
            code = '769' if wizard.effect_balance else '626'
            account = wizard._find_account_by_code(wizard.company_id or self.env.company, code)
            if account:
                wizard.expense_account_id = account

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        vals.setdefault('payment_date', fields.Date.context_today(self))
        remittance_id = self.env.context.get('default_remittance_id') or self.env.context.get('remittance_id')
        remittance = self.env['account.effect.remittance'].browse(remittance_id).exists() if remittance_id else self.env['account.effect.remittance']
        if remittance:
            vals['remittance_id'] = remittance.id
            vals.setdefault('communication', remittance.reference or (_('Remesa nº %s') % remittance.cartera_number))
            journal = remittance.bank_journal_id.filtered(lambda item: item.default_account_id)
            if not journal:
                posted_histories = remittance.payment_history_ids.filtered(
                    lambda history: history.type == 'paid' and history.move_id.state == 'posted'
                ).sorted(key=lambda history: (history.date or date.min, history.id), reverse=True)
                for history in posted_histories:
                    journal = (history.payment_ids | history.payment_id).mapped('journal_id').filtered(
                        lambda item: item.company_id == remittance.company_id and item.default_account_id
                    )[:1]
                    if journal:
                        break
            if not journal:
                journal = self.env['account.journal'].search([
                    ('company_id', '=', remittance.company_id.id),
                    ('type', 'in', ('bank', 'cash')),
                    ('default_account_id', '!=', False),
                ], order='type, sequence, id', limit=1)
            if journal:
                vals['journal_id'] = journal.id
            documents = self.env['account.effect.payment.document'].search([
                ('active', '=', True), ('remesable', '=', True),
            ], order='code, id')
            preferred = documents.filtered(lambda item: item.code == 'TR')[:1] or documents[:1]
            if preferred:
                vals['payment_document_id'] = preferred.id
            account_626 = self._find_account_by_code(remittance.company_id, '626')
            if account_626:
                vals.setdefault('expense_account_id', account_626.id)
                vals.setdefault('commission_account_id', account_626.id)
        return vals

    def action_devolver(self):
        self.ensure_one()
        remittance = self.remittance_id
        effects = remittance.effect_ids.filtered(
            lambda effect: not effect.is_container
            and remittance.currency_id.compare_amounts(remittance._effect_returnable_amount(effect), 0.0) > 0
        )
        if not effects:
            raise UserError(_('No hay efectos con importes cobrados pendientes de devolución en esta remesa.'))
        return remittance._return_selected_effects(
            effects,
            journal=self.journal_id,
            impute_expenses=self.impute_expenses,
            effect_expenses=self.effect_expenses,
            expense_account=self.expense_account_id,
            effect_commissions=self.effect_commissions,
            commission_account=self.commission_account_id,
            create_new_effect=self.create_new_effect,
            payment_date=self.payment_date,
            communication=self.communication,
            group_bank_entries=self.group_bank_entries,
            payment_document_id=self.payment_document_id.id,
        )

