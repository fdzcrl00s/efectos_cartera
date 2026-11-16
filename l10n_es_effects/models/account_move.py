from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountMove(models.Model):
    _inherit = 'account.move'

    effect_group_ids = fields.Many2many(
        'account.effect.group', 'account_move_effect_group_rel', 'move_id', 'group_id',
        string='Agrupaciones de cartera', readonly=True, copy=False,
    )
    effect_remittance_id = fields.Many2one(
        'account.effect.remittance', string='Remesa de cartera', readonly=True, copy=False,
    )
    effect_ids = fields.One2many('account.effect', 'move_id', string='Efectos', readonly=True)
    cartera_effect_ids = fields.One2many('account.effect', 'origin_invoice_id', string='Efectos de cartera vinculados', readonly=True)
    payment_state = fields.Selection(
        selection_add=[('returned', 'Devuelto')],
        ondelete={'returned': 'set not_paid'},
    )
    # Odoo 18 exposes payment_state to invoice lists through the separate
    # status_in_payment selection. Extend it as well, otherwise the core
    # _compute_status_in_payment can return a value that its own selection
    # does not recognize when an invoice has a returned cartera effect.
    status_in_payment = fields.Selection(
        selection_add=[('returned', 'Devuelto')],
        ondelete={'returned': 'set not_paid'},
    )
    effect_count = fields.Integer(compute='_compute_effect_count', string='Efectos')


    @api.depends(
        'amount_residual', 'move_type', 'state', 'company_id', 'reconciled_payment_ids.state',
        'cartera_effect_ids', 'cartera_effect_ids.state', 'cartera_effect_ids.amount',
        'cartera_effect_ids.amount_pending', 'cartera_effect_ids.active',
        'cartera_effect_ids.payment_state',
    )
    def _compute_payment_state(self):
        # Recalculate the native state first, then override only invoices represented
        # in cartera. Remitted/grouped is a transfer of the receivable, not a payment.
        super()._compute_payment_state()
        for move in self.filtered(lambda item: item.is_invoice(include_receipts=True)):
            effects = move.cartera_effect_ids.filtered(
                lambda item: item.active and not item.is_container and not item.is_portfolio_effect
            )
            if not effects:
                continue

            returned_effects = effects.filtered(lambda item: item.state == 'returned')
            current_effects = effects.filtered(lambda item: item.state not in ('returned', 'uncollectible'))
            pending_effects = current_effects.filtered(
                lambda item: item.state in ('pending', 'grouped', 'remitted')
                and not item.currency_id.is_zero(item._cartera_pending_amount())
            )
            paid_effects = current_effects.filtered(lambda item: item.state == 'paid')
            partial_paid_amount = sum(
                max(0.0, abs(item.amount) - item._cartera_pending_amount())
                for item in current_effects
            )
            invoice_total = abs(move.amount_total)
            currency = move.currency_id or move.company_currency_id
            is_fully_paid = currency.compare_amounts(partial_paid_amount, invoice_total) >= 0

            if is_fully_paid:
                move.payment_state = 'paid'
            elif returned_effects:
                # A returned instrument keeps the invoice visibly unpaid until
                # the replacement effect(s) cover the full invoice amount.
                move.payment_state = 'returned'
            elif pending_effects and partial_paid_amount > 0:
                move.payment_state = 'partial'
            elif pending_effects:
                move.payment_state = 'not_paid'
            elif paid_effects or partial_paid_amount > 0:
                move.payment_state = 'partial'
            else:
                move.payment_state = 'not_paid'

    @api.depends('effect_ids')
    def _compute_effect_count(self):
        for move in self:
            move.effect_count = len(move.effect_ids)

    def action_open_effects(self):
        self.ensure_one()
        return {
            'name': 'Cartera', 'type': 'ir.actions.act_window', 'res_model': 'account.effect',
            'view_mode': 'list,form', 'domain': ['|', ('move_id', '=', self.id), ('origin_invoice_id', '=', self.id)],
            'context': {'default_move_id': self.id, 'default_company_type': 'customer' if self.move_type in ('out_invoice', 'out_refund') else 'supplier'},
        }

    def action_generate_effects_from_existing_invoices(self):
        """Create cartera effects for the open payment terms of selected invoices and credit notes.

        The action is intentionally atomic: all selected moves and all candidate
        lines are validated before any effect is created. The method never commits
        manually; any exception raised during create() aborts the RPC transaction
        and rolls back every effect created by this batch.
        """
        if not self:
            raise UserError(_('Selecciona al menos una factura, factura rectificativa o documento de proveedor.'))

        supported_move_types = ('out_invoice', 'in_invoice', 'out_refund', 'in_refund')
        unsupported = self.filtered(lambda move: move.move_type not in supported_move_types)
        if unsupported:
            raise UserError(_(
                'La generación de efectos solo admite facturas de cliente y facturas de proveedor. '
                'No se han procesado documentos de otro tipo: %s'
            ) % ', '.join(unsupported.mapped('display_name')))

        not_posted = self.filtered(lambda move: move.state != 'posted')
        if not_posted:
            raise UserError(_(
                'Todas las facturas seleccionadas deben estar contabilizadas. '
                'Documentos pendientes de contabilizar: %s'
            ) % ', '.join(not_posted.mapped('display_name')))

        unavailable_company = self.filtered(lambda move: move.company_id not in self.env.companies)
        if unavailable_company:
            raise UserError(_(
                'No tienes activas todas las compañías de las facturas seleccionadas: %s'
            ) % ', '.join(unavailable_company.mapped('display_name')))

        missing_partner = self.filtered(lambda move: not move.partner_id)
        if missing_partner:
            raise UserError(_(
                'No se puede generar cartera para documentos sin cliente/proveedor: %s'
            ) % ', '.join(missing_partner.mapped('display_name')))

        # Lock the invoice payment-term rows before reading residuals. This
        # serializes concurrent batch runs and avoids creating two effects for
        # the same accounting maturity. The SQL unique constraint on
        # account.effect.move_line_id remains the final integrity safeguard.
        term_lines = self.env['account.move.line']
        for move in self:
            account_type = 'asset_receivable' if move.move_type in ('out_invoice', 'out_refund') else 'liability_payable'
            move_term_lines = move.line_ids.filtered(
                lambda line: line.display_type == 'payment_term'
                and line.account_type == account_type
            )
            if not move_term_lines:
                raise UserError(_(
                    'El documento %s no contiene líneas contables de vencimiento de cliente/proveedor. '
                    'No se ha creado ningún efecto.'
                ) % move.display_name)
            term_lines |= move_term_lines

        if term_lines:
            self.env.cr.execute(
                'SELECT id FROM account_move_line WHERE id = ANY(%s) ORDER BY id FOR UPDATE',
                [term_lines.ids],
            )
            term_lines.invalidate_recordset([
                'reconciled', 'amount_residual', 'amount_residual_currency',
                'date_maturity', 'account_id', 'partner_id', 'currency_id',
            ])

        Effect = self.env['account.effect']
        existing_effects = Effect.search([('move_line_id', 'in', term_lines.ids)]) if term_lines else Effect
        existing_by_line = {effect.move_line_id.id: effect for effect in existing_effects}

        effects_to_create = []
        effects_to_update = []
        already_linked_count = 0
        updated_effect_count = 0
        paid_invoice_count = 0

        # Build and validate the complete batch first. Nothing is written until
        # every selected invoice and every open maturity has passed validation.
        for move in self:
            company_type = 'customer' if move.move_type in ('out_invoice', 'out_refund') else 'supplier'
            expected_account_type = 'asset_receivable' if company_type == 'customer' else 'liability_payable'
            open_line_count = 0
            invoice_had_existing_effect = False

            invoice_lines = term_lines.filtered(lambda line: line.move_id == move)
            for line in invoice_lines:
                currency = line.currency_id or move.currency_id
                if not currency:
                    raise UserError(_(
                        'No se ha podido determinar la moneda del vencimiento de %s. '
                        'No se ha creado ningún efecto.'
                    ) % move.display_name)

                signed_residual = (
                    line.amount_residual_currency
                    if line.currency_id and line.currency_id != move.company_currency_id
                    else line.amount_residual
                )
                residual = abs(signed_residual)
                existing = existing_by_line.get(line.id)
                if existing:
                    invoice_had_existing_effect = True
                    already_linked_count += 1
                    if not currency.is_zero(residual):
                        expected_direction = 'receive' if signed_residual > 0 else 'send'
                        is_safe_to_correct = (
                            existing.move_id == move
                            and existing.state == 'pending'
                            and not existing.group_id
                            and not existing.remittance_id
                            and not existing.is_container
                            and not existing.is_portfolio_effect
                            and not existing.payment_id
                            and not existing.payment_history_ids
                        )
                        amount_is_wrong = currency.compare_amounts(existing.amount, signed_residual) != 0
                        direction_is_wrong = existing.payment_direction != expected_direction
                        if amount_is_wrong or direction_is_wrong:
                            if not is_safe_to_correct:
                                raise UserError(_(
                                    'El efecto existente %(effect)s de %(invoice)s tiene un importe o dirección incorrectos, '
                                    'pero ya está agrupado, remesado o tiene movimientos asociados. Deshaz primero esas operaciones.'
                                ) % {'effect': existing.display_name, 'invoice': move.display_name})
                            effects_to_update.append((existing, signed_residual, expected_direction))
                    continue

                if currency.is_zero(residual):
                    continue

                open_line_count += 1
                if line.reconciled:
                    raise UserError(_(
                        'El vencimiento %(line)s del documento %(invoice)s figura como conciliado, '
                        'pero conserva un saldo pendiente. No se ha creado ningún efecto.'
                    ) % {'line': line.display_name, 'invoice': move.display_name})

                if line.account_id.account_type != expected_account_type:
                    raise UserError(_(
                        'La cuenta contable del vencimiento del documento %(invoice)s no es una cuenta de '
                        '%(kind)s. No se ha creado ningún efecto.'
                    ) % {
                        'invoice': move.display_name,
                        'kind': _('cliente') if company_type == 'customer' else _('proveedor'),
                    })
                if line.account_id.deprecated or not line.account_id.reconcile:
                    raise UserError(_(
                        'La cuenta %(account)s del vencimiento del documento %(invoice)s está inactiva '
                        'o no permite conciliación. No se ha creado ningún efecto.'
                    ) % {'account': line.account_id.display_name, 'invoice': move.display_name})

                partner = line.partner_id or move.partner_id
                if not partner:
                    raise UserError(_(
                        'No se ha podido determinar el cliente/proveedor del vencimiento de %s. '
                        'No se ha creado ningún efecto.'
                    ) % move.display_name)

                due_date = line.date_maturity or move.invoice_date_due or move.invoice_date or move.date
                if not due_date:
                    raise UserError(_(
                        'No se ha podido determinar la fecha de vencimiento de %s. '
                        'No se ha creado ningún efecto.'
                    ) % move.display_name)

                effects_to_create.append({
                    'company_id': move.company_id.id,
                    'partner_id': partner.id,
                    'company_type': company_type,
                    'payment_direction': 'receive' if signed_residual > 0 else 'send',
                    'move_id': move.id,
                    'move_line_id': line.id,
                    'reference': move.name or move.ref or move.display_name,
                    'due_date': due_date,
                    'amount': signed_residual,
                    'currency_id': currency.id,
                })

            # A fully paid invoice is a valid no-op: it has no outstanding
            # maturity to put into cartera. An invoice with open lines is
            # either imported now or already represented by existing effects.
            if open_line_count == 0 and not invoice_had_existing_effect:
                paid_invoice_count += 1

        # Create by company so company-dependent defaults (notably the bank
        # journal) are resolved against the invoice company. Every call still
        # belongs to this same Odoo RPC transaction. Do not catch creation
        # exceptions or commit: a failure in any company rolls back the batch.
        created_effects = Effect.browse()
        values_by_company = {}
        for values in effects_to_create:
            values_by_company.setdefault(values['company_id'], []).append(values)
        for company_id, company_values in values_by_company.items():
            company = self.env['res.company'].browse(company_id)
            created_effects |= Effect.with_company(company).create(company_values)

        # Correct legacy effects produced by earlier builds, but only while they
        # are untouched and still pending. Never rewrite an amount after grouping,
        # remittance, payment or return because those operations have accounting
        # consequences. This remains part of the same atomic transaction.
        for existing, signed_amount, direction in effects_to_update:
            existing.write({'amount': signed_amount, 'payment_direction': direction})
            updated_effect_count += 1

        message = _(
            '%(created)s efectos creados. %(updated)s efectos existentes corregidos. '
            '%(existing)s vencimientos ya tenían efecto. %(paid)s documentos sin saldo pendiente.'
        ) % {
            'created': len(created_effects),
            'updated': updated_effect_count,
            'existing': already_linked_count - updated_effect_count,
            'paid': paid_invoice_count,
        }
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': _('Generación de cartera completada'),
                'message': message,
                'type': 'success',
                'sticky': False,
            },
        }

    def action_post(self):
        # The OCA account_journal_general_sequence addon computes entry_number
        # during posting and expects every journal to have entry_number_sequence_id.
        # Payments use the bank/cash journal, which may not yet have that stored
        # field initialized although the invoice journal already has the shared
        # company sequence. Reuse/initialize it before OCA computes entry_number.
        if 'entry_number_sequence_id' in self.env['account.journal']._fields:
            remittance_model = self.env['account.effect.remittance']
            for journal in self.mapped('journal_id').filtered(lambda item: item):
                remittance_model._ensure_journal_entry_number_sequence(journal)

        result = super().action_post()
        Effect = self.env['account.effect']
        supported_move_types = ('out_invoice', 'in_invoice', 'out_refund', 'in_refund')
        for move in self:
            if move.state != 'posted' or move.move_type not in supported_move_types:
                continue

            is_customer_document = move.move_type in ('out_invoice', 'out_refund')
            expected_account_type = 'asset_receivable' if is_customer_document else 'liability_payable'
            company_type = 'customer' if is_customer_document else 'supplier'
            lines = move.line_ids.filtered(lambda line:
                line.account_type == expected_account_type
                and line.display_type == 'payment_term'
                and not line.reconciled
            )
            for line in lines:
                if Effect.search_count([('move_line_id', '=', line.id)]):
                    continue

                currency = line.currency_id or move.currency_id
                signed_residual = (
                    line.amount_residual_currency
                    if line.currency_id and line.currency_id != move.company_currency_id
                    else line.amount_residual
                )
                if not currency or currency.is_zero(signed_residual):
                    continue

                # The balance sign, not merely the document type, determines
                # whether cash is received or sent. This is essential for
                # customer credit notes and supplier refunds:
                #   customer invoice  + receivable => receive
                #   customer refund   - receivable => send
                #   supplier bill     - payable    => send
                #   supplier refund   + payable    => receive
                payment_direction = 'receive' if signed_residual > 0 else 'send'
                Effect.with_company(move.company_id).create({
                    'company_id': move.company_id.id,
                    'partner_id': line.partner_id.id or move.partner_id.id,
                    'company_type': company_type,
                    'payment_direction': payment_direction,
                    'move_id': move.id,
                    'move_line_id': line.id,
                    'reference': move.name or move.ref or '',
                    'due_date': line.date_maturity or move.invoice_date_due or move.invoice_date or move.date,
                    'amount': signed_residual,
                    'currency_id': currency.id,
                })
        return result

    def _reverse_cartera_payment_entry(self, reversal_date=None, note=None):
        """Reverse a cartera payment move and restore its open counterpart balances.

        The liquidity line is deliberately left for bank reconciliation. Receivable/payable or other reconcilable balance-account partial reconciliations
        are removed before the reversal is posted; the original and reversal balance
        lines are then reconciled with each other, restoring the prior open balance.
        """
        self.ensure_one()
        if self.state != 'posted':
            raise UserError(_('Solo se pueden anular asientos de cartera publicados.'))

        liquidity_account = self.journal_id.default_account_id
        liquidity_lines = self.line_ids.filtered(lambda line: line.account_id.account_type == 'asset_cash' or (liquidity_account and line.account_id == liquidity_account))
        counterpart_lines = self.line_ids.filtered(
            lambda line: line.account_id.reconcile and line not in liquidity_lines
        )
        if not counterpart_lines:
            raise UserError(_('El asiento no contiene líneas de balance conciliables para revertir.'))

        if any(line.matched_debit_ids or line.matched_credit_ids for line in liquidity_lines):
            raise UserError(_(
                'El asiento está conciliado con extractos bancarios. Deshaz primero la conciliación bancaria y vuelve a anular el pago.'
            ))

        # Remove both full and partial matches to the source effects/group balances.
        matched_counterparts = counterpart_lines.filtered(
            lambda line: line.matched_debit_ids or line.matched_credit_ids
        )
        if matched_counterparts:
            matched_counterparts.remove_move_reconcile()

        reversal = self._reverse_moves(default_values_list=[{
            'date': reversal_date or fields.Date.context_today(self),
            'ref': (self.ref or self.name or _('Liquidación de cartera')) + ' - ' + (note or _('Anulación')),
        }], cancel=False)
        reversal.action_post()

        reversal_liquidity_account = reversal.journal_id.default_account_id
        reversal_liquidity_lines = reversal.line_ids.filtered(lambda line: line.account_id.account_type == 'asset_cash' or (reversal_liquidity_account and line.account_id == reversal_liquidity_account))
        reversed_counterparts = reversal.line_ids.filtered(
            lambda line: line.account_id.reconcile and line not in reversal_liquidity_lines
        )
        company_currency = self.company_id.currency_id
        # Do not pair lines one by one: one payment can contain several effects
        # for the same partner/account, and the reversal can legally split or
        # regroup those lines. Reconcile each complete account/partner/currency
        # bucket instead. This also avoids pairing the wrong duplicate line.
        bucket_keys = set(
            (line.account_id.id, line.partner_id.id or False, line.currency_id.id or False)
            for line in (counterpart_lines | reversed_counterparts)
        )
        for account_id, partner_id, currency_id in bucket_keys:
            original_bucket = counterpart_lines.filtered(
                lambda line: line.account_id.id == account_id
                and (line.partner_id.id or False) == partner_id
                and (line.currency_id.id or False) == currency_id
            )
            reversal_bucket = reversed_counterparts.filtered(
                lambda line: line.account_id.id == account_id
                and (line.partner_id.id or False) == partner_id
                and (line.currency_id.id or False) == currency_id
            )
            if not original_bucket or not reversal_bucket:
                account = self.env['account.account'].browse(account_id)
                partner = self.env['res.partner'].browse(partner_id)
                raise UserError(_(
                    'No se ha podido localizar la contrapartida completa de la reversión '
                    '(%s, %s). La anulación se ha cancelado para no dejar saldos abiertos.'
                ) % (account.display_name, partner.display_name or ''))

            bucket = original_bucket | reversal_bucket
            currency = self.env['res.currency'].browse(currency_id) if currency_id else company_currency
            company_balance = sum(bucket.mapped('balance'))
            currency_balance = sum(bucket.mapped('amount_currency')) if currency_id else company_balance
            if not company_currency.is_zero(company_balance) or not currency.is_zero(currency_balance):
                account = self.env['account.account'].browse(account_id)
                partner = self.env['res.partner'].browse(partner_id)
                raise UserError(_(
                    'La reversión no cuadra para la cuenta %(account)s y el cliente/proveedor %(partner)s. '
                    'Debe: %(debit).2f · Haber: %(credit).2f. No se ha conciliado ningún apunte de ese grupo.'
                ) % {
                    'account': account.display_name,
                    'partner': partner.display_name or '',
                    'debit': sum(bucket.mapped('debit')),
                    'credit': sum(bucket.mapped('credit')),
                })

            bucket.filtered(lambda line: not line.reconciled).reconcile()
            if not all(bucket.mapped('reconciled')):
                account = self.env['account.account'].browse(account_id)
                raise UserError(_(
                    'La contrapartida %(account)s no ha quedado conciliada con su reversión. '
                    'La anulación se ha cancelado.'
                ) % {'account': account.display_name})
        return reversal


class AccountMoveLine(models.Model):
    _inherit = 'account.move.line'

    effect_id = fields.Many2one('account.effect', string='Efecto de cartera', readonly=True, copy=False, index=True)
    effect_group_id = fields.Many2one('account.effect.group', string='Agrupación de cartera', readonly=True, copy=False, index=True)
    effect_group_effect_id = fields.Many2one('account.effect', string='Efecto reclasificado', readonly=True, copy=False, index=True)
    effect_remittance_effect_id = fields.Many2one('account.effect', string='Efecto transferido a remesa', readonly=True, copy=False, index=True)
    effect_remittance_line_type = fields.Selection(
        [('source', 'Origen de remesa'), ('target', 'Saldo de remesa')],
        string='Tipo de línea de remesa', readonly=True, copy=False, index=True,
    )
    effect_remittance_origin_line_id = fields.Many2one(
        'account.move.line', string='Apunte origen de remesa', readonly=True, copy=False, index=True,
    )
    effect_ids = fields.Many2many('account.effect', 'account_move_line_effect_rel', 'line_id', 'effect_id', string='Efectos liquidados', readonly=True, copy=False)
