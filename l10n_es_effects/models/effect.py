from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountEffect(models.Model):
    _name = 'account.effect'
    _description = 'Efecto de cartera'
    _rec_name = 'display_label'
    _order = 'due_date desc, id desc'

    name = fields.Char(string='Nº Efecto', required=True, readonly=True, copy=False, default='/')
    cartera_number = fields.Char(string='Nº Cartera', readonly=True, copy=False, index=True)
    display_label = fields.Char(string='Nombre', compute='_compute_display_labels', store=True)
    display_reference = fields.Char(string='Referencia', compute='_compute_display_labels', store=True)
    invoice_reference = fields.Char(string='Referencia factura', readonly=True)
    company_id = fields.Many2one('res.company', required=True, readonly=True, default=lambda self: self.env.company)
    partner_id = fields.Many2one('res.partner', string='Empresa', required=True)
    company_type = fields.Selection([('customer', 'Cliente'), ('supplier', 'Proveedor')], string='Tipo de empresa', required=True, readonly=True, default=lambda self: 'customer' if self.env.context.get('default_company_type') != 'supplier' else 'supplier')
    move_id = fields.Many2one('account.move', string='Factura', readonly=True, index=True)
    move_line_id = fields.Many2one('account.move.line', string='Vencimiento contable', readonly=True, ondelete='restrict', index=True)
    reference = fields.Char(string='Concepto')
    invoice_name = fields.Char(string='Nombre factura', related='move_id.name', readonly=True)
    due_date = fields.Date(string='Fecha de vencimiento', required=True, index=True)
    effect_type = fields.Selection([
        ('effect', 'Efecto'),
        ('group', 'Agrupación'),
        ('remittance', 'Remesa'),
    ], string='Tipo de efecto', required=True, default='effect')
    bank_journal_id = fields.Many2one('account.journal', string='Banco', domain="[('type', '=', 'bank')]")
    partner_bank_id = fields.Many2one('res.partner.bank', string='Cuenta destino')
    payment_direction = fields.Selection([('receive', 'Recibir dinero'), ('send', 'Enviar dinero')], string='Tipo de pago', required=True, default=lambda self: 'receive' if self.env.context.get('default_company_type') != 'supplier' else 'send')
    amount = fields.Monetary(string='Total', required=True)
    currency_id = fields.Many2one('res.currency', required=True, default=lambda self: self.env.company.currency_id)
    amount_pending = fields.Monetary(string='Total pendiente', compute='_compute_amount_pending', currency_field='currency_id', store=True)
    payment_state = fields.Selection([('pending', 'Pendiente'), ('partial', 'Parcial'), ('paid', 'Saldado')], string='Estado del pago', compute='_compute_payment_state', store=True)
    state = fields.Selection([('pending', 'Pendiente'), ('grouped', 'Agrupado'), ('remitted', 'Remesado'), ('paid', 'Saldado'), ('returned', 'Devuelto'), ('uncollectible', 'Incobrable')], string='Situación', required=True, default='pending', index=True)
    group_id = fields.Many2one('account.effect.group', string='Agrupación', readonly=True, ondelete='set null')
    remittance_id = fields.Many2one('account.effect.remittance', string='Remesa', readonly=True, ondelete='set null')
    adjustment_move_id = fields.Many2one('account.move', string='Asiento de gastos/comisiones', readonly=True, copy=False)
    payment_id = fields.Many2one('account.payment', string='Pago', readonly=True, copy=False)
    payment_move_id = fields.Many2one('account.move', string='Asiento de pago', related='payment_id.move_id', readonly=True)
    payment_history_ids = fields.One2many('account.effect.payment.history', 'effect_id', string='Histórico pagos', readonly=True)
    situation_history_ids = fields.One2many('account.effect.situation.history', 'effect_id', string='Histórico situaciones', readonly=True)
    portfolio_effect_ids = fields.Many2many('account.effect', compute='_compute_portfolio_effects', string='Efectos de la misma Cartera')
    notes = fields.Text(string='Notas')
    active = fields.Boolean(default=True)

    _sql_constraints = [('move_line_unique', 'unique(move_line_id)', 'Solo puede existir un efecto por vencimiento contable.')]

    @api.model_create_multi
    def create(self, vals_list):
        records = self.browse()
        effect_vals = []
        for vals in vals_list:
            effect_type = vals.get('effect_type', 'effect')
            if effect_type != 'effect':
                raise UserError(_(
                    'Las agrupaciones y remesas se crean desde su formulario específico. '
                    'Utiliza Crear y selecciona el tipo correspondiente.'
                ))
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('account.effect') or '/'
            records |= super(AccountEffect, self).create(vals)
        for effect in records:
            effect._log_situation(effect.state, _('Efecto creado'))
        return records

    def _compute_portfolio_effects(self):
        for effect in self:
            if effect.remittance_id:
                effects = effect.remittance_id.effect_ids
            elif effect.group_id:
                effects = effect.group_id.effect_ids
            else:
                effects = self.search([('partner_id', '=', effect.partner_id.id), ('company_type', '=', effect.company_type), ('id', '!=', effect.id)])
            effect.portfolio_effect_ids = effects

    @api.depends('reference', 'invoice_reference', 'group_id.name', 'remittance_id.name', 'cartera_number', 'effect_type')
    def _compute_display_labels(self):
        for effect in self:
            base_ref = effect.invoice_reference or effect.reference or effect.invoice_name or ''
            effect.display_label = _('Efecto de %s') % (base_ref or effect.name)
            if effect.remittance_id:
                effect.display_reference = _('Remesa %s') % effect.remittance_id.cartera_number
            elif effect.group_id:
                effect.display_reference = _('Agrupación %s') % effect.group_id.cartera_number
            elif effect.effect_type == 'remittance' and effect.cartera_number:
                effect.display_reference = _('Remesa %s') % effect.cartera_number
            elif effect.effect_type == 'group' and effect.cartera_number:
                effect.display_reference = _('Agrupación %s') % effect.cartera_number
            else:
                effect.display_reference = base_ref

    @api.depends('amount', 'move_line_id.amount_residual', 'move_line_id.amount_residual_currency', 'move_line_id.currency_id', 'state')
    def _compute_amount_pending(self):
        for effect in self:
            if effect.move_line_id and not effect.move_line_id.reconciled:
                if effect.move_line_id.currency_id and effect.move_line_id.currency_id != effect.company_id.currency_id:
                    effect.amount_pending = abs(effect.move_line_id.amount_residual_currency)
                else:
                    effect.amount_pending = abs(effect.move_line_id.amount_residual)
            elif effect.state == 'paid' or (effect.move_line_id and effect.move_line_id.reconciled):
                effect.amount_pending = 0
            else:
                effect.amount_pending = effect.amount

    @api.depends('move_line_id.reconciled', 'move_line_id.amount_residual', 'move_line_id.amount_residual_currency', 'state', 'amount_pending')
    def _compute_payment_state(self):
        for effect in self:
            if effect.state == 'paid' or (effect.move_line_id and effect.move_line_id.reconciled):
                effect.payment_state = 'paid'
            elif effect.move_line_id and effect.amount_pending < effect.amount:
                effect.payment_state = 'partial'
            else:
                effect.payment_state = 'pending'

    def _log_situation(self, state, note=None):
        self.env['account.effect.situation.history'].create([{'effect_id': e.id, 'state': state, 'note': note} for e in self])

    def _set_state(self, state, note=None):
        self.write({'state': state})
        self._log_situation(state, note)

    def _ensure_same_currency(self, effects):
        if len(effects.mapped('currency_id')) > 1:
            raise UserError(_('No se pueden mezclar efectos de distintas monedas en una misma agrupación o remesa.'))

    def _validate_selection(self, effects, allowed_states):
        effects = effects.filtered(lambda e: e.state in allowed_states and not e.remittance_id)
        if not effects:
            raise UserError(_('Selecciona efectos válidos para esta operación.'))
        if len(effects.mapped('company_id')) > 1 or len(effects.mapped('company_type')) > 1:
            raise UserError(_('No se pueden mezclar compañías o tipos de empresa distintos.'))
        self._ensure_same_currency(effects)
        return effects

    def action_group_selected(self):
        effects = self._validate_selection(self, ('pending',))
        group = self.env['account.effect.group'].create({'company_id': effects.company_id.id, 'company_type': effects.company_type, 'partner_id': effects.partner_id.id if len(effects.mapped('partner_id')) == 1 else False, 'currency_id': effects.currency_id.id})
        effects.write({'group_id': group.id, 'cartera_number': group.cartera_number})
        effects._set_state('grouped', _('Agrupación %s') % group.name)
        return {'type': 'ir.actions.act_window', 'name': _('Agrupación'), 'res_model': 'account.effect.group', 'view_mode': 'form', 'res_id': group.id}

    def action_create_remittance_selected(self):
        effects = self._validate_selection(self, ('grouped',))
        remittance = self.env['account.effect.remittance'].create({'company_id': effects.company_id.id, 'company_type': effects.company_type, 'currency_id': effects.currency_id.id})
        groups = effects.mapped('group_id')
        groups.write({'remittance_id': remittance.id, 'state': 'remitted'})
        effects.write({'remittance_id': remittance.id, 'cartera_number': remittance.cartera_number})
        effects._set_state('remitted', _('Remesa %s') % remittance.name)
        return {'type': 'ir.actions.act_window', 'name': _('Remesa'), 'res_model': 'account.effect.remittance', 'view_mode': 'form', 'res_id': remittance.id}

    def action_saldar(self):
        self.ensure_one()
        if self.state in ('paid', 'returned', 'uncollectible') or not self.move_line_id or self.move_line_id.reconciled:
            raise UserError(_('Este efecto no tiene un vencimiento contable pendiente de pago.'))
        return {'name': _('Saldar'), 'type': 'ir.actions.act_window', 'res_model': 'account.payment.register', 'view_mode': 'form', 'target': 'new', 'context': {'active_model': 'account.move.line', 'active_ids': [self.move_line_id.id], 'effect_id': self.id}}

    def action_register_payment(self):
        return self.action_saldar()

    def action_open_invoice(self):
        self.ensure_one()
        if not self.move_id:
            raise UserError(_('Este efecto no está asociado a una factura.'))
        return {'type': 'ir.actions.act_window', 'name': _('Factura'), 'res_model': 'account.move', 'view_mode': 'form', 'res_id': self.move_id.id}

    def action_create_from_menu(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Crear'),
            'res_model': 'account.effect.create.wizard',
            'view_mode': 'form',
            'target': 'new',
        }

    def action_new_effect(self):
        return {'type': 'ir.actions.act_window', 'name': _('Crear efecto'), 'res_model': 'account.effect', 'view_mode': 'form', 'target': 'current', 'context': dict(self.env.context)}

    def action_ungroup_selected(self):
        """Desvincula los efectos de agrupaciones/remesas sin marcar devolución."""
        for effect in self:
            if effect.state == 'paid':
                continue
            group = effect.group_id
            remittance = effect.remittance_id
            effect.write({
                'group_id': False,
                'remittance_id': False,
                'state': 'pending',
                'cartera_number': False,
            })
            effect._log_situation('pending', _('Efecto desagrupado/desremesado'))
            if group:
                group._compute_amount()
            if remittance:
                remittance._compute_amount()
        return True

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
