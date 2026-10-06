from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountEffect(models.Model):
    _name = 'account.effect'
    _description = 'Efecto de cartera'
    _order = 'due_date, id'

    name = fields.Char(string='Número', required=True, readonly=True, copy=False, default='/')
    company_id = fields.Many2one(
        'res.company', required=True, readonly=True,
        default=lambda self: self.env.company
    )
    partner_id = fields.Many2one('res.partner', string='Cliente/Proveedor', required=True, readonly=True)
    company_type = fields.Selection(
        [('customer', 'Cliente'), ('supplier', 'Proveedor')],
        string='Tipo', required=True, readonly=True
    )
    move_id = fields.Many2one('account.move', string='Factura', required=True, readonly=True, index=True)
    move_line_id = fields.Many2one(
        'account.move.line', string='Vencimiento', required=True, readonly=True,
        ondelete='restrict', index=True
    )
    reference = fields.Char(string='Referencia', readonly=True)
    due_date = fields.Date(string='Vencimiento', required=True, readonly=True, index=True)
    amount = fields.Monetary(string='Importe', required=True, readonly=True)
    currency_id = fields.Many2one('res.currency', required=True, readonly=True)
    state = fields.Selection(
        [
            ('pending', 'Pendiente'),
            ('grouped', 'Agrupado'),
            ('remitted', 'Remesado'),
            ('paid', 'Pagado'),
            ('returned', 'Devuelto'),
            ('uncollectible', 'Incobrable'),
        ],
        string='Estado', required=True, default='pending', index=True
    )
    group_id = fields.Many2one('account.effect.group', string='Agrupación', readonly=True, ondelete='set null')
    remittance_id = fields.Many2one('account.effect.remittance', string='Remesa', readonly=True, ondelete='set null')
    payment_id = fields.Many2one('account.payment', string='Pago', readonly=True, copy=False)
    payment_move_id = fields.Many2one('account.move', string='Asiento de pago', related='payment_id.move_id', readonly=True)
    origin_move_id = fields.Many2one('account.move', string='Asiento de origen', related='move_id', readonly=True)
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
        return super().create(vals_list)

    def _ensure_same_currency(self, effects):
        currencies = effects.mapped('currency_id')
        if len(currencies) > 1:
            raise UserError(_('No se pueden mezclar efectos de distintas monedas en una misma agrupación o remesa.'))

    def action_group_selected(self):
        effects = self.filtered(lambda e: e.state == 'pending' and not e.group_id and not e.remittance_id)
        if not effects:
            raise UserError(_('Selecciona al menos un efecto pendiente.'))

        companies = effects.mapped('company_id')
        types = effects.mapped('company_type')
        if len(companies) > 1:
            raise UserError(_('No se pueden agrupar efectos de distintas compañías.'))
        if len(types) > 1:
            raise UserError(_('No se pueden mezclar efectos de clientes y proveedores.'))

        self._ensure_same_currency(effects)

        group = self.env['account.effect.group'].create({
            'company_id': effects.company_id.id,
            'company_type': effects.company_type,
            'partner_id': effects.partner_id.id if len(effects.mapped('partner_id')) == 1 else False,
            'currency_id': effects.currency_id.id,
        })
        effects.write({
            'group_id': group.id,
            'state': 'grouped',
        })
        return {
            'type': 'ir.actions.act_window',
            'name': _('Agrupación'),
            'res_model': 'account.effect.group',
            'view_mode': 'form',
            'res_id': group.id,
        }

    def action_register_payment(self):
        self.ensure_one()
        if self.state in ('paid', 'returned', 'uncollectible'):
            raise UserError(_('Este efecto no admite un nuevo pago.'))
        if not self.move_line_id or self.move_line_id.reconciled:
            raise UserError(_('El vencimiento del efecto ya está conciliado o no está disponible.'))

        return {
            'name': _('Registrar pago'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment.register',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_model': 'account.move.line',
                'active_ids': [self.move_line_id.id],
                'effect_id': self.id,
            },
        }

    def action_mark_returned(self):
        self.filtered(lambda e: e.state not in ('paid', 'uncollectible')).write({'state': 'returned'})

    def action_mark_uncollectible(self):
        self.filtered(lambda e: e.state != 'paid').write({'state': 'uncollectible'})
