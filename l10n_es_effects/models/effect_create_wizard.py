from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountEffectCreateWizard(models.TransientModel):
    _name = 'account.effect.create.wizard'
    _description = 'Crear elemento de cartera'

    effect_type = fields.Selection([
        ('effect', 'Efecto'),
        ('group', 'Agrupación'),
        ('remittance', 'Remesa'),
    ], string='Tipo de efecto', required=True, default=lambda self: self.env.context.get('default_effect_type', 'effect'))
    company_type = fields.Selection([
        ('customer', 'Cliente'),
        ('supplier', 'Proveedor'),
    ], string='Tipo de empresa', required=True, default=lambda self: self.env.context.get('default_company_type', 'customer'))
    partner_id = fields.Many2one('res.partner', string='Cliente / Proveedor')
    company_id = fields.Many2one('res.company', string='Compañía', required=True, default=lambda self: self.env.company)
    company_partner_id = fields.Many2one('res.partner', related='company_id.partner_id', readonly=True)
    currency_id = fields.Many2one('res.currency', string='Moneda', required=True, default=lambda self: self.env.company.currency_id)
    move_id = fields.Many2one('account.move', string='Factura', domain="[('company_id', '=', company_id), ('state', '=', 'posted'), ('move_type', 'in', ('out_invoice', 'in_invoice'))]")
    source_move_line_id = fields.Many2one(
        'account.move.line', string='Apunte contable existente',
        domain="[('company_id', '=', company_id), ('move_id.state', '=', 'posted'), ('reconciled', '=', False), ('account_id.reconcile', '=', True), ('account_id.deprecated', '=', False)]",
        help='Campo opcional para vincular un apunte ya publicado. También puedes crear el efecto sin apunte de origen.'
    )
    manual_account_id = fields.Many2one(
        'account.account', string='Cuenta destino',
        domain="[('company_ids', 'in', company_id), ('deprecated', '=', False), ('reconcile', '=', True)]",
        check_company=True,
        help='Cuenta conciliable que se utilizará al agrupar o saldar el efecto manual.'
    )
    due_date = fields.Date(string='Fecha de vencimiento', default=fields.Date.context_today)
    amount = fields.Monetary(string='Total', currency_field='currency_id')
    bank_journal_id = fields.Many2one('account.journal', string='Banco', domain="[('type', '=', 'bank'), ('company_id', '=', company_id)]")
    partner_bank_id = fields.Many2one(
        'res.partner.bank', string='Cuenta bancaria',
        default=lambda self: self._default_partner_bank(),
    )
    payment_direction = fields.Selection([
        ('receive', 'Recibir dinero'),
        ('send', 'Enviar dinero'),
    ], string='Tipo de pago', compute='_compute_payment_direction', store=False)
    reference = fields.Char(string='Circular / Concepto')
    notes = fields.Text(string='Notas')

    @api.model
    def _default_partner_bank(self):
        if self.env.context.get('default_effect_type') != 'remittance':
            return False
        company_partner = self.env.company.partner_id
        if not company_partner:
            return False
        bank = self.env['res.partner.bank'].search(
            [('partner_id', '=', company_partner.id)], order='id', limit=1
        )
        return bank.id or False

    @api.depends('company_type', 'move_id', 'source_move_line_id')
    def _compute_payment_direction(self):
        for wizard in self:
            source = wizard.source_move_line_id
            if not source and wizard.move_id:
                account_type = 'asset_receivable' if wizard.move_id.move_type in ('out_invoice', 'out_refund') else 'liability_payable'
                source = wizard.move_id.line_ids.filtered(
                    lambda line: line.display_type == 'payment_term' and line.account_type == account_type
                ).sorted(lambda line: line.date_maturity or wizard.move_id.invoice_date_due or wizard.move_id.invoice_date)[:1]
            residual = 0.0
            if source:
                residual = source.amount_residual_currency if source.currency_id and source.currency_id != source.company_id.currency_id else source.amount_residual
            wizard.payment_direction = ('receive' if residual > 0 else 'send') if source else ('receive' if wizard.company_type == 'customer' else 'send')

    @api.onchange('effect_type')
    def _onchange_effect_type(self):
        for wizard in self:
            if wizard.effect_type == 'remittance':
                company_partner = wizard.company_id.partner_id
                if wizard.partner_bank_id and wizard.partner_bank_id.partner_id != company_partner:
                    wizard.partner_bank_id = False
                if not wizard.partner_bank_id and company_partner:
                    wizard.partner_bank_id = self.env['res.partner.bank'].search(
                        [('partner_id', '=', company_partner.id)], order='id', limit=1
                    )
            elif wizard.partner_bank_id and wizard.effect_type == 'effect':
                if wizard.partner_id and wizard.partner_bank_id.partner_id != wizard.partner_id:
                    wizard.partner_bank_id = False
            elif wizard.effect_type == 'group':
                # The group's customer/supplier is selected after its creation.
                wizard.partner_bank_id = False

    @api.onchange('company_type')
    def _onchange_company_type(self):
        self.partner_id = False
        self.move_id = False
        self.source_move_line_id = False
        self.manual_account_id = False
        self.partner_bank_id = False
        self.amount = 0.0
        self.currency_id = self.company_id.currency_id or self.env.company.currency_id

    @api.onchange('company_id')
    def _onchange_company_id(self):
        self.move_id = False
        self.source_move_line_id = False
        self.manual_account_id = False
        self.currency_id = self.company_id.currency_id
        self.amount = 0.0
        if self.effect_type == 'remittance' and self.company_id.partner_id:
            self.partner_bank_id = self.env['res.partner.bank'].search(
                [('partner_id', '=', self.company_id.partner_id.id)], order='id', limit=1
            )

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        if self.partner_id and self.partner_bank_id and self.partner_bank_id.partner_id != self.partner_id:
            self.partner_bank_id = False
        if self.partner_id and self.effect_type == 'effect' and not self.manual_account_id:
            property_name = 'property_account_receivable_id' if self.company_type == 'customer' else 'property_account_payable_id'
            account = self.partner_id.with_company(self.company_id)[property_name]
            if account and account.reconcile and not account.deprecated:
                self.manual_account_id = account

    @api.onchange('move_id')
    def _onchange_move_id(self):
        if not self.move_id:
            return
        self.source_move_line_id = False
        self.partner_id = self.move_id.partner_id
        self.company_type = 'customer' if self.move_id.move_type in ('out_invoice', 'out_refund') else 'supplier'
        self.currency_id = self.move_id.currency_id
        payment_terms = self.move_id.line_ids.filtered(lambda line: line.display_type == 'payment_term')
        if payment_terms:
            line = payment_terms.sorted(lambda l: l.date_maturity or self.move_id.invoice_date_due or self.move_id.invoice_date)[0]
            self.due_date = line.date_maturity or self.move_id.invoice_date_due or self.move_id.invoice_date
            self.amount = line.amount_residual_currency if line.currency_id and line.currency_id != self.company_id.currency_id else line.amount_residual

    @api.onchange('source_move_line_id')
    def _onchange_source_move_line_id(self):
        line = self.source_move_line_id
        if not line:
            return
        self.move_id = False
        self.manual_account_id = line.account_id
        self.partner_id = line.partner_id or self.partner_id
        self.currency_id = line.currency_id or self.company_id.currency_id
        residual = line.amount_residual_currency if line.currency_id and line.currency_id != self.company_id.currency_id else line.amount_residual
        self.amount = residual
        self.company_type = 'customer' if line.account_type == 'asset_receivable' else 'supplier'
        self.due_date = line.date_maturity or line.move_id.invoice_date_due or line.move_id.date
        if not self.reference:
            self.reference = line.move_id.ref or line.name or line.move_id.name

    def _effect_vals(self):
        if not self.partner_id:
            raise UserError(_('Indica el cliente o proveedor.'))
        if not self.due_date:
            raise UserError(_('Indica la fecha de vencimiento.'))
        if self.currency_id.is_zero(self.amount) or (not self.move_id and not self.source_move_line_id and self.amount <= 0):
            raise UserError(_('El total debe ser distinto de cero y, para efectos manuales, superior a cero.'))
        source = self.source_move_line_id if not self.move_id else self.env['account.move.line']
        vals = {
            'company_id': self.company_id.id,
            'company_type': self.company_type,
            'partner_id': self.partner_id.id,
            'move_id': self.move_id.id if self.move_id else False,
            'move_line_id': source.id if source else False,
            'invoice_reference': self.move_id.name if self.move_id else False,
            'reference': self.reference or False,
            'due_date': self.due_date,
            'amount': self.amount,
            'currency_id': self.currency_id.id,
            'bank_journal_id': self.bank_journal_id.id if self.bank_journal_id else False,
            'manual_account_id': source.account_id.id if source else (self.manual_account_id.id if self.manual_account_id else False),
            'partner_bank_id': self.partner_bank_id.id if self.partner_bank_id else False,
            'payment_direction': self.payment_direction,
            'effect_type': 'effect',
        }
        return vals

    def _container_vals(self):
        vals = {
            'company_id': self.company_id.id,
            'company_type': self.company_type,
            'currency_id': self.currency_id.id,
            'date': fields.Date.context_today(self),
            'due_date': self.due_date,
            'reference': self.reference or False,
            'notes': self.notes or False,
            'payment_direction': self.payment_direction,
        }
        # Leave the bank field absent when the wizard has no explicit choice,
        # so the container model's company default can be applied.
        if self.bank_journal_id:
            vals['bank_journal_id'] = self.bank_journal_id.id
        if self.partner_bank_id:
            vals['partner_bank_id'] = self.partner_bank_id.id
        return vals

    def _validate_manual_source(self):
        self.ensure_one()
        line = self.source_move_line_id
        if not line:
            raise UserError(_('Para crear un efecto manual, selecciona un apunte contable existente y pendiente.'))
        if line.company_id != self.company_id or line.move_id.state != 'posted':
            raise UserError(_('El apunte seleccionado debe estar publicado y pertenecer a la compañía activa.'))
        if line.reconciled or not line.account_id.reconcile or line.account_id.deprecated:
            raise UserError(_('El apunte seleccionado debe estar abierto y pertenecer a una cuenta que permita conciliación.'))
        if line.partner_id and line.partner_id != self.partner_id:
            raise UserError(_('El tercero seleccionado no coincide con el tercero del apunte contable.'))
        residual = line.amount_residual_currency if line.currency_id and line.currency_id != self.company_id.currency_id else line.amount_residual
        source_currency = line.currency_id or self.company_id.currency_id
        if source_currency != self.currency_id:
            raise UserError(_('La moneda del efecto debe coincidir con la moneda del apunte contable.'))
        if source_currency.compare_amounts(abs(residual), 0.0) <= 0:
            raise UserError(_('El apunte seleccionado no tiene saldo pendiente.'))
        if source_currency.compare_amounts(abs(self.amount), abs(residual)) != 0:
            raise UserError(_('El importe del efecto debe coincidir con el saldo pendiente completo del apunte (%s). Los pagos parciales se registrarán al saldar el efecto.') % abs(residual))
        existing = self.env['account.effect'].search([('move_line_id', '=', line.id)], limit=1)
        if existing:
            raise UserError(_('Este apunte contable ya está vinculado al efecto %s.') % existing.display_name)
        return line

    def _validate_manual_account(self):
        self.ensure_one()
        account = self.manual_account_id.exists()
        if not account:
            raise UserError(_('Selecciona la cuenta destino del efecto manual.'))
        if account.deprecated or not account.reconcile:
            raise UserError(_('La cuenta destino debe estar activa y permitir conciliación.'))
        if account.company_ids and self.company_id not in account.company_ids:
            raise UserError(_('La cuenta destino no pertenece a la compañía seleccionada.'))
        return account

    def action_create(self):
        self.ensure_one()
        if self.effect_type == 'effect':
            vals = self._effect_vals()
            if self.move_id:
                account_type = 'asset_receivable' if self.company_type == 'customer' else 'liability_payable'
                candidates = self.move_id.line_ids.filtered(lambda line:
                    line.display_type == 'payment_term'
                    and line.account_id.account_type == account_type
                    and not line.reconciled
                    and line.partner_id == self.partner_id
                )
                due_matches = candidates.filtered(lambda line: (line.date_maturity or self.move_id.invoice_date_due or self.move_id.invoice_date) == self.due_date)
                if due_matches:
                    candidates = due_matches
                exact = candidates.filtered(lambda line:
                    self.currency_id.compare_amounts(
                        abs(line.amount_residual_currency if line.currency_id and line.currency_id != self.company_id.currency_id else line.amount_residual),
                        self.amount,
                    ) == 0
                )
                source = exact[:1] if len(exact) == 1 else (candidates[:1] if len(candidates) == 1 else self.env['account.move.line'])
                if not source:
                    raise UserError(_('No se ha podido identificar un vencimiento abierto único de la factura.'))
                existing = self.env['account.effect'].search([('move_line_id', '=', source.id)], limit=1)
                if existing:
                    updates = {}
                    if self.reference:
                        updates['reference'] = self.reference
                    if self.bank_journal_id:
                        updates['bank_journal_id'] = self.bank_journal_id.id
                    if self.partner_bank_id:
                        updates['partner_bank_id'] = self.partner_bank_id.id
                    if updates:
                        existing.write(updates)
                    effect = existing
                else:
                    vals['move_line_id'] = source.id
                    effect = self.env['account.effect'].create(vals)
            else:
                if self.source_move_line_id:
                    source = self._validate_manual_source()
                    vals['move_line_id'] = source.id
                    vals['manual_account_id'] = source.account_id.id
                else:
                    self._validate_manual_account()
                    vals['move_line_id'] = False
                effect = self.env['account.effect'].create(vals)
            return {
                'type': 'ir.actions.act_window',
                'name': _('Efecto %s') % effect.name,
                'res_model': 'account.effect',
                'view_mode': 'form',
                'res_id': effect.id,
                'target': 'main',
            }
        if self.effect_type == 'group':
            group = self.env['account.effect.group'].create(self._container_vals())
            return {
                'type': 'ir.actions.act_window',
                'name': _('Agrupación %s') % group.cartera_number,
                'res_model': 'account.effect.group',
                'view_mode': 'form',
                'res_id': group.id,
                'target': 'main',
            }
        remittance_vals = self._container_vals()
        remittance_vals['company_type'] = False
        remittance = self.env['account.effect.remittance'].create(remittance_vals)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Remesa %s') % remittance.cartera_number,
            'res_model': 'account.effect.remittance',
            'view_mode': 'form',
            'res_id': remittance.id,
            'target': 'main',
        }
