from odoo import api, fields, models


class AccountEffectPaymentHistory(models.Model):
    _name = 'account.effect.payment.history'
    _description = 'Histórico de pagos del efecto'
    _order = 'date desc, id desc'

    effect_id = fields.Many2one('account.effect', required=True, ondelete='cascade')
    date = fields.Date(required=True, default=fields.Date.context_today)
    payment_id = fields.Many2one('account.payment', readonly=True)
    journal_id = fields.Many2one('account.journal', string='Diario de pago', readonly=True)
    amount = fields.Monetary(required=True, currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', related='effect_id.currency_id', store=True, readonly=True)
    note = fields.Char(string='Concepto')


class AccountEffectSituationHistory(models.Model):
    _name = 'account.effect.situation.history'
    _description = 'Histórico de situaciones del efecto'
    _order = 'date desc, id desc'

    effect_id = fields.Many2one('account.effect', required=True, ondelete='cascade')
    date = fields.Datetime(required=True, default=fields.Datetime.now)
    old_state = fields.Selection(related='effect_id.state', readonly=True)
    state = fields.Selection([
        ('pending', 'Pendiente'), ('grouped', 'Agrupado'), ('remitted', 'Remesado'),
        ('paid', 'Saldado'), ('returned', 'Devuelto'), ('uncollectible', 'Incobrable')
    ], required=True, readonly=True)
    display_state = fields.Selection([('pending', 'Pendiente'), ('paid', 'Saldado'), ('returned', 'Devuelto')], string='Situación', compute='_compute_display_state')

    @api.depends('state')
    def _compute_display_state(self):
        for record in self:
            record.display_state = 'paid' if record.state == 'paid' else ('returned' if record.state == 'returned' else 'pending')
    note = fields.Char(string='Observaciones')

class AccountEffectContainerPaymentHistory(models.Model):
    _name = 'account.effect.container.payment.history'
    _description = 'Histórico de pagos de agrupación o remesa'
    _order = 'date desc, id desc'

    group_id = fields.Many2one('account.effect.group', string='Agrupación', ondelete='cascade')
    remittance_id = fields.Many2one('account.effect.remittance', string='Remesa', ondelete='cascade')
    payment_id = fields.Many2one('account.payment', string='Pago', readonly=True)
    reference = fields.Char(string='Referencia', readonly=True)
    move_id = fields.Many2one('account.move', string='Asiento', readonly=True)
    date = fields.Date(string='Fecha', required=True, default=fields.Date.context_today)
    effect_ids = fields.Many2many('account.effect', string='Agrupar Efectos', readonly=True)
    amount = fields.Monetary(string='Total', required=True, currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', required=True, readonly=True)
    type = fields.Selection([
        ('paid', 'Saldados'),
        ('returned', 'Devoluciones'),
        ('cancelled', 'Anulaciones'),
    ], string='Tipo', required=True, readonly=True)
