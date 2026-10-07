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
    display_situation = fields.Char(string='Situación', compute='_compute_display_labels', store=True)
    situation_state = fields.Selection([('pending', 'Pendiente'), ('paid', 'Saldado'), ('returned', 'Devuelto')], string='Situación', compute='_compute_situation_state', store=True)
    situation_ref = fields.Reference(
        selection=[('account.effect.group', 'Agrupación'), ('account.effect.remittance', 'Remesa')],
        string='Situación', compute='_compute_situation_ref', store=False
    )
    invoice_reference = fields.Char(string='Referencia factura', readonly=True)
    company_id = fields.Many2one('res.company', required=True, readonly=True, default=lambda self: self.env.company)
    partner_id = fields.Many2one('res.partner', string='Empresa')
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
    paid_date = fields.Date(string='Fecha de saldado', readonly=True, copy=False)
    display_payment_state = fields.Char(string='Estado del pago', compute='_compute_display_payment_state', store=True)
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
    is_container = fields.Boolean(
        string='Registro de cartera',
        default=False,
        readonly=True,
        copy=False,
        index=True,
    )
    is_portfolio_effect = fields.Boolean(
        string='Efecto de la misma cartera',
        default=False,
        readonly=True,
        copy=False,
        index=True,
    )
    container_group_id = fields.Many2one(
        'account.effect.group',
        string='Agrupación representada',
        readonly=True,
        copy=False,
        ondelete='cascade',
    )
    container_remittance_id = fields.Many2one(
        'account.effect.remittance',
        string='Remesa representada',
        readonly=True,
        copy=False,
        ondelete='cascade',
    )

    _sql_constraints = [('move_line_unique', 'unique(move_line_id)', 'Solo puede existir un efecto por vencimiento contable.')]

    @api.model_create_multi
    def create(self, vals_list):
        records = self.browse()
        effect_vals = []
        for vals in vals_list:
            effect_type = vals.get('effect_type', 'effect')
            is_container = bool(vals.get('is_container'))
            if effect_type != 'effect' and not is_container:
                raise UserError(_(
                    'Las agrupaciones y remesas se crean desde su formulario específico.'
                ))
            if not is_container and not vals.get('partner_id'):
                raise UserError(_('Indica el cliente o proveedor.'))
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('account.effect') or '/'
            records |= super(AccountEffect, self).create(vals)
        for effect in records:
            effect._log_situation(effect.state, _('Efecto creado'))
        return records

    def _compute_portfolio_effects(self):
        for effect in self:
            if effect.is_container:
                if effect.container_remittance_id:
                    effects = self.search([
                        ('is_portfolio_effect', '=', True),
                        ('container_remittance_id', '=', effect.container_remittance_id.id),
                    ])
                elif effect.container_group_id:
                    effects = self.search([
                        ('is_portfolio_effect', '=', True),
                        ('container_group_id', '=', effect.container_group_id.id),
                    ])
                else:
                    effects = self.browse()
            elif effect.remittance_id:
                effects = effect.remittance_id.effect_ids.filtered(lambda e: not e.is_container)
            elif effect.group_id:
                effects = effect.group_id.effect_ids.filtered(lambda e: not e.is_container)
            elif effect.move_id:
                effects = self.search([
                    ('move_id', '=', effect.move_id.id),
                    ('id', '!=', effect.id),
                    ('is_portfolio_effect', '=', False),
                ])
            else:
                effects = self.browse()
            effect.portfolio_effect_ids = effects

    @api.depends(
        'group_id', 'group_id.remittance_id',
        'remittance_id',
        'container_group_id', 'container_group_id.remittance_id',
        'container_remittance_id',
    )
    def _compute_situation_ref(self):
        for effect in self:
            situation = False
            if effect.is_container:
                situation = False
            elif effect.remittance_id:
                situation = 'account.effect.remittance,%s' % effect.remittance_id.id
            elif effect.group_id:
                situation = 'account.effect.group,%s' % effect.group_id.id
            effect.situation_ref = situation

    @api.depends('state', 'is_container', 'container_group_id.state', 'container_remittance_id.state')
    def _compute_situation_state(self):
        for effect in self:
            if effect.is_container and effect.container_remittance_id:
                effect.situation_state = 'paid' if effect.container_remittance_id.state == 'paid' else 'pending'
            elif effect.is_container and effect.container_group_id:
                effect.situation_state = 'paid' if effect.container_group_id.state == 'paid' else 'pending'
            elif effect.state == 'paid':
                effect.situation_state = 'paid'
            elif effect.state == 'returned':
                effect.situation_state = 'returned'
            else:
                effect.situation_state = 'pending'

    @api.depends(
        'reference', 'invoice_reference', 'name', 'group_id.name', 'group_id.cartera_number',
        'group_id.date', 'group_id.remittance_id', 'remittance_id.name', 'remittance_id.cartera_number',
        'remittance_id.date', 'container_group_id.name', 'container_group_id.cartera_number',
        'container_group_id.remittance_id', 'container_remittance_id.name', 'container_remittance_id.cartera_number',
        'container_remittance_id.date', 'cartera_number', 'effect_type', 'state', 'paid_date'
    )
    def _compute_display_labels(self):
        for effect in self:
            if effect.is_container:
                if effect.container_remittance_id:
                    remittance = effect.container_remittance_id
                    effect.display_label = _('Remesa nº %s') % remittance.cartera_number
                    effect.display_reference = remittance.reference or ''
                    if remittance.state == 'paid':
                        effect.display_situation = _('Saldado · %s') % (remittance.paid_date or remittance.date or '')
                    elif remittance.state == 'partial':
                        effect.display_situation = _('Saldado parcialmente · %s') % (remittance.paid_date or remittance.date or '')
                    else:
                        effect.display_situation = _('Pendiente')
                elif effect.container_group_id:
                    group = effect.container_group_id
                    effect.display_label = _('Agrupación nº %s') % group.cartera_number
                    effect.display_reference = group.reference or ''
                    if group.state == 'paid':
                        effect.display_situation = _('Saldado · %s') % (group.paid_date or group.date or '')
                    elif group.state == 'cancelled':
                        effect.display_situation = _('Devuelto')
                    else:
                        effect.display_situation = _('Pendiente')
                else:
                    effect.display_label = effect.name
                    effect.display_reference = effect.reference or ''
                    effect.display_situation = dict(self._fields['state'].selection).get(effect.state, effect.state)
            else:
                effect.display_label = _('Efecto nº %s') % effect.name
                effect.display_reference = effect.invoice_reference or effect.reference or ''
                if effect.state == 'paid':
                    effect.display_situation = _('Saldado · %s') % (effect.paid_date or '')
                elif effect.state == 'returned':
                    effect.display_situation = _('Devuelto')
                else:
                    effect.display_situation = _('Pendiente')

    @api.depends(
        'amount', 'move_line_id.amount_residual', 'move_line_id.amount_residual_currency',
        'move_line_id.currency_id', 'state', 'is_container',
        'container_group_id.amount_total', 'container_group_id.effect_ids.amount_pending',
        'container_remittance_id.amount_pending', 'container_remittance_id.state',
    )
    def _compute_amount_pending(self):
        for effect in self:
            if effect.is_container:
                if effect.container_remittance_id:
                    effect.amount_pending = effect.container_remittance_id.amount_pending
                elif effect.container_group_id:
                    effect.amount_pending = sum(
                        effect.container_group_id.effect_ids.filtered(lambda e: not e.is_container).mapped('amount_pending')
                    )
                else:
                    effect.amount_pending = effect.amount
            elif effect.move_line_id and not effect.move_line_id.reconciled:
                if effect.move_line_id.currency_id and effect.move_line_id.currency_id != effect.company_id.currency_id:
                    effect.amount_pending = abs(effect.move_line_id.amount_residual_currency)
                else:
                    effect.amount_pending = abs(effect.move_line_id.amount_residual)
            elif effect.state == 'paid' or (effect.move_line_id and effect.move_line_id.reconciled):
                effect.amount_pending = 0
            else:
                effect.amount_pending = effect.amount

    @api.depends(
        'move_line_id.reconciled', 'move_line_id.amount_residual',
        'move_line_id.amount_residual_currency', 'state', 'amount_pending',
        'is_container',
    )
    def _compute_payment_state(self):
        for effect in self:
            if effect.is_container:
                effect.payment_state = 'paid' if effect.state == 'paid' or effect.amount_pending <= 0 else 'pending'
            elif effect.state == 'paid' or (effect.move_line_id and effect.move_line_id.reconciled):
                effect.payment_state = 'paid'
            elif effect.move_line_id and effect.amount_pending < effect.amount:
                effect.payment_state = 'partial'
            else:
                effect.payment_state = 'pending'

    @api.depends('payment_state', 'paid_date', 'state', 'group_id', 'group_id.date', 'remittance_id', 'remittance_id.date', 'remittance_id.state', 'container_group_id', 'container_remittance_id')
    def _compute_display_payment_state(self):
        for effect in self:
            if effect.is_container:
                if effect.container_remittance_id:
                    remittance = effect.container_remittance_id
                    if remittance.state == 'paid':
                        effect.display_payment_state = _('Cobrado - %s') % (effect.paid_date or remittance.paid_date or remittance.date or '')
                    elif remittance.state == 'partial':
                        effect.display_payment_state = _('Saldado parcialmente - %s') % (remittance.paid_date or remittance.date or '')
                    else:
                        effect.display_payment_state = _('Pendiente')
                elif effect.container_group_id:
                    group = effect.container_group_id
                    if group.state == 'paid':
                        effect.display_payment_state = _('Saldado - %s') % (effect.paid_date or group.paid_date or group.date or '')
                    elif effect.amount_pending < effect.amount:
                        effect.display_payment_state = _('Saldado parcialmente - %s') % (group.paid_date or group.date or '')
                    else:
                        effect.display_payment_state = _('Pendiente')
                else:
                    effect.display_payment_state = _('Saldado - %s') % (effect.paid_date or '') if effect.state == 'paid' else _('Pendiente')
            elif effect.state == 'paid':
                effect.display_payment_state = _('Saldado - %s') % (effect.paid_date or '')
            elif effect.state == 'returned':
                effect.display_payment_state = _('Devuelto')
            elif effect.state in ('grouped', 'remitted'):
                effect.display_payment_state = _('Pendiente')
            else:
                effect.display_payment_state = _('Pendiente')

    def _log_situation(self, state, note=None):
        normalized = 'paid' if state == 'paid' else ('returned' if state == 'returned' else 'pending')
        self.env['account.effect.situation.history'].create([{'effect_id': e.id, 'state': normalized, 'note': note} for e in self])

    def _set_state(self, state, note=None):
        self.write({'state': state})
        self._log_situation(state, note)

    def _ensure_same_currency(self, effects):
        if len(effects.mapped('currency_id')) > 1:
            raise UserError(_('No se pueden mezclar efectos de distintas monedas en una misma agrupación o remesa.'))

    def _validate_selection(self, effects, allowed_states):
        effects = effects.filtered(lambda e: not e.is_container and e.state in allowed_states and not e.remittance_id)
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
        group._compute_totals()
        group._sync_container_effect()
        effects._set_state('grouped', _('Agrupación %s') % group.name)
        return {'type': 'ir.actions.act_window', 'name': _('Agrupación'), 'res_model': 'account.effect.group', 'view_mode': 'form', 'res_id': group.id}

    def action_create_remittance_selected(self):
        effects = self._validate_selection(self, ('pending', 'grouped'))
        remittance = self.env['account.effect.remittance'].create({'company_id': effects.company_id.id, 'company_type': effects.company_type, 'currency_id': effects.currency_id.id})
        groups = effects.mapped('group_id')
        if groups:
            groups.write({'remittance_id': remittance.id, 'state': 'remitted'})
            for group in groups:
                group._sync_container_effect()
        effects.write({'remittance_id': remittance.id, 'cartera_number': remittance.cartera_number})
        effects._set_state('remitted', _('Remesa %s') % remittance.name)
        remittance._compute_totals()
        remittance._sync_container_effect()
        return {'type': 'ir.actions.act_window', 'name': _('Remesa'), 'res_model': 'account.effect.remittance', 'view_mode': 'form', 'res_id': remittance.id}

    def action_saldar(self):
        self.ensure_one()
        if self.is_container:
            if self.container_group_id:
                return self.container_group_id.action_saldar()
            if self.container_remittance_id:
                return self.container_remittance_id.action_saldar_entero()
            raise UserError(_('Este registro de cartera no tiene un contenedor asociado.'))
        if self.state in ('paid', 'returned', 'uncollectible') or not self.move_line_id or self.move_line_id.reconciled:
            raise UserError(_('Este efecto no tiene un vencimiento contable pendiente de pago.'))
        return {'name': _('Saldar'), 'type': 'ir.actions.act_window', 'res_model': 'account.payment.register', 'view_mode': 'form', 'target': 'new', 'context': {'active_model': 'account.move.line', 'active_ids': [self.move_line_id.id], 'effect_id': self.id}}

    def action_register_payment(self):
        return self.action_saldar()

    def action_open_container(self):
        self.ensure_one()
        if self.container_remittance_id:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Remesa %s') % self.container_remittance_id.cartera_number,
                'res_model': 'account.effect.remittance',
                'view_mode': 'form',
                'res_id': self.container_remittance_id.id,
            }
        if self.container_group_id:
            return {
                'type': 'ir.actions.act_window',
                'name': _('Agrupación %s') % self.container_group_id.cartera_number,
                'res_model': 'account.effect.group',
                'view_mode': 'form',
                'res_id': self.container_group_id.id,
            }
        return False

    @api.model
    def _sync_container_effects(self):
        groups = self.env['account.effect.group'].search([])
        remittances = self.env['account.effect.remittance'].search([])
        for group in groups:
            group._sync_container_effect()
        for remittance in remittances:
            remittance._sync_container_effect()
        return True

    @api.model
    def action_open_effects(self, company_type):
        self._sync_container_effects()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Efectos de clientes') if company_type == 'customer' else _('Efectos de proveedores'),
            'res_model': 'account.effect',
            'view_mode': 'list,form',
            'views': [
                (self.env.ref('l10n_es_effects.view_account_effect_list').id, 'list'),
                (False, 'form'),
            ],
            'domain': [('company_type', '=', company_type), ('is_portfolio_effect', '=', False)],
            'context': {'default_company_type': company_type, 'default_effect_type': 'effect'},
        }

    def action_open_invoice(self):
        self.ensure_one()
        if not self.move_id:
            raise UserError(_('Este efecto no está asociado a una factura.'))
        return {'type': 'ir.actions.act_window', 'name': _('Factura'), 'res_model': 'account.move', 'view_mode': 'form', 'res_id': self.move_id.id}


    def action_open_payment(self):
        self.ensure_one()
        if not self.payment_id:
            raise UserError(_('Este efecto no tiene un pago de Odoo asociado.'))
        return self.payment_id.action_open_business_doc()

    def action_open_accounting_entries(self):
        self.ensure_one()
        move_ids = set(self.payment_move_id.ids)
        move_ids.update(self.payment_history_ids.mapped('payment_id.move_id').ids)
        if self.adjustment_move_id:
            move_ids.add(self.adjustment_move_id.id)
        if not move_ids:
            raise UserError(_('No hay asientos contables asociados a este efecto.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Asientos contables'),
            'res_model': 'account.move',
            'view_mode': 'list,form',
            'domain': [('id', 'in', list(move_ids))],
            'context': {'create': False},
        }

    def _latest_payment_for_effects(self, effects):
        payments = effects.mapped('payment_id').filtered(lambda p: p)
        return payments.sorted(key=lambda p: (p.date or fields.Date.min, p.id), reverse=True)[:1]

    def action_anular_saldado(self):
        self.ensure_one()
        if self.is_container:
            if self.container_group_id:
                return self.container_group_id.action_anular_saldado()
            if self.container_remittance_id:
                return self.container_remittance_id.action_anular_saldado()
        if self.state != 'paid':
            raise UserError(_('Solo se puede anular un efecto saldado.'))
        payment = self._latest_payment_for_effects(self)
        if not payment:
            raise UserError(_('No se ha encontrado el pago de Odoo asociado al efecto.'))
        related = self.search([('payment_id', '=', payment.id), ('state', '=', 'paid')])
        payment.action_cancel()
        for effect in related:
            restore_state = 'remitted' if effect.remittance_id else ('grouped' if effect.group_id else 'pending')
            effect.write({'state': restore_state, 'paid_date': False, 'payment_id': False})
            effect._log_situation(restore_state, _('Saldado anulado · Pago %s') % payment.display_name)
        for group in related.mapped('group_id'):
            group._update_payment_state_from_effects()
        for remittance in related.mapped('remittance_id'):
            remittance._update_payment_state_from_effects()
        return True

    def action_devolver(self):
        self.ensure_one()
        if self.is_container:
            raise UserError(_('La devolución debe realizarse desde un efecto individual.'))
        if self.state != 'paid':
            raise UserError(_('Solo se puede devolver un efecto saldado.'))
        today = fields.Date.context_today(self)
        vals = {
            'company_id': self.company_id.id,
            'company_type': self.company_type,
            'partner_id': self.partner_id.id,
            'move_id': self.move_id.id if self.move_id else False,
            'move_line_id': False,
            'reference': _('Devuelto de efecto de %s') % self.name,
            'invoice_reference': self.invoice_reference,
            'due_date': today,
            'effect_type': 'effect',
            'bank_journal_id': self.bank_journal_id.id if self.bank_journal_id else False,
            'partner_bank_id': self.partner_bank_id.id if self.partner_bank_id else False,
            'payment_direction': self.payment_direction,
            'amount': self.amount,
            'currency_id': self.currency_id.id,
            'state': 'pending',
            'active': True,
        }
        returned = self.env['account.effect'].create(vals)
        self.write({'state': 'returned'})
        self._log_situation('returned', _('Efecto devuelto'))
        returned._log_situation('pending', _('Nuevo efecto pendiente tras devolución de %s') % self.name)
        if self.payment_id:
            history_vals = {
                'effect_id': self.id,
                'date': today,
                'payment_id': self.payment_id.id,
                'journal_id': self.payment_id.journal_id.id,
                'amount': self.amount,
                'note': _('Devolución de efecto'),
            }
            self.env['account.effect.payment.history'].create(history_vals)
            if self.group_id:
                self.env['account.effect.container.payment.history'].create({
                    'group_id': self.group_id.id,
                    'payment_id': self.payment_id.id,
                    'reference': self.payment_id.name or self.name,
                    'move_id': self.payment_id.move_id.id if self.payment_id.move_id else False,
                    'date': today,
                    'effect_ids': [(6, 0, [self.id])],
                    'amount': self.amount,
                    'currency_id': self.currency_id.id,
                    'type': 'returned',
                })
            if self.remittance_id:
                self.env['account.effect.container.payment.history'].create({
                    'remittance_id': self.remittance_id.id,
                    'payment_id': self.payment_id.id,
                    'reference': self.payment_id.name or self.name,
                    'move_id': self.payment_id.move_id.id if self.payment_id.move_id else False,
                    'date': today,
                    'effect_ids': [(6, 0, [self.id])],
                    'amount': self.amount,
                    'currency_id': self.currency_id.id,
                    'type': 'returned',
                })
        if self.group_id:
            self.group_id._update_payment_state_from_effects(today)
        if self.remittance_id:
            self.remittance_id._update_payment_state_from_effects(today)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Efecto devuelto'),
            'res_model': 'account.effect',
            'view_mode': 'form',
            'res_id': returned.id,
        }

    def action_add_selected_to_remittance(self):
        remittance_id = self.env.context.get('remittance_id')
        if not remittance_id:
            raise UserError(_('No se ha indicado la remesa de destino.'))
        remittance = self.env['account.effect.remittance'].browse(remittance_id).exists()
        if not remittance:
            raise UserError(_('No se ha encontrado la remesa.'))

        selected = self.filtered(lambda e: not e.remittance_id and (
            (not e.is_container and not e.is_portfolio_effect and e.state == 'pending')
            or (e.is_container and e.effect_type == 'group' and e.container_group_id and e.container_group_id.state == 'draft')
        ))
        if not selected:
            raise UserError(_('Selecciona al menos un efecto pendiente o una agrupación pendiente.'))

        direct_effects = selected.filtered(lambda e: not e.is_container)
        group_containers = selected.filtered(lambda e: e.is_container and e.container_group_id)
        group_effects = group_containers.mapped('container_group_id.effect_ids').filtered(
            lambda e: not e.is_container and e.state in ('pending', 'grouped') and not e.remittance_id
        )
        effects = (direct_effects | group_effects).exists()
        if not effects:
            raise UserError(_('No hay efectos pendientes disponibles para añadir a la remesa.'))
        if any(e.company_id != remittance.company_id for e in effects):
            raise UserError(_('No se pueden mezclar compañías.'))
        if len(effects.mapped('currency_id')) > 1 or any(e.currency_id != remittance.currency_id for e in effects):
            raise UserError(_('No se pueden mezclar monedas.'))
        types = set(effects.mapped('company_type'))
        if remittance.company_type and types and types != {remittance.company_type}:
            raise UserError(_('No se pueden mezclar clientes y proveedores en una misma remesa.'))
        if types:
            remittance.company_type = next(iter(types))

        effects.write({
            'remittance_id': remittance.id,
            'cartera_number': remittance.cartera_number,
            'state': 'remitted',
        })
        groups = effects.mapped('group_id') | group_containers.mapped('container_group_id')
        for group in groups:        
            group.write({'remittance_id': remittance.id, 'state': 'remitted'})
            group._sync_container_effect()
        remittance._compute_totals()
        remittance._sync_container_effect()
        return {'type': 'ir.actions.act_window_close'}

    def action_create_from_menu(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Crear'),
            'res_model': 'account.effect.create.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_company_type': self.env.context.get('default_company_type', 'customer')},
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
            if remittance and group:
                # Quitar un efecto de una remesa no deshace su agrupación.
                effect.write({
                    'remittance_id': False,
                    'state': 'grouped',
                    'cartera_number': group.cartera_number,
                })
                effect._log_situation('grouped', _('Efecto retirado de la remesa'))
            else:
                effect.write({
                    'group_id': False,
                    'remittance_id': False,
                    'state': 'pending',
                    'cartera_number': False,
                })
                effect._log_situation('pending', _('Efecto desagrupado/desremesado'))
            if group:
                group._compute_totals()
            if remittance:
                remittance._compute_totals()
        return True

    def _get_reconciled_payment(self):
        self.ensure_one()
        if not self.move_line_id:
            return self.env['account.payment']
        if self.move_line_id.payment_id:
            return self.move_line_id.payment_id
        counterpart_lines = (
            self.move_line_id.matched_debit_ids.mapped('debit_move_id')
            | self.move_line_id.matched_credit_ids.mapped('credit_move_id')
        )
        payments = counterpart_lines.mapped('payment_id')
        return payments[:1]

    def _mark_paid_from_payment(self, payment_date=False):
        effects = self.filtered(lambda e: not e.is_container and e.move_line_id and e.move_line_id.reconciled)
        if effects:
            paid_date = payment_date or fields.Date.context_today(self)
            paid_vals = {'state': 'paid', 'paid_date': paid_date}
            effects.write(paid_vals)
            for effect in effects:
                payment = effect._get_reconciled_payment()
                if payment:
                    effect.payment_id = payment.id
            effects._log_situation('paid', _('Efecto saldado'))
            groups = effects.mapped('group_id')
            remittances = effects.mapped('remittance_id')
            for group in groups:
                group._update_payment_state_from_effects(paid_date)
            for remittance in remittances:
                remittance._update_payment_state_from_effects(paid_date)
        return effects

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
