from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountEffect(models.Model):
    _name = 'account.effect'
    _description = 'Efecto de cartera'
    _order = 'due_date desc, id desc'

    name = fields.Char(string='Nº Efecto', required=True, readonly=True, copy=False, default='/')
    company_id = fields.Many2one('res.company', required=True, readonly=True, default=lambda self: self.env.company)
    partner_id = fields.Many2one('res.partner', string='Cliente/Proveedor', required=True)
    company_type = fields.Selection(
        [('customer', 'Cliente'), ('supplier', 'Proveedor')],
        string='Tipo', required=True, readonly=True,
        default=lambda self: 'customer' if self.env.context.get('default_company_type') != 'supplier' else 'supplier',
    )
    move_id = fields.Many2one('account.move', string='Factura', readonly=True, index=True)
    move_line_id = fields.Many2one(
        'account.move.line', string='Vencimiento contable', readonly=True,
        ondelete='restrict', index=True
    )
    reference = fields.Char(string='Referencia')
    invoice_name = fields.Char(string='Nombre', related='move_id.name', readonly=True)
    due_date = fields.Date(string='Vencimiento', required=True, index=True)
    effect_type = fields.Selection([('effect', 'Efecto')], string='Tipo de Efecto', required=True, default='effect', readonly=True)
    amount = fields.Monetary(string='Total', required=True)
    currency_id = fields.Many2one('res.currency', required=True, default=lambda self: self.env.company.currency_id)
    amount_pending = fields.Monetary(string='Total pendiente', compute='_compute_amount_pending', currency_field='currency_id', store=True)
    payment_state = fields.Selection(
        [('pending', 'Pendiente'), ('partial', 'Parcial'), ('paid', 'Saldado')],
        string='Estado del pago', compute='_compute_payment_state', store=True,
    )
    state = fields.Selection(
        [('pending', 'Pendiente'), ('grouped', 'Agrupado'), ('remitted', 'Remesado'),
         ('paid', 'Saldado'), ('returned', 'Devuelto'), ('uncollectible', 'Incobrable')],
        string='Situación', required=True, default='pending', index=True
    )
    group_id = fields.Many2one('account.effect.group', string='Agrupación', readonly=True, ondelete='set null')
    remittance_id = fields.Many2one('account.effect.remittance', string='Remesa', readonly=True, ondelete='set null')
    payment_id = fields.Many2one('account.payment', string='Pago', readonly=True, copy=False)
    payment_move_id = fields.Many2one('account.move', string='Asiento de pago', related='payment_id.move_id', readonly=True)
    bank_journal_id = fields.Many2one('account.journal', string='Diario bancario')
    notes = fields.Text(string='Notas')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('move_line_unique', 'unique(move_line_id)', 'Solo puede existir un efecto por vencimiento contable.'),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', '/') == '/':
                vals['name'] = self.env['ir.sequence'].next_by_code('account.effect') or '/'
            if not vals.get('company_type'):
                vals['company_type'] = self.env.context.get('default_company_type', 'customer')
        return super().create(vals_list)

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

    @api.depends('move_line_id.reconciled', 'move_line_id.amount_residual', 'move_line_id.amount_residual_currency', 'state')
    def _compute_payment_state(self):
        for effect in self:
            if effect.state == 'paid' or (effect.move_line_id and effect.move_line_id.reconciled):
                effect.payment_state = 'paid'
            elif effect.move_line_id:
                pending = effect.amount_pending
                effect.payment_state = 'partial' if pending < effect.amount else 'pending'
            else:
                effect.payment_state = 'pending'

    def _ensure_same_currency(self, effects):
        currencies = effects.mapped('currency_id')
        if len(currencies) > 1:
            raise UserError(_('No se pueden mezclar efectos de distintas monedas en una misma agrupación o remesa.'))

    def _validate_selection(self, effects, allowed_states):
        effects = effects.filtered(lambda e: e.state in allowed_states and not e.remittance_id)
        if not effects:
            raise UserError(_('Selecciona efectos válidos para esta operación.'))
        companies = effects.mapped('company_id')
        types = effects.mapped('company_type')
        if len(companies) > 1:
            raise UserError(_('No se pueden mezclar efectos de distintas compañías.'))
        if len(types) > 1:
            raise UserError(_('No se pueden mezclar efectos de clientes y proveedores.'))
        self._ensure_same_currency(effects)
        return effects

    def action_group_selected(self):
        effects = self._validate_selection(self, ('pending',))
        group = self.env['account.effect.group'].create({
            'company_id': effects.company_id.id,
            'company_type': effects.company_type,
            'partner_id': effects.partner_id.id if len(effects.mapped('partner_id')) == 1 else False,
            'currency_id': effects.currency_id.id,
        })
        effects.write({'group_id': group.id, 'state': 'grouped'})
        return {
            'type': 'ir.actions.act_window', 'name': _('Agrupación'),
            'res_model': 'account.effect.group', 'view_mode': 'form', 'res_id': group.id,
        }

    def action_create_remittance_selected(self):
        effects = self._validate_selection(self, ('grouped',))
        remittance = self.env['account.effect.remittance'].create({
            'company_id': effects.company_id.id,
            'company_type': effects.company_type,
            'currency_id': effects.currency_id.id,
        })
        groups = effects.mapped('group_id')
        groups.write({'remittance_id': remittance.id, 'state': 'remitted'})
        effects.write({'remittance_id': remittance.id, 'state': 'remitted'})
        return {
            'type': 'ir.actions.act_window', 'name': _('Remesa'),
            'res_model': 'account.effect.remittance', 'view_mode': 'form', 'res_id': remittance.id,
        }

    def action_saldar(self):
        self.ensure_one()
        if self.state in ('paid', 'returned', 'uncollectible'):
            raise UserError(_('Este efecto no admite un nuevo pago.'))
        if not self.move_line_id or self.move_line_id.reconciled:
            raise UserError(_('Este efecto no tiene un vencimiento contable pendiente de pago.'))
        return {
            'name': _('Saldar'), 'type': 'ir.actions.act_window',
            'res_model': 'account.payment.register', 'view_mode': 'form', 'target': 'new',
            'context': {'active_model': 'account.move.line', 'active_ids': [self.move_line_id.id], 'effect_id': self.id},
        }

    def action_register_payment(self):
        return self.action_saldar()

    def action_mark_returned(self):
        self.filtered(lambda e: e.state not in ('paid', 'uncollectible')).write({'state': 'returned'})

    def action_mark_uncollectible(self):
        self.filtered(lambda e: e.state != 'paid').write({'state': 'uncollectible'})
