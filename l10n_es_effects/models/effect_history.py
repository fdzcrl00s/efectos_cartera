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
    note = fields.Char(string='Observaciones')
