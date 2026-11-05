from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountEffectPaymentHistory(models.Model):
    _name = 'account.effect.payment.history'
    _description = 'Histórico de pagos del efecto'
    _order = 'date desc, id desc'

    effect_id = fields.Many2one('account.effect', required=True, ondelete='cascade')
    date = fields.Date(required=True, default=fields.Date.context_today)
    payment_id = fields.Many2one('account.payment', readonly=True)
    move_id = fields.Many2one('account.move', string='Asiento', readonly=True)
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
    payment_ids = fields.Many2many(
        'account.payment',
        'account_payment_container_history_rel',
        'history_id', 'payment_id',
        string='Pagos por cliente', readonly=True,
    )
    reference = fields.Char(string='Referencia', readonly=True)
    move_id = fields.Many2one('account.move', string='Asiento', readonly=True)
    date = fields.Date(string='Fecha', required=True, default=fields.Date.context_today)
    effect_ids = fields.Many2many('account.effect', string='Agrupar Efectos', readonly=True)
    amount = fields.Monetary(string='Total', required=True, currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', required=True, readonly=True)
    group_ids = fields.Many2many('account.effect.group', 'account_effect_container_history_group_rel', 'history_id', 'group_id', string='Agrupaciones')
    allocation_line_ids = fields.One2many('account.effect.container.payment.line', 'history_id', string='Distribución del pago')
    portfolio_effect_ids = fields.Many2many(
        'account.effect', 'account_effect_history_portfolio_effect_rel',
        'history_id', 'effect_id', string='Efectos de cuota / saldo', readonly=True,
    )
    source_history_id = fields.Many2one(
        'account.effect.container.payment.history', string='Operación original',
        readonly=True, copy=False, ondelete='restrict', index=True,
    )
    type = fields.Selection([
        ('paid', 'Saldados'),
        ('returned', 'Devoluciones'),
        ('cancelled', 'Anulaciones'),
    ], string='Tipo', required=True, readonly=True)

    def action_anular_saldado(self):
        self.ensure_one()
        if self.type != 'paid' or not self.move_id or self.move_id.state != 'posted':
            raise UserError(_('Solo se puede anular un saldado publicado.'))

        if self.remittance_id:
            latest = self.remittance_id.payment_history_ids.filtered(
                lambda item: item.type == 'paid' and item.move_id and item.move_id.state == 'posted'
            ).sorted(key=lambda item: (item.date or fields.Date.to_date('1900-01-01'), item.id))[-1:]
            if not latest or latest[0] != self:
                raise UserError(_('Solo se puede anular el último saldado de la remesa.'))
            return self.remittance_id.action_anular_saldado()

        groups = self.group_ids | self.group_id | self.effect_ids.mapped('group_id')
        if len(groups) != 1:
            raise UserError(_('Esta operación afecta a varias agrupaciones. Debe anularse desde la remesa que la originó.'))
        group = groups[:1]
        histories = self.env['account.effect.container.payment.history'].search([
            '|', ('group_id', '=', group.id), ('group_ids', 'in', group.id),
            ('type', '=', 'paid'), ('move_id.state', '=', 'posted'),
        ], order='date desc, id desc')
        if not histories or histories[0] != self:
            raise UserError(_('Solo se puede anular el último saldado de la agrupación.'))
        return group.action_anular_saldado()


class AccountEffectContainerPaymentLine(models.Model):
    _name = 'account.effect.container.payment.line'
    _description = 'Distribución de pagos de cartera'
    _order = 'id'

    history_id = fields.Many2one(
        'account.effect.container.payment.history',
        string='Operación de pago', required=True, ondelete='cascade', index=True,
    )
    effect_id = fields.Many2one(
        'account.effect', string='Efecto', required=True, ondelete='restrict', index=True,
    )
    amount = fields.Monetary(string='Importe aplicado', required=True, currency_field='currency_id')
    currency_id = fields.Many2one('res.currency', related='effect_id.currency_id', store=True, readonly=True)
