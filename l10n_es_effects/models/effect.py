from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountEffect(models.Model):
    _name = 'account.effect'
    _description = 'Efecto de cartera'
    _order = 'due_date, id'
    _check_company_auto = True

    name = fields.Char(
        string='Nº efecto',
        required=True,
        copy=False,
        readonly=True,
        default=lambda self: _('Nuevo'),
    )
    company_id = fields.Many2one(
        'res.company',
        string='Compañía',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Cliente/Proveedor',
        required=True,
        index=True,
        check_company=True,
    )
    company_type = fields.Selection(
        [('customer', 'Cliente'), ('supplier', 'Proveedor')],
        string='Tipo',
        required=True,
        index=True,
    )
    move_id = fields.Many2one(
        'account.move',
        string='Factura',
        readonly=True,
        index=True,
        check_company=True,
        ondelete='restrict',
    )
    move_line_id = fields.Many2one(
        'account.move.line',
        string='Vencimiento contable',
        readonly=True,
        index=True,
        check_company=True,
        ondelete='restrict',
    )
    reference = fields.Char(string='Referencia', readonly=True)
    due_date = fields.Date(string='Vencimiento', required=True, index=True)
    effect_type = fields.Selection(
        [
            ('effect', 'Efecto'),
            ('group', 'Agrupación'),
            ('remittance', 'Remesa'),
        ],
        string='Tipo',
        required=True,
        default='effect',
    )
    amount = fields.Monetary(
        string='Total',
        required=True,
        currency_field='currency_id',
    )
    currency_id = fields.Many2one(
        'res.currency',
        string='Moneda',
        required=True,
        default=lambda self: self.env.company.currency_id,
    )
    state = fields.Selection(
        [
            ('pending', 'Pendiente'),
            ('grouped', 'Agrupado'),
            ('remitted', 'Remesado'),
            ('paid', 'Saldado'),
            ('returned', 'Devuelto'),
            ('uncollectible', 'Incobrable'),
        ],
        string='Estado',
        required=True,
        default='pending',
        index=True,
        copy=False,
    )
    group_id = fields.Many2one(
        'account.effect.group',
        string='Agrupación',
        readonly=True,
        copy=False,
        check_company=True,
    )
    remittance_id = fields.Many2one(
        'account.effect.remittance',
        string='Remesa',
        readonly=True,
        copy=False,
        check_company=True,
    )
    payment_id = fields.Many2one(
        'account.payment',
        string='Pago',
        readonly=True,
        copy=False,
        check_company=True,
    )
    payment_move_id = fields.Many2one(
        'account.move',
        string='Asiento de pago',
        related='payment_id.move_id',
        readonly=True,
    )
    origin_move_id = fields.Many2one(
        'account.move',
        string='Asiento de factura',
        related='move_id',
        readonly=True,
    )
    bank_journal_id = fields.Many2one(
        'account.journal',
        string='Diario de cobro/pago',
        domain="[('type', 'in', ('bank', 'cash', 'credit')), ('company_id', '=', company_id)]",
        check_company=True,
    )
    notes = fields.Text(string='Notas')
    active = fields.Boolean(default=True)

    _sql_constraints = [
        (
            'move_line_unique',
            'unique(move_line_id)',
            'Ya existe un efecto para este vencimiento contable.',
        ),
    ]

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Nuevo')) == _('Nuevo'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'account.effect'
                ) or _('Nuevo')
        return super().create(vals_list)

    def action_group_selected(self):
        effects = self.filtered(lambda e: e.state == 'pending')
        if not effects:
            raise UserError(_('Selecciona al menos un efecto pendiente.'))
        if len(effects.mapped('company_id')) != 1:
            raise UserError(_('Todos los efectos deben pertenecer a la misma compañía.'))
        if len(effects.mapped('company_type')) != 1:
            raise UserError(_('No puedes mezclar efectos de clientes y proveedores.'))
        group = self.env['account.effect.group'].create({
            'company_id': effects.company_id.id,
            'company_type': effects.company_type,
            'partner_id': effects.partner_id.id if len(effects.mapped('partner_id')) == 1 else False,
            'effect_ids': [(6, 0, effects.ids)],
        })
        effects.write({'state': 'grouped'})
        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.effect.group',
            'view_mode': 'form',
            'res_id': group.id,
        }

    def action_register_payment(self):
        self.ensure_one()
        if self.state == 'paid':
            raise UserError(_('El efecto ya está saldado.'))
        if not self.move_line_id:
            raise UserError(_('El efecto no tiene asociado un vencimiento contable.'))
        if self.move_line_id.reconciled:
            raise UserError(_('El vencimiento contable de este efecto ya está conciliado.'))

        ctx = {
            'active_model': 'account.move.line',
            'active_ids': self.move_line_id.ids,
            'active_id': self.move_line_id.id,
            'effect_id': self.id,
            'default_communication': self.reference,
        }
        if self.bank_journal_id:
            ctx['default_journal_id'] = self.bank_journal_id.id

        return {
            'name': _('Saldar efecto'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment.register',
            'view_mode': 'form',
            'target': 'new',
            'context': ctx,
        }

    def action_mark_returned(self):
        for effect in self:
            if effect.state == 'paid':
                raise UserError(_('Un efecto saldado no puede marcarse como devuelto.'))
            effect.write({'state': 'returned'})

    def action_mark_uncollectible(self):
        for effect in self:
            if effect.state == 'paid':
                raise UserError(_('Un efecto saldado no puede marcarse como incobrable.'))
            effect.write({'state': 'uncollectible'})
