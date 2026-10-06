from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountEffectGroup(models.Model):
    _name = 'account.effect.group'
    _description = 'Agrupación de efectos'
    _order = 'date desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string='Nº agrupación',
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
        check_company=True,
    )
    partner_id = fields.Many2one(
        'res.partner',
        string='Cliente/Proveedor',
        check_company=True,
    )
    company_type = fields.Selection(
        [('customer', 'Cliente'), ('supplier', 'Proveedor')],
        string='Tipo',
        required=True,
    )
    date = fields.Date(
        string='Fecha',
        required=True,
        default=fields.Date.context_today,
    )
    effect_ids = fields.One2many(
        'account.effect',
        'group_id',
        string='Efectos',
    )
    effect_count = fields.Integer(
        string='Nº efectos',
        compute='_compute_totals',
    )
    amount_total = fields.Monetary(
        string='Total',
        currency_field='currency_id',
        compute='_compute_totals',
    )
    currency_id = fields.Many2one(
        'res.currency',
        related='company_id.currency_id',
        readonly=True,
    )
    state = fields.Selection(
        [
            ('draft', 'Borrador'),
            ('remitted', 'Remesada'),
            ('cancelled', 'Cancelada'),
        ],
        string='Estado',
        required=True,
        default='draft',
    )
    remittance_id = fields.Many2one(
        'account.effect.remittance',
        string='Remesa',
        readonly=True,
        check_company=True,
    )
    notes = fields.Text(string='Notas')

    @api.depends('effect_ids', 'effect_ids.amount')
    def _compute_totals(self):
        for group in self:
            group.effect_count = len(group.effect_ids)
            group.amount_total = sum(group.effect_ids.mapped('amount'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Nuevo')) == _('Nuevo'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'account.effect.group'
                ) or _('Nuevo')
        return super().create(vals_list)

    def action_create_remittance(self):
        self.ensure_one()
        if self.state != 'draft':
            raise UserError(_('Solo se pueden remesar agrupaciones en borrador.'))
        if not self.effect_ids:
            raise UserError(_('La agrupación no contiene efectos.'))

        remittance = self.env['account.effect.remittance'].create({
            'company_id': self.company_id.id,
            'company_type': self.company_type,
            'date': fields.Date.context_today(self),
            'group_ids': [(6, 0, self.ids)],
        })
        self.write({'state': 'remitted', 'remittance_id': remittance.id})
        self.effect_ids.write({
            'state': 'remitted',
            'remittance_id': remittance.id,
        })

        return {
            'type': 'ir.actions.act_window',
            'res_model': 'account.effect.remittance',
            'view_mode': 'form',
            'res_id': remittance.id,
        }
