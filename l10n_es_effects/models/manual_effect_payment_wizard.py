from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountEffectManualPaymentWizard(models.TransientModel):
    """Unified settlement form for every individual cartera effect.

    Invoice-backed and manually-created customer/supplier effects all use this
    same form and the same payment-document selector. Groupings and remittances
    retain their collective settlement flow because they settle consolidated
    accounting lines rather than one individual effect.
    """
    _name = 'account.effect.manual.payment.wizard'
    _description = 'Saldar efecto'

    effect_id = fields.Many2one('account.effect', string='Efecto', required=True, readonly=True)
    partner_id = fields.Many2one(related='effect_id.partner_id', string='Cliente / proveedor', readonly=True)
    company_id = fields.Many2one(related='effect_id.company_id', readonly=True)
    company_type = fields.Selection(related='effect_id.company_type', readonly=True)
    manual_account_id = fields.Many2one(related='effect_id.manual_account_id', string='Cuenta del efecto', readonly=True)
    currency_id = fields.Many2one(related='effect_id.currency_id', readonly=True)
    amount = fields.Monetary(string='Importe a saldar', required=True, currency_field='currency_id')
    amount_pending = fields.Monetary(string='Pendiente máximo', compute='_compute_amount_pending', currency_field='currency_id')
    payment_date = fields.Date(string='Fecha de pago', required=True, default=fields.Date.context_today)
    communication = fields.Char(string='Circular / Concepto')
    payment_document_id = fields.Many2one('account.effect.payment.document', string='Documento de pago', required=True)
    available_payment_document_ids = fields.Many2many(
        'account.effect.payment.document', compute='_compute_available_payment_documents', compute_sudo=True,
    )
    journal_id = fields.Many2one(
        'account.journal', string='Diario bancario', required=True,
        domain="[('company_id', '=', company_id), ('type', 'in', ('bank', 'cash')), ('default_account_id', '!=', False)]",
    )
    effect_balance = fields.Boolean(string='Cuadre del efecto', default=False)
    effect_expenses = fields.Monetary(string='Gastos', currency_field='currency_id', default=0.0)
    expense_account_id = fields.Many2one(
        'account.account', string='Cuenta de gastos',
        domain="[('deprecated', '=', False), ('company_ids', 'in', company_id)]",
    )
    effect_commissions = fields.Monetary(string='Comisiones', currency_field='currency_id', default=0.0)
    commission_account_id = fields.Many2one(
        'account.account', string='Cuenta de comisiones',
        domain="[('deprecated', '=', False), ('company_ids', 'in', company_id)]",
    )
    group_bank_entries = fields.Boolean(string='Agrupar apuntes en banco', default=False)

    @api.depends('effect_id', 'effect_id.payment_direction', 'effect_id.company_type')
    def _compute_available_payment_documents(self):
        # Identical selector for customer and supplier effects. The remesable
        # restriction is intentionally reserved for the remittance wizard.
        documents = self.env['account.effect.payment.document'].sudo().search(
            [('active', '=', True)], order='code, id'
        )
        for wizard in self:
            wizard.available_payment_document_ids = documents

    @api.depends(
        'effect_id', 'effect_id.amount', 'effect_id.state',
        'effect_id.move_line_id.amount_residual',
        'effect_id.move_line_id.amount_residual_currency',
        'effect_id.payment_history_ids.amount',
        'effect_id.payment_history_ids.operation_type',
        'effect_id.payment_history_ids.move_id.state',
        'effect_id.payment_history_ids.is_reversed',
    )
    def _compute_amount_pending(self):
        for wizard in self:
            wizard.amount_pending = wizard.effect_id._cartera_pending_amount() if wizard.effect_id else 0.0

    @api.model
    def default_get(self, fields_list):
        vals = super().default_get(fields_list)
        effect_id = self.env.context.get('default_effect_id') or self.env.context.get('effect_id')
        effect = self.env['account.effect'].browse(effect_id).exists() if effect_id else self.env['account.effect']
        if not effect:
            return vals
        vals.update({
            'effect_id': effect.id,
            'amount': effect._cartera_pending_amount(),
            'payment_date': fields.Date.context_today(self),
            'communication': effect.reference or _('Efecto nº %s') % (effect.cartera_number or effect.name),
        })
        documents = self.env['account.effect.payment.document'].sudo().search(
            [('active', '=', True)], order='code, id'
        )
        preferred = documents.filtered(lambda item: item.code == 'TR')[:1] or documents[:1]
        if preferred:
            vals['payment_document_id'] = preferred.id
        if 'journal_id' in fields_list:
            journal = effect.bank_journal_id
            if not journal or journal.company_id != effect.company_id or not journal.default_account_id:
                journal = self.env['account.journal'].search([
                    ('company_id', '=', effect.company_id.id),
                    ('type', 'in', ('bank', 'cash')),
                    ('default_account_id', '!=', False),
                ], order='type, sequence, id', limit=1)
            if journal:
                vals['journal_id'] = journal.id
        if 'expense_account_id' in fields_list or 'commission_account_id' in fields_list:
            account_626 = self._find_account_by_code('626', effect.company_id)
            if account_626:
                vals.setdefault('expense_account_id', account_626.id)
                vals.setdefault('commission_account_id', account_626.id)
        return vals

    @api.model
    def _find_account_by_code(self, code, company):
        accounts = self.env['account.account'].search([
            ('code', '=like', code + '%'),
            ('company_ids', 'in', company.id),
            ('deprecated', '=', False),
        ], order='code, id')
        return accounts.filtered(lambda account: account.code == code)[:1] or accounts[:1]

    @api.onchange('effect_balance')
    def _onchange_effect_balance(self):
        for wizard in self:
            code = '769' if wizard.effect_balance else '626'
            account = wizard._find_account_by_code(code, wizard.company_id) if wizard.company_id else False
            if account:
                wizard.expense_account_id = account

    def _create_adjustment_entry(self, is_receipt):
        self.ensure_one()
        if not self.effect_expenses and not self.effect_commissions:
            return self.env['account.move']
        journal = self.journal_id
        bank_account = journal.default_account_id
        if not bank_account:
            raise UserError(_('El diario %s no tiene una cuenta de liquidez configurada.') % journal.display_name)
        if journal.type not in ('bank', 'cash'):
            raise UserError(_('El diario utilizado para saldar debe ser de banco o caja.'))
        if self.effect_expenses < 0 or self.effect_commissions < 0:
            raise UserError(_('Los gastos y las comisiones no pueden ser negativos.'))
        entries = []
        for amount, account in (
            (self.effect_expenses, self.expense_account_id),
            (self.effect_commissions, self.commission_account_id),
        ):
            if not amount:
                continue
            # Expense and commission accounts do not need reconciliation; they
            # must simply be active and belong to the effect company.
            if not account or account.deprecated:
                raise UserError(_('Selecciona una cuenta de gastos/comisiones activa.'))
            if self.company_id not in account.company_ids:
                raise UserError(_('La cuenta %s no pertenece a la compañía del efecto.') % account.display_name)
            entries.append((amount, account))
        label = self.communication or _('Liquidación de cartera')
        lines = []
        total = sum(amount for amount, _account in entries)
        for amount, account in entries:
            lines.append((0, 0, {
                'name': label,
                'account_id': account.id,
                'partner_id': self.partner_id.id,
                'debit': amount if is_receipt else 0.0,
                'credit': amount if not is_receipt else 0.0,
            }))
            if not self.group_bank_entries:
                lines.append((0, 0, {
                    'name': label,
                    'account_id': bank_account.id,
                    'debit': amount if not is_receipt else 0.0,
                    'credit': amount if is_receipt else 0.0,
                }))
        if self.group_bank_entries:
            lines.append((0, 0, {
                'name': label,
                'account_id': bank_account.id,
                'debit': total if not is_receipt else 0.0,
                'credit': total if is_receipt else 0.0,
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

    def _create_portfolio_continuation(self, effect, root_effect, remaining_amount):
        """Create the pending tranche after a partial settlement of a chain row."""
        self.ensure_one()
        remaining_amount = effect.currency_id.round(remaining_amount)
        if effect.currency_id.is_zero(remaining_amount):
            return self.env['account.effect']
        signed_amount = remaining_amount if effect.payment_direction == 'receive' else -remaining_amount
        continuation = self.env['account.effect'].create({
            'company_id': effect.company_id.id,
            'company_type': effect.company_type,
            'partner_id': effect.partner_id.id if effect.partner_id else False,
            'move_id': root_effect.move_id.id if root_effect.move_id else (effect.move_id.id if effect.move_id else False),
            'move_line_id': False,
            'reference': effect.reference or False,
            'invoice_reference': effect.invoice_reference,
            'due_date': self.payment_date,
            'effect_type': 'effect',
            'bank_journal_id': effect.bank_journal_id.id if effect.bank_journal_id else False,
            'partner_bank_id': effect.partner_bank_id.id if effect.partner_bank_id else False,
            'payment_direction': effect.payment_direction,
            'amount': signed_amount,
            'currency_id': effect.currency_id.id,
            'state': 'pending',
            'is_container': False,
            'is_portfolio_effect': False,
            'portfolio_chain_id': root_effect.id,
            'cartera_number': effect.cartera_number,
            'active': True,
        })
        continuation._log_situation('pending', _('Saldo pendiente tras el pago parcial de %s') % effect.name)
        return continuation

    def action_create_payment(self):
        self.ensure_one()
        effect = self.effect_id.exists()
        if not effect or effect.is_container:
            raise UserError(_('Selecciona un efecto individual.'))
        if effect.group_id or effect.remittance_id:
            raise UserError(_('Los efectos agrupados o remesados deben saldarse desde su agrupación o remesa.'))
        if effect.state not in ('pending', 'grouped', 'remitted'):
            raise UserError(_('Solo se pueden saldar efectos pendientes.'))
        if effect.move_id and effect.move_id.state != 'posted':
            raise UserError(_('La factura o asiento de origen debe estar contabilizado.'))
        if not self.payment_document_id or not self.payment_document_id.active:
            raise UserError(_('Selecciona un documento de pago activo.'))
        currency = effect.currency_id
        pending = effect._cartera_pending_amount()
        if currency.is_zero(self.amount) or self.amount < 0:
            raise UserError(_('El importe debe ser mayor que cero.'))
        if currency.compare_amounts(self.amount, pending) > 0:
            raise UserError(_('El importe no puede superar el pendiente del efecto (%s).') % pending)
        if self.effect_expenses < 0 or self.effect_commissions < 0:
            raise UserError(_('Los gastos y las comisiones no pueden ser negativos.'))
        if self.effect_expenses and not self.expense_account_id:
            raise UserError(_('Indica la cuenta de gastos.'))
        if self.effect_commissions and not self.commission_account_id:
            raise UserError(_('Indica la cuenta de comisiones.'))
        pending_before_payment = pending

        source = effect.move_line_id
        root_effect = effect.portfolio_chain_id or effect
        if not source and root_effect != effect:
            source = root_effect.move_line_id
        had_source_link = bool(source)
        if (not source or source.reconciled or source.move_id.state != 'posted') and root_effect.opening_move_id:
            source = root_effect._ensure_manual_open_item_line()
        if source and (source.reconciled or source.move_id.state != 'posted'):
            source = self.env['account.move.line']
        if had_source_link and not source:
            raise UserError(_('El apunte contable de origen ya no tiene saldo pendiente. Comprueba el efecto antes de registrar otro pago.'))
        if not source and not effect.manual_account_id:
            raise UserError(_('El efecto no tiene un apunte de origen ni una cuenta destino conciliable.'))
        account = source.account_id if source else effect.manual_account_id
        if not account.reconcile:
            raise UserError(_('La cuenta %s no permite conciliación.') % account.display_name)
        partner = (source.partner_id if source else False) or effect.partner_id
        if source and effect.manual_account_id and effect.manual_account_id != account:
            raise UserError(_('La cuenta del efecto no coincide con el apunte contable de origen.'))
        if source and source.partner_id and effect.partner_id and source.partner_id != effect.partner_id:
            raise UserError(_('El apunte contable pertenece a un tercero distinto del efecto.'))
        if source:
            source_residual = (
                source.amount_residual_currency
                if source.currency_id and source.currency_id != effect.company_id.currency_id
                else source.amount_residual
            )
            is_receipt = source_residual > 0
            if currency.compare_amounts(self.amount, abs(source_residual)) > 0:
                raise UserError(_('El importe supera el saldo que todavía queda abierto en el apunte contable (%s).') % abs(source_residual))
        else:
            is_receipt = effect.payment_direction == 'receive'
        if not partner:
            raise UserError(_('El efecto necesita un cliente o proveedor.'))

        journal = self.journal_id
        if not journal or journal.company_id != effect.company_id or journal.type not in ('bank', 'cash') or not journal.default_account_id:
            raise UserError(_('Selecciona un diario bancario o de caja con cuenta de liquidez de la misma compañía.'))
        company_currency = effect.company_id.currency_id
        amount_company = currency._convert(
            self.amount, company_currency, effect.company_id, self.payment_date, round=True,
        ) if currency != company_currency else self.amount
        balance_debit = 0.0 if is_receipt else amount_company
        balance_credit = amount_company if is_receipt else 0.0
        balance_currency = -self.amount if is_receipt else self.amount
        bank_debit = amount_company if is_receipt else 0.0
        bank_credit = 0.0 if is_receipt else amount_company
        communication = self.communication or effect.reference or _('Efecto nº %s') % effect.name

        payment = self.env['account.payment']
        move = self.env['account.move']
        payment_line = self.env['account.move.line']
        valid_payment_accounts = payment._get_valid_payment_account_types()

        # For invoice-backed receivable/payable lines, keep the native Odoo
        # account.payment record and its Manual payment method. Standalone
        # manual effects (or custom balance accounts) continue to use a direct
        # journal entry because they have no invoice due line to reconcile.
        if source and account.account_type in valid_payment_accounts:
            payment_type = 'inbound' if is_receipt else 'outbound'
            method_lines = (
                journal.inbound_payment_method_line_ids
                if payment_type == 'inbound'
                else journal.outbound_payment_method_line_ids
            )
            manual_method = method_lines.filtered(lambda line: line.code == 'manual')[:1]
            if not manual_method:
                raise UserError(_(
                    'El diario %(journal)s no tiene disponible el método técnico Manual para %(direction)s. '
                    'Actívalo en las líneas de método de pago del diario.'
                ) % {
                    'journal': journal.display_name,
                    'direction': _('cobros') if is_receipt else _('pagos'),
                })
            payment = self.env['account.payment'].with_context(skip_invoice_sync=True).create({
                'date': self.payment_date,
                'amount': self.amount,
                'payment_type': payment_type,
                'partner_type': effect.company_type,
                'memo': communication,
                'journal_id': journal.id,
                'company_id': effect.company_id.id,
                'currency_id': currency.id,
                'partner_id': partner.id,
                'payment_method_line_id': manual_method.id,
                'destination_account_id': account.id,
            })
            payment.with_context(skip_sale_auto_invoice_send=True).action_post()
            move = payment.move_id
            payment_line = move.line_ids.filtered(
                lambda line: line.account_id == account and line.partner_id == partner and not line.reconciled
            )[:1]
            if not payment_line:
                raise UserError(_('El pago de Odoo no ha generado la contrapartida contable del efecto.'))
            payment_line.write({
                'effect_id': effect.id,
                'effect_ids': [(4, effect.id)],
            })
            payment.with_context(cartera_internal_state_update=True).write({
                'cartera_settled': True,
                'cartera_effect_ids': [(4, effect.id)],
            })
        else:
            balance_debit = 0.0 if is_receipt else amount_company
            balance_credit = amount_company if is_receipt else 0.0
            balance_currency = -self.amount if is_receipt else self.amount
            bank_debit = amount_company if is_receipt else 0.0
            bank_credit = 0.0 if is_receipt else amount_company
            move = self.env['account.move'].create({
                'move_type': 'entry',
                'date': self.payment_date,
                'journal_id': journal.id,
                'ref': _('%s · Saldado') % communication,
                'line_ids': [
                    (0, 0, {
                        'name': communication,
                        'account_id': account.id,
                        'partner_id': partner.id,
                        'currency_id': currency.id,
                        'amount_currency': balance_currency,
                        'debit': balance_debit,
                        'credit': balance_credit,
                        'date_maturity': self.payment_date,
                        'effect_id': effect.id,
                        'effect_ids': [(4, effect.id)],
                    }),
                    (0, 0, {
                        'name': _('Banco · %s') % communication,
                        'account_id': journal.default_account_id.id,
                        'debit': bank_debit,
                        'credit': bank_credit,
                    }),
                ],
            })
            move.action_post()
            payment_line = move.line_ids.filtered(
                lambda line: line.account_id == account and line.effect_id == effect
            )[:1]
            if not payment_line:
                raise UserError(_('No se ha podido localizar la línea de liquidación del efecto.'))
        remaining_root = 0.0
        if source:
            (source | payment_line).filtered(lambda line: not line.reconciled).reconcile()
            source.invalidate_recordset(['amount_residual', 'amount_residual_currency', 'reconciled'])
            if root_effect != effect:
                remaining_root = root_effect._settlement_pending_amount()
                if currency.is_zero(remaining_root):
                    is_fully_paid = True
                elif currency.compare_amounts(remaining_root, pending_before_payment) < 0:
                    settled_part = pending_before_payment - remaining_root
                    signed_settled_part = settled_part if effect.payment_direction == 'receive' else -settled_part
                    effect.write({'amount': signed_settled_part, 'state': 'paid', 'paid_date': self.payment_date})
                    self._create_portfolio_continuation(effect, root_effect, remaining_root)
                    is_fully_paid = True
                else:
                    is_fully_paid = False
            else:
                is_fully_paid = source.reconciled or currency.is_zero(effect._settlement_pending_amount())
        else:
            is_fully_paid = currency.compare_amounts(self.amount, pending_before_payment) >= 0

        adjustment = self._create_adjustment_entry(is_receipt)
        vals = {}
        if is_fully_paid and effect.state != 'paid':
            vals.update({'state': 'paid', 'paid_date': self.payment_date})
            if payment:
                vals['payment_id'] = payment.id
        if adjustment:
            vals['adjustment_move_id'] = adjustment.id
        if vals:
            effect.write(vals)
        if is_fully_paid:
            effect._log_situation('paid', _('Efecto saldado mediante asiento %s') % move.name)
        else:
            effect._log_situation(effect.state, _('Pago parcial registrado mediante asiento %s') % move.name)

        self.env['account.effect.payment.history'].create({
            'effect_id': effect.id,
            'date': self.payment_date,
            'payment_id': payment.id if payment else False,
            'move_id': move.id,
            'journal_id': journal.id,
            'amount': currency.round(self.amount),
            'operation_type': 'paid',
            'payment_document_id': self.payment_document_id.id,
            'note': _('Liquidación contra la cuenta %s') % account.display_name,
        })
        return {'type': 'ir.actions.client', 'tag': 'reload'}
