from odoo import api, fields, models, _
from odoo.tools.misc import format_date
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
    container_status_state = fields.Selection([('pending', 'Pendiente'), ('partial', 'Saldada parcialmente'), ('paid', 'Saldada'), ('returned', 'Devuelto')], string='Estado de cartera', compute='_compute_container_status_state', store=False)
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
    associated_effect_ids = fields.Many2many('account.effect', compute='_compute_associated_effects', string='Efectos agrupados')
    container_payment_history_ids = fields.Many2many('account.effect.container.payment.history', compute='_compute_container_payment_history', string='Histórico Pagos')
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
    portfolio_chain_id = fields.Many2one(
        'account.effect',
        string='Cartera origen',
        readonly=True,
        copy=False,
        ondelete='cascade',
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

    @api.model
    def _next_cartera_number(self):
        """Return the next number shared by groupings and remittances."""
        seq = self.env['ir.sequence'].search([('code', '=', 'account.effect.cartera')], limit=1)
        number = self.env['ir.sequence'].next_by_code('account.effect.cartera') or '/'
        try:
            candidate = int(number)
        except (TypeError, ValueError):
            return number
        group_numbers = self.env['account.effect.group'].search([]).mapped('cartera_number')
        remittance_numbers = self.env['account.effect.remittance'].search([]).mapped('cartera_number')
        existing = []
        for value in group_numbers + remittance_numbers:
            try:
                existing.append(int(value))
            except (TypeError, ValueError):
                continue
        max_existing = max(existing or [0])
        if candidate <= max_existing:
            candidate = max_existing + 1
            if seq:
                seq.number_next_actual = candidate + 1
        return str(candidate).zfill(seq.padding if seq else 6)

    @api.onchange('effect_type')
    def _onchange_effect_type(self):
        for effect in self:
            if effect.effect_type != 'effect':
                effect.move_id = False
                effect.partner_id = False if effect.effect_type == 'remittance' else effect.partner_id
                effect.amount = 0.0
                effect.invoice_reference = False
                effect.reference = False
            if effect.effect_type == 'effect' and not effect.due_date:
                effect.due_date = fields.Date.context_today(self)

    @api.model_create_multi
    def create(self, vals_list):
        records = self.browse()
        effect_vals = []
        for vals in vals_list:
            effect_type = vals.get('effect_type', 'effect')
            is_container = bool(vals.get('is_container'))
            if effect_type != 'effect' and not is_container:
                container_vals = {
                    'company_id': vals.get('company_id') or self.env.company.id,
                    'company_type': vals.get('company_type') or 'customer',
                    'currency_id': vals.get('currency_id') or self.env.company.currency_id.id,
                    'date': vals.get('due_date') or fields.Date.context_today(self),
                    'due_date': vals.get('due_date') or fields.Date.context_today(self),
                    'bank_journal_id': vals.get('bank_journal_id') or False,
                    'partner_bank_id': vals.get('partner_bank_id') or False,
                    'payment_direction': vals.get('payment_direction') or ('receive' if (vals.get('company_type') or 'customer') == 'customer' else 'send'),
                    'reference': False,
                    'notes': vals.get('notes') or False,
                    'partner_id': vals.get('partner_id') or False,
                }
                if effect_type == 'group':
                    container = self.env['account.effect.group'].create(container_vals)
                else:
                    container_vals.pop('partner_id', None)
                    container_vals['company_type'] = vals.get('company_type') or False
                    container = self.env['account.effect.remittance'].create(container_vals)
                records |= container.container_effect_id
                continue
            if not is_container and not vals.get('partner_id'):
                raise UserError(_('Indica el cliente o proveedor.'))
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('account.effect') or '/'
            records |= super(AccountEffect, self).create(vals)
        for effect in records:
            effect._log_situation(effect.state, _('Efecto creado'))
        return records

    def write(self, vals):
        # When a pending container is edited from its portfolio effect, persist
        # the editable header data on the real grouping/remittance as well.
        if self.env.context.get('cartera_edit_mode') and any(e.is_container for e in self):
            for effect in self:
                if not effect.is_container:
                    continue
                container_vals = {}
                if 'due_date' in vals:
                    container_vals['due_date'] = vals['due_date']
                if 'reference' in vals:
                    container_vals['reference'] = vals['reference']
                if 'partner_id' in vals and effect.container_group_id:
                    container_vals['partner_id'] = vals['partner_id']
                if 'bank_journal_id' in vals:
                    container_vals['bank_journal_id'] = vals['bank_journal_id']
                if 'partner_bank_id' in vals:
                    container_vals['partner_bank_id'] = vals['partner_bank_id']
                if 'company_type' in vals:
                    container_vals['company_type'] = vals['company_type']
                if container_vals:
                    if effect.container_group_id:
                        effect.container_group_id.write(container_vals)
                        effect.container_group_id._compute_totals()
                        effect.container_group_id.with_context(cartera_edit_mode=False)._sync_container_effect()
                    elif effect.container_remittance_id:
                        # Remittance partner is intentionally not tied to a single
                        # customer; the company remains the accounting company.
                        effect.container_remittance_id.write({k: v for k, v in container_vals.items() if k != 'partner_id'})
                        effect.container_remittance_id._compute_totals()
                        effect.container_remittance_id.with_context(cartera_edit_mode=False)._sync_container_effect()
                    vals = dict(vals)
                    for key in ('due_date','reference','bank_journal_id','partner_bank_id','company_type'):
                        vals.pop(key, None)
                    if effect.container_group_id:
                        vals.pop('partner_id', None)
        return super().write(vals)

    @api.depends('portfolio_chain_id', 'portfolio_chain_id.amount', 'portfolio_chain_id.state', 'active', 'container_group_id', 'container_remittance_id')
    def _compute_portfolio_effects(self):
        for effect in self:
            if effect.portfolio_chain_id:
                root = effect.portfolio_chain_id
                effects = (root | self.search([('portfolio_chain_id', '=', root.id), ('active', '=', True)])).exists()
            elif effect.is_container and effect.container_remittance_id:
                effects = effect
            elif effect.is_container and effect.container_group_id:
                effects = self.search([
                    ('container_group_id', '=', effect.container_group_id.id),
                    ('active', '=', True),
                ])
            elif effect.remittance_id:
                effects = effect.remittance_id.container_effect_id or self.browse()
            elif effect.group_id:
                effects = self.search([
                    ('container_group_id', '=', effect.group_id.id),
                    ('active', '=', True),
                ])
            else:
                effects = self.browse()
            effect.portfolio_effect_ids = effects

    def _compute_container_payment_history(self):
        for effect in self:
            if effect.is_container and effect.container_remittance_id:
                history = effect.container_remittance_id.payment_history_ids
            elif effect.is_container and effect.container_group_id:
                history = effect.container_group_id.payment_history_ids
            else:
                history = self.env['account.effect.container.payment.history']
            effect.container_payment_history_ids = history

    def _compute_associated_effects(self):
        for effect in self:
            if effect.is_container and effect.container_remittance_id:
                effects = effect.container_remittance_id.effect_ids.filtered(lambda e: not e.is_container)
            elif effect.is_container and effect.container_group_id:
                effects = effect.container_group_id.effect_ids.filtered(lambda e: not e.is_container)
            elif effect.remittance_id:
                effects = effect.remittance_id.effect_ids.filtered(lambda e: not e.is_container)
            elif effect.group_id:
                effects = effect.group_id.effect_ids.filtered(lambda e: not e.is_container)
            else:
                effects = self.browse()
            effect.associated_effect_ids = effects

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

    @api.depends('state', 'is_container', 'group_id', 'group_id.cartera_number', 'group_id.date', 'remittance_id', 'remittance_id.cartera_number', 'remittance_id.date', 'container_group_id.state', 'container_group_id.cartera_number', 'container_remittance_id.state', 'container_remittance_id.cartera_number')
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

    def _compute_container_status_state(self):
        for effect in self:
            if effect.is_container and effect.container_remittance_id:
                state = effect.container_remittance_id.state
                effect.container_status_state = {
                    'draft': 'pending',
                    'partial': 'partial',
                    'paid': 'paid',
                    'cancelled': 'returned',
                }.get(state, 'pending')
            elif effect.is_container and effect.container_group_id:
                state = effect.container_group_id.state
                effect.container_status_state = 'paid' if state == 'paid' else ('returned' if state == 'cancelled' else 'pending')
            else:
                effect.container_status_state = 'paid' if effect.state == 'paid' else ('returned' if effect.state == 'returned' else 'pending')

    @api.depends(
        'reference', 'invoice_reference', 'name', 'group_id.cartera_number', 'group_id.date',
        'remittance_id.cartera_number', 'remittance_id.date', 'container_group_id.cartera_number',
        'container_group_id.date', 'container_remittance_id.cartera_number', 'container_remittance_id.date',
        'cartera_number', 'effect_type', 'state', 'paid_date'
    )
    def _compute_display_labels(self):
        for effect in self:
            effect.display_reference = '' if effect.is_container or effect.group_id or effect.remittance_id else (effect.invoice_reference or effect.reference or '')
            if effect.is_container and effect.container_remittance_id:
                remittance = effect.container_remittance_id
                effect.display_label = _('Remesa nº %s') % remittance.cartera_number
                if remittance.state == 'paid':
                    effect.display_situation = _('Cobrado - %s') % (format_date(self.env, remittance.paid_date or remittance.date, date_format='dd/MM/yyyy') if (remittance.paid_date or remittance.date) else '')
                elif remittance.state == 'partial':
                    effect.display_situation = _('Saldado parcialmente - %s') % (format_date(self.env, remittance.paid_date or remittance.date, date_format='dd/MM/yyyy') if (remittance.paid_date or remittance.date) else '')
                else:
                    effect.display_situation = _('Pendiente')
            elif effect.is_container and effect.container_group_id:
                group = effect.container_group_id
                effect.display_label = _('Agrupación nº %s') % group.cartera_number
                effect.display_situation = (_('Saldado - %s') % (format_date(self.env, group.paid_date or group.date, date_format='dd/MM/yyyy') if (group.paid_date or group.date) else '')) if group.state == 'paid' else _('Pendiente')
            else:
                if effect.invoice_reference:
                    effect.display_label = _('Efecto de %s') % effect.invoice_reference
                else:
                    effect.display_label = _('Efecto nº %s') % effect.name
                if effect.state == 'grouped' and effect.group_id:
                    effect.display_situation = _('Agrupado en nº %s - %s') % (effect.group_id.cartera_number, format_date(self.env, effect.group_id.date, date_format='dd/MM/yyyy') if effect.group_id.date else '')
                elif effect.state == 'remitted' and effect.remittance_id:
                    effect.display_situation = _('Remesado en nº %s - %s') % (effect.remittance_id.cartera_number, format_date(self.env, effect.remittance_id.date, date_format='dd/MM/yyyy') if effect.remittance_id.date else '')
                elif effect.state == 'paid':
                    if effect.remittance_id:
                        effect.display_situation = _('Saldado desde remesa - %s') % (format_date(self.env, effect.paid_date, date_format='dd/MM/yyyy') if effect.paid_date else '')
                    else:
                        effect.display_situation = _('Saldado - %s') % (format_date(self.env, effect.paid_date, date_format='dd/MM/yyyy') if effect.paid_date else '')
                elif effect.state == 'returned':
                    effect.display_situation = _('Devuelto')
                else:
                    effect.display_situation = _('Pendiente')

    @api.depends(
        'amount', 'move_line_id.amount_residual', 'move_line_id.amount_residual_currency',
        'move_line_id.currency_id', 'move_line_id.reconciled', 'state', 'is_container',
        'container_group_id.amount_pending', 'container_remittance_id.amount_pending'
    )
    def _compute_amount_pending(self):
        for effect in self:
            # Once an individual effect is incorporated into a grouping/remittance,
            # it no longer represents the pending portfolio balance. The container
            # represents that balance, so the individual effect is explicitly 0.
            if not effect.is_container and effect.state in ('grouped', 'remitted', 'paid', 'returned', 'uncollectible'):
                effect.amount_pending = 0.0
            elif effect.is_container and effect.container_remittance_id:
                effect.amount_pending = effect.container_remittance_id.amount_pending
            elif effect.is_container and effect.container_group_id:
                effect.amount_pending = effect.container_group_id.amount_pending
            elif effect.move_line_id and not effect.move_line_id.reconciled:
                effect.amount_pending = abs(effect.move_line_id.amount_residual_currency if effect.move_line_id.currency_id and effect.move_line_id.currency_id != effect.company_id.currency_id else effect.move_line_id.amount_residual)
            else:
                effect.amount_pending = 0.0 if effect.state in ('paid', 'returned', 'uncollectible') else effect.amount

    def _settlement_pending_amount(self):
        self.ensure_one()
        if self.move_line_id:
            if not self.move_line_id.reconciled:
                return abs(self.move_line_id.amount_residual_currency if self.move_line_id.currency_id and self.move_line_id.currency_id != self.company_id.currency_id else self.move_line_id.amount_residual)
            return 0.0
        # Effects created/linked by previous module versions may not have a
        # move line. If they are still genuinely pending in a grouping/remittance
        # (or standalone), their own amount is the pending balance.
        if self.active and self.state in ('pending', 'grouped', 'remitted'):
            return self.amount
        return 0.0

    @api.depends('move_line_id.reconciled', 'move_line_id.amount_residual', 'move_line_id.amount_residual_currency', 'state', 'amount_pending', 'is_container')
    def _compute_payment_state(self):
        for effect in self:
            if effect.is_container:
                effect.payment_state = 'paid' if effect.state == 'paid' or effect.amount_pending <= 0 else 'pending'
            elif effect.state == 'paid':
                effect.payment_state = 'paid'
            elif effect.state in ('grouped', 'remitted'):
                effect.payment_state = 'pending'
            elif effect.amount_pending <= effect.currency_id.rounding:
                effect.payment_state = 'paid'
            elif effect.amount_pending < effect.amount - effect.currency_id.rounding:
                effect.payment_state = 'partial'
            else:
                effect.payment_state = 'pending'

    @api.depends('payment_state', 'paid_date', 'state')
    def _compute_display_payment_state(self):
        for effect in self:
            if effect.is_container:
                if effect.container_remittance_id:
                    r = effect.container_remittance_id
                    effect.display_payment_state = _('Saldado') if r.state == 'paid' else (_('Saldado parcial') if r.state == 'partial' else _('Pendiente'))
                elif effect.container_group_id:
                    effect.display_payment_state = _('Saldado') if effect.container_group_id.state == 'paid' else _('Pendiente')
                else:
                    effect.display_payment_state = _('Saldado') if effect.state == 'paid' else _('Pendiente')
            elif effect.state == 'grouped':
                effect.display_payment_state = _('Agrupado')
            elif effect.state == 'remitted':
                effect.display_payment_state = _('Remesado')
            elif effect.state == 'paid':
                effect.display_payment_state = _('Saldado')
            elif effect.state == 'returned':
                effect.display_payment_state = _('Devuelto')
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
        effects = effects.filtered(lambda e: not e.is_container and e.state in allowed_states and not e.remittance_id and not e.is_portfolio_effect)
        if not effects:
            raise UserError(_('Selecciona efectos válidos para esta operación.'))
        companies = effects.mapped('company_id')
        types = set(effects.mapped('company_type'))
        if len(companies) > 1 or len(types) > 1:
            raise UserError(_('No se pueden mezclar compañías o tipos de empresa distintos.'))
        self._ensure_same_currency(effects)
        return effects

    def action_group_selected(self):
        effects = self._validate_selection(self, ('pending',))
        company = effects.mapped('company_id')[:1]
        company_type = next(iter(set(effects.mapped('company_type'))))
        partners = effects.mapped('partner_id')
        currency = effects.mapped('currency_id')[:1]
        group = self.env['account.effect.group'].create({
            'company_id': company.id,
            'company_type': company_type,
            'partner_id': partners.id if len(partners) == 1 else False,
            'currency_id': currency.id,
        })
        effects.write({'group_id': group.id, 'cartera_number': group.cartera_number})
        group._compute_totals()
        group._sync_container_effect()
        effects._set_state('grouped', _('Agrupación %s') % group.name)
        return {'type': 'ir.actions.act_window', 'name': _('Agrupación'), 'res_model': 'account.effect.group', 'view_mode': 'form', 'res_id': group.id}

    def action_create_remittance_selected(self):
        effects = self._validate_selection(self, ('pending', 'grouped'))
        company = effects.mapped('company_id')[:1]
        company_type = next(iter(set(effects.mapped('company_type'))))
        currency = effects.mapped('currency_id')[:1]
        remittance = self.env['account.effect.remittance'].create({'company_id': company.id, 'company_type': company_type, 'currency_id': currency.id})
        groups = effects.mapped('group_id')
        if groups:
            groups.write({'remittance_id': remittance.id, 'state': 'remitted'})
            for group in groups:
                group._sync_container_effect()
        effects.write({'remittance_id': remittance.id, 'cartera_number': remittance.cartera_number})
        effects._set_state('remitted', _('Remesa %s') % remittance.name)
        remittance._compute_totals()
        container_effect = remittance._sync_container_effect()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Remesa %s') % remittance.cartera_number,
            'res_model': 'account.effect',
            'view_mode': 'form',
            'res_id': container_effect.id,
        }

    def action_add_pending_effects(self):
        self.ensure_one()
        if self.container_remittance_id:
            return self.container_remittance_id.action_add_pending_effects()
        if self.container_group_id:
            return self.container_group_id.action_add_pending_effects()
        raise UserError(_('Este registro no representa una agrupación o remesa.'))

    def action_saldar_entero(self):
        self.ensure_one()
        if self.container_remittance_id:
            return self.container_remittance_id.action_saldar_entero()
        if self.container_group_id:
            return self.container_group_id.action_saldar()
        return self.action_saldar()

    def action_saldar_parcial(self):
        self.ensure_one()
        if self.container_remittance_id:
            return self.container_remittance_id.action_saldar_parcial()
        if self.container_group_id:
            raise UserError(_('Las agrupaciones se saldan desde Saldar (entero), modificando el importe si es necesario.'))
        raise UserError(_('Este efecto no pertenece a una agrupación o remesa.'))

    def action_devolver_efectos(self):
        self.ensure_one()
        if self.container_remittance_id:
            return self.container_remittance_id.action_devolver_efectos()
        raise UserError(_('La devolución de varios efectos solo está disponible desde una remesa.'))

    def action_saldar(self):
        self.ensure_one()
        if self.is_container:
            if self.container_group_id:
                return self.container_group_id.action_saldar()
            if self.container_remittance_id:
                return self.container_remittance_id.action_saldar_entero()
            raise UserError(_('Este registro de cartera no tiene un contenedor asociado.'))
        if self.portfolio_chain_id and not self.move_line_id:
            root = self.portfolio_chain_id
            if not root.move_line_id or root.move_line_id.reconciled:
                raise UserError(_('Este efecto no tiene un vencimiento contable pendiente de pago.'))
            return {
                'name': _('Saldar'),
                'type': 'ir.actions.act_window',
                'res_model': 'account.payment.register',
                'view_mode': 'form',
                'target': 'new',
                'context': {
                    'active_model': 'account.move.line',
                    'active_ids': [root.move_line_id.id],
                    'effect_id': root.id,
                    'cartera_effect_ids': [root.id],
                    'cartera_amount_editable': True,
                    'cartera_effect_amount_override': self.amount,
                    'cartera_portfolio_child_id': self.id,
                },
            }
        if self.state in ('returned', 'uncollectible') or not self.move_line_id or self.move_line_id.reconciled:
            raise UserError(_('Este efecto no tiene un vencimiento contable pendiente de pago.'))
        return {'name': _('Saldar'), 'type': 'ir.actions.act_window', 'res_model': 'account.payment.register', 'view_mode': 'form', 'target': 'new', 'context': {'active_model': 'account.move.line', 'active_ids': [self.move_line_id.id], 'effect_id': self.id, 'cartera_effect_ids': [self.id], 'cartera_amount_editable': True}}

    def action_register_payment(self):
        return self.action_saldar()

    def action_open_container(self):
        self.ensure_one()
        if self.container_remittance_id:
            # Always open the remittance's portfolio effect. This keeps the
            # same effect-centric form regardless of where the remittance is
            # opened from (main list, grouped effect, or remittance action).
            return {
                'type': 'ir.actions.act_window',
                'name': _('Remesa %s') % self.container_remittance_id.cartera_number,
                'res_model': 'account.effect',
                'view_mode': 'form',
                'res_id': self.id,
            }
        if self.container_group_id:
            effect = self.container_group_id._sync_container_effect()
            return {
                'type': 'ir.actions.act_window',
                'name': _('Agrupación %s') % self.container_group_id.cartera_number,
                'res_model': 'account.effect',
                'view_mode': 'form',
                'views': [(self.env.ref('l10n_es_effects.view_account_effect_form').id, 'form')],
                'res_id': effect.id,
            }
        return False

    @api.model
    def _sync_container_effects(self):
        # Recompute stored portfolio balances so records created by older V3
        # test versions are normalized when the main cartera is opened.
        effects = self.search([])
        effects._compute_amount_pending()
        effects._compute_payment_state()
        effects.flush_recordset(['amount_pending', 'payment_state'])
        groups = self.env['account.effect.group'].search([])
        remittances = self.env['account.effect.remittance'].search([])
        for group in groups:
            group._compute_totals()
            group._sync_container_effect()
        for remittance in remittances:
            remittance._compute_totals()
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
            'domain': [('company_type', '=', company_type)],
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
        move_ids.update(self.container_payment_history_ids.mapped('move_id').ids)
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
        related = self.search([('payment_id', '=', payment.id), ('is_container', '=', False)])
        chain_children = self.search([('portfolio_chain_id', 'in', related.ids), ('active', '=', True)]) if related else self.browse()
        if payment.state not in ('draft', 'canceled'):
            payment.action_cancel()
        if chain_children:
            chain_children.write({'active': False})
        for effect in related:
            restore_state = 'remitted' if effect.remittance_id else ('grouped' if effect.group_id else 'pending')
            effect.write({'state': restore_state, 'paid_date': False, 'payment_id': False})
            effect.move_line_id.invalidate_recordset(['amount_residual', 'amount_residual_currency', 'reconciled']) if effect.move_line_id else None
            effect._compute_amount_pending()
            effect._compute_payment_state()
            effect._log_situation(restore_state, _('Saldado anulado · Pago %s') % payment.display_name)
        for child in chain_children:
            child.write({'active': False, 'payment_id': False})
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
        original_payment = self.payment_id
        original_move_line = self.move_line_id
        # A returned effect must put the accounting due line back in an unpaid
        # state before the new pending effect takes ownership of it.
        if original_payment and original_payment.state not in ('draft', 'canceled'):
            original_payment.action_cancel()
        vals = {
            'company_id': self.company_id.id,
            'company_type': self.company_type,
            'partner_id': self.partner_id.id,
            'move_id': self.move_id.id if self.move_id else False,
            'move_line_id': original_move_line.id if original_move_line else False,
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
        # The original effect remains as historical returned evidence; the new
        # pending effect becomes the sole owner of the accounting due line.
        self.write({'state': 'returned', 'payment_id': False, 'move_line_id': False})
        returned = self.env['account.effect'].create(vals)
        self._log_situation('returned', _('Efecto devuelto'))
        returned._log_situation('pending', _('Nuevo efecto pendiente tras devolución de %s') % self.name)
        if original_payment:
            history_vals = {
                'effect_id': self.id,
                'date': today,
                'payment_id': original_payment.id,
                'journal_id': original_payment.journal_id.id,
                'amount': self.amount,
                'note': _('Devolución de efecto'),
            }
            self.env['account.effect.payment.history'].create(history_vals)
            if self.group_id:
                self.env['account.effect.container.payment.history'].create({
                    'group_id': self.group_id.id,
                    'payment_id': original_payment.id,
                    'reference': original_payment.name or self.name,
                    'move_id': original_payment.move_id.id if original_payment.move_id else False,
                    'date': today,
                    'effect_ids': [(6, 0, [self.id])],
                    'amount': self.amount,
                    'currency_id': self.currency_id.id,
                    'type': 'returned',
                })
            if self.remittance_id:
                self.env['account.effect.container.payment.history'].create({
                    'remittance_id': self.remittance_id.id,
                    'payment_id': original_payment.id,
                    'reference': original_payment.name or self.name,
                    'move_id': original_payment.move_id.id if original_payment.move_id else False,
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

    def action_edit_container(self):
        self.ensure_one()
        if not self.is_container:
            raise UserError(_('Solo se puede editar una agrupación o remesa desde su efecto de cartera.'))
        if self.container_remittance_id:
            if self.container_remittance_id.state != 'draft':
                raise UserError(_('Solo se puede editar una remesa pendiente.'))
        elif self.container_group_id:
            if self.container_group_id.state != 'draft':
                raise UserError(_('Solo se puede editar una agrupación pendiente.'))
        else:
            raise UserError(_('Este efecto no está vinculado a una agrupación o remesa.'))
        action = {
            'type': 'ir.actions.act_window',
            'name': self.display_label,
            'res_model': 'account.effect',
            'view_mode': 'form',
            'views': [(self.env.ref('l10n_es_effects.view_account_effect_form').id, 'form')],
            'res_id': self.id,
            'target': 'current',
            'context': dict(self.env.context, cartera_edit_mode=True),
        }
        return action

    def action_finish_container_edit(self):
        self.ensure_one()
        action = {
            'type': 'ir.actions.act_window',
            'name': self.display_label,
            'res_model': 'account.effect',
            'view_mode': 'form',
            'views': [(self.env.ref('l10n_es_effects.view_account_effect_form').id, 'form')],
            'res_id': self.id,
            'target': 'current',
            'context': dict(self.env.context, cartera_edit_mode=False),
        }
        return action

    def action_add_selected_to_group(self):
        group_id = self.env.context.get('group_id')
        if not group_id:
            raise UserError(_('No se ha indicado la agrupación de destino.'))
        group = self.env['account.effect.group'].browse(group_id).exists()
        if not group:
            raise UserError(_('No se ha encontrado la agrupación.'))
        if group.state != 'draft':
            raise UserError(_('Solo se puede editar una agrupación pendiente.'))
        selected = self.filtered(lambda e: not e.is_container and not e.is_portfolio_effect and e.state == 'pending' and not e.group_id and not e.remittance_id)
        if not selected:
            raise UserError(_('Selecciona al menos un efecto pendiente.'))
        if any(e.company_id != group.company_id for e in selected):
            raise UserError(_('No se pueden mezclar compañías.'))
        if any(e.currency_id != group.currency_id for e in selected):
            raise UserError(_('No se pueden mezclar monedas.'))
        if any(e.company_type != group.company_type for e in selected):
            raise UserError(_('No se pueden mezclar clientes y proveedores en una misma agrupación.'))
        selected.write({
            'group_id': group.id,
            'remittance_id': False,
            'cartera_number': group.cartera_number,
            'state': 'grouped',
        })
        group._compute_totals()
        group._sync_container_effect()
        return {'type': 'ir.actions.act_window_close'}

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
            'name': _('Crear efecto'),
            'res_model': 'account.effect',
            'view_mode': 'form',
            'views': [(self.env.ref('l10n_es_effects.view_account_effect_form').id, 'form')],
            'target': 'current',
            'context': {
                'default_company_type': self.env.context.get('default_company_type', 'customer'),
                'default_effect_type': 'effect',
                'default_due_date': fields.Date.context_today(self),
                'cartera_new_mode': True,
            },
        }

    def action_new_effect(self):
        return {'type': 'ir.actions.act_window', 'name': _('Crear efecto'), 'res_model': 'account.effect', 'view_mode': 'form', 'target': 'current', 'context': dict(self.env.context)}

    def action_ungroup_selected(self):
        """Desvincula los efectos de agrupaciones/remesas sin marcar devolución."""
        containers = self.filtered('is_container')
        for container in containers:
            if container.container_remittance_id:
                if container.container_remittance_id._has_active_payments():
                    raise UserError(_('No se pueden quitar efectos de una remesa que tiene pagos activos. Anula primero los pagos asociados a la remesa.'))
                return container.container_remittance_id.action_ungroup_selected()
            if container.container_group_id:
                return container.container_group_id.action_ungroup_selected()
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
