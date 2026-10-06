from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountEffectRemittance(models.Model):
    _name = 'account.effect.remittance'
    _description = 'Remesa de efectos'
    _order = 'date desc, id desc'
    _check_company_auto = True

    name = fields.Char(
        string='Nº remesa',
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
    group_ids = fields.One2many(
        'account.effect.group',
        'remittance_id',
        string='Agrupaciones',
    )
    effect_ids = fields.One2many(
        'account.effect',
        'remittance_id',
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
            ('sent', 'Remesada'),
            ('paid', 'Saldada'),
            ('cancelled', 'Cancelada'),
        ],
        string='Estado',
        required=True,
        default='draft',
    )
    notes = fields.Text(string='Notas')

    @api.depends('effect_ids', 'effect_ids.amount', 'group_ids', 'group_ids.effect_ids')
    def _compute_totals(self):
        for remittance in self:
            effects = remittance.effect_ids
            if not effects and remittance.group_ids:
                effects = remittance.group_ids.mapped('effect_ids')
            remittance.effect_count = len(effects)
            remittance.amount_total = sum(effects.mapped('amount'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Nuevo')) == _('Nuevo'):
                vals['name'] = self.env['ir.sequence'].next_by_code(
                    'account.effect.remittance'
                ) or _('Nuevo')
        return super().create(vals_list)

    def action_mark_sent(self):
        for remittance in self:
            effects = remittance.effect_ids or remittance.group_ids.mapped('effect_ids')
            if not effects:
                raise UserError(_('La remesa no contiene efectos.'))
            remittance.write({
                'state': 'sent',
                'effect_ids': [(6, 0, effects.ids)],
            })
            effects.write({
                'state': 'remitted',
                'remittance_id': remittance.id,
            })

    def action_register_payments(self):
        self.ensure_one()
        effects = self.effect_ids.filtered(
            lambda e: e.state in ('remitted', 'pending')
            and e.move_line_id
            and not e.move_line_id.reconciled
        )
        if not effects:
            raise UserError(_('No hay efectos pendientes de liquidar en esta remesa.'))

        return {
            'name': _('Liquidar remesa'),
            'type': 'ir.actions.act_window',
            'res_model': 'account.payment.register',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'active_model': 'account.move.line',
                'active_ids': effects.mapped('move_line_id').ids,
                'effect_remittance_id': self.id,
            },
        }
