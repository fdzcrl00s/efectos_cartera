from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountEffectRemittance(models.Model):
    _name = 'account.effect.remittance'
    _description = 'Remesa de efectos'
    _order = 'date desc, id desc'

    name = fields.Char(string='Nº Remesa', required=True, copy=False, readonly=True, default=lambda self: _('Nuevo'))
    date = fields.Date(string='Fecha', required=True, default=fields.Date.context_today)
    due_date = fields.Date(string='Vencimiento')
    journal_id = fields.Many2one('account.journal', string='Diario bancario', domain="[('type', '=', 'bank'), ('company_id', '=', company_id)]")
    company_id = fields.Many2one('res.company', default=lambda self: self.env.company, required=True, index=True)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', store=True, readonly=True)
    state = fields.Selection([
        ('draft', 'Borrador'), ('generated', 'Generada'), ('sent', 'Enviada al banco'),
        ('presented', 'Presentada'), ('paid', 'Cobrada'), ('partial', 'Parcialmente cobrada'),
        ('returned', 'Devuelta'), ('cancelled', 'Anulada')
    ], default='draft', required=True, index=True)
    effect_ids = fields.One2many('account.effect', 'remittance_id', string='Efectos')
    effect_count = fields.Integer(compute='_compute_counts')
    amount_total = fields.Monetary(compute='_compute_counts', store=True)
    notes = fields.Text()

    @api.depends('effect_ids.amount', 'effect_ids.payment_state')
    def _compute_counts(self):
        for rec in self:
            effects = rec.effect_ids.filtered(lambda e: e.payment_state != 'cancelled')
            rec.effect_count = len(effects)
            rec.amount_total = sum(effects.mapped('amount'))

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', _('Nuevo')) == _('Nuevo'):
                vals['name'] = self.env['ir.sequence'].next_by_code('account.effect.remittance') or _('Nuevo')
        return super().create(vals_list)

    def action_generate(self):
        for rec in self:
            if not rec.effect_ids:
                raise UserError(_('Añade al menos un efecto a la remesa.'))
            rec.effect_ids.action_mark_remitted()
            rec.state = 'generated'
        return True

    def action_send(self):
        self.write({'state': 'sent'})
        return True

    def action_present(self):
        self.write({'state': 'presented'})
        return True

    def action_paid(self):
        self.write({'state': 'paid'})
        self.effect_ids.filtered(lambda e: e.payment_state not in ('paid', 'cancelled')).write({'payment_state': 'paid', 'situation': 'paid'})
        return True

    def action_return(self):
        self.write({'state': 'returned'})
        self.effect_ids.filtered(lambda e: e.payment_state not in ('paid', 'cancelled')).action_mark_returned()
        return True

    def action_cancel(self):
        self.effect_ids.action_unlink_remittance()
        self.write({'state': 'cancelled'})
        return True
