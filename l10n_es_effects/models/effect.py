from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


class AccountEffect(models.Model):
    _name = 'account.effect'
    _description = 'Efecto de cartera'
    _order = 'due_date asc, id desc'
    _rec_name = 'name'

    name = fields.Char(string='Nombre', compute='_compute_name', store=True)
    effect_number = fields.Char(string='Nº Efecto', required=True, copy=False, readonly=True, default=lambda self: _('Nuevo'))
    portfolio_number = fields.Char(string='Nº Cartera', copy=False, readonly=True)
    reference = fields.Char(string='Nº Referencia')
    due_date = fields.Date(string='Vencimiento', required=True, index=True)
    partner_id = fields.Many2one('res.partner', string='Cliente/Proveedor', required=True, index=True)
    move_id = fields.Many2one('account.move', string='Documento Contable', index=True, ondelete='set null')
    move_line_id = fields.Many2one('account.move.line', string='Línea contable', index=True, ondelete='set null')
    payment_id = fields.Many2one('account.payment', string='Pago', readonly=True, copy=False)
    company_id = fields.Many2one('res.company', string='Empresa', required=True, default=lambda self: self.env.company, index=True)
    currency_id = fields.Many2one('res.currency', string='Moneda', compute='_compute_currency_id', store=True, readonly=True)
    bank_account_id = fields.Many2one('res.partner.bank', string='Cuenta bancaria')
    destination_account_id = fields.Many2one('account.account', string='Cuenta destino')
    journal_id = fields.Many2one('account.journal', string='Diario de pago', domain="[('company_id', '=', company_id)]")
    payment_method = fields.Selection([
        ('bank_transfer', 'Transferencia bancaria'),
        ('direct_debit', 'Domiciliación bancaria'),
        ('cash', 'Efectivo'),
        ('card', 'Tarjeta'),
        ('other', 'Otro'),
    ], string='Documento de Pago', default='bank_transfer', required=True)
    payment_state = fields.Selection([
        ('pending', 'Pendiente'),
        ('grouped', 'Agrupado'),
        ('remitted', 'Remesado'),
        ('paid', 'Saldado'),
        ('returned', 'Devuelto'),
        ('uncollectible', 'Incobrable'),
        ('cancelled', 'Anulado'),
    ], string='Estado del Pago', default='pending', required=True, index=True)
    situation = fields.Selection([
        ('pending', 'Pendiente'),
        ('grouped', 'Agrupado'),
        ('in_portfolio', 'Efecto en Cartera'),
        ('remitted', 'Remesado'),
        ('paid', 'Saldado'),
        ('returned', 'Devuelto'),
        ('uncollectible', 'Incobrable'),
        ('cancelled', 'Anulado'),
    ], string='Situación', default='pending', required=True, index=True)
    effect_type = fields.Selection([
        ('effect', 'Efecto'),
        ('grouping', 'Agrupación'),
        ('remittance', 'Remesa'),
        ('advance', 'Anticipo'),
        ('suplido', 'Suplido'),
        ('forecast', 'Previsión'),
        ('pos', 'Punto de Venta'),
    ], string='Tipo de Efecto', default='effect', required=True)
    company_type = fields.Selection([
        ('customer', 'Cliente'), ('supplier', 'Proveedor'), ('employee', 'Empleado')
    ], string='Tipo de Empresa', default='customer', required=True)
    payment_type = fields.Selection([
        ('receive', 'Recibir dinero'), ('send', 'Enviar dinero')
    ], string='Tipo de pago', required=True, default='receive')
    amount = fields.Monetary(string='Total', required=True)
    signed_amount = fields.Monetary(string='Total con signo', compute='_compute_signed_amount', store=True)
    pending_amount = fields.Monetary(string='Pendiente', compute='_compute_pending_amount', store=True)
    residual_difference = fields.Monetary(string='Total Descuadre', compute='_compute_pending_amount')
    remittance_id = fields.Many2one('account.effect.remittance', string='Remesa', readonly=True, ondelete='set null')
    origin_effect_id = fields.Many2one('account.effect', string='Efecto origen', readonly=True, ondelete='set null')
    child_effect_ids = fields.One2many('account.effect', 'origin_effect_id', string='Efectos agrupados')
    notes = fields.Text(string='Notas')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('effect_number_company_uniq', 'unique(effect_number, company_id)', 'El número de efecto debe ser único por empresa.'),
    ]

    @api.depends('effect_number', 'reference')
    def _compute_name(self):
        for rec in self:
            rec.name = rec.reference or rec.effect_number or _('Nuevo')

    @api.depends('company_id')
    def _compute_currency_id(self):
        for rec in self:
            rec.currency_id = rec.company_id.currency_id

    @api.depends('amount', 'payment_type')
    def _compute_signed_amount(self):
        for rec in self:
            rec.signed_amount = rec.amount if rec.payment_type == 'receive' else -rec.amount

    @api.depends('amount', 'payment_state')
    def _compute_pending_amount(self):
        for rec in self:
            rec.pending_amount = rec.amount if rec.payment_state not in ('paid', 'cancelled', 'uncollectible') else 0.0
            rec.residual_difference = rec.pending_amount

    @api.constrains('amount')
    def _check_amount(self):
        for rec in self:
            if rec.amount < 0:
                raise ValidationError(_('El importe del efecto no puede ser negativo.'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('effect_number', _('Nuevo')) == _('Nuevo'):
                vals['effect_number'] = self.env['ir.sequence'].next_by_code('account.effect') or _('Nuevo')
            if not vals.get('portfolio_number'):
                vals['portfolio_number'] = self.env['ir.sequence'].next_by_code('account.effect.portfolio')
        return super().create(vals_list)

    def action_set_in_portfolio(self):
        self.write({'payment_state': 'pending', 'situation': 'in_portfolio'})
        return True

    def action_group(self):
        self.write({'payment_state': 'grouped', 'situation': 'grouped'})
        return True

    def action_mark_remitted(self):
        self.write({'payment_state': 'remitted', 'situation': 'remitted'})
        return True

    def action_mark_returned(self):
        self.write({'payment_state': 'returned', 'situation': 'returned'})
        return True

    def action_mark_uncollectible(self):
        self.write({'payment_state': 'uncollectible', 'situation': 'uncollectible'})
        return True

    def action_cancel(self):
        self.write({'payment_state': 'cancelled', 'situation': 'cancelled', 'active': False})
        return True

    def action_unlink_remittance(self):
        self.write({'remittance_id': False, 'payment_state': 'pending', 'situation': 'in_portfolio'})
        return True

    def action_register_payment(self):
        self.ensure_one()
        if self.payment_state == 'paid':
            raise UserError(_('El efecto ya está saldado.'))
        if not self.move_id:
            raise UserError(_('Este efecto no está vinculado a una factura/asiento.'))
        return self.env['account.payment.register'].with_context(
            active_model='account.move',
            active_ids=self.move_id.ids,
            default_amount=self.pending_amount,
        ).action_create_payments()

    def action_group_selected(self):
        """Agrupa los efectos seleccionados en un efecto padre."""
        effects = self.filtered(lambda e: e.active and e.payment_state in ('pending', 'grouped') and not e.remittance_id and not e.origin_effect_id)
        if len(effects) < 2:
            raise UserError(_('Selecciona al menos dos efectos pendientes para agruparlos.'))
        companies = effects.mapped('company_id')
        partners = effects.mapped('partner_id')
        if len(companies) != 1:
            raise UserError(_('Todos los efectos deben pertenecer a la misma empresa.'))
        if len(partners) != 1:
            raise UserError(_('Para esta primera versión, todos los efectos de una agrupación deben pertenecer al mismo cliente/proveedor.'))
        total = sum(effects.mapped('amount'))
        parent = self.create({
            'partner_id': partners.id,
            'company_id': companies.id,
            'due_date': min(effects.mapped('due_date')),
            'reference': _('Agrupación de %s efectos') % len(effects),
            'amount': total,
            'payment_type': effects[0].payment_type,
            'company_type': effects[0].company_type,
            'effect_type': 'grouping',
            'payment_method': effects[0].payment_method,
            'payment_state': 'pending',
            'situation': 'pending',
            'notes': _('Agrupación creada a partir de: %s') % ', '.join(effects.mapped('effect_number')),
        })
        effects.write({'origin_effect_id': parent.id, 'payment_state': 'grouped', 'situation': 'grouped'})
        return {
            'type': 'ir.actions.act_window',
            'name': _('Agrupación'),
            'res_model': 'account.effect',
            'view_mode': 'form',
            'res_id': parent.id,
        }

    def action_ungroup(self):
        parents = self.filtered(lambda e: e.effect_type == 'grouping')
        if not parents:
            raise UserError(_('Selecciona una agrupación.'))
        for parent in parents:
            parent.child_effect_ids.write({'origin_effect_id': False, 'payment_state': 'pending', 'situation': 'in_portfolio'})
            parent.action_cancel()
        return True
