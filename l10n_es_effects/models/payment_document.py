from odoo import fields, models


class AccountEffectPaymentDocument(models.Model):
    _name = 'account.effect.payment.document'
    _description = 'Documento de pago de cartera'
    _order = 'code, id'

    code = fields.Char(string='Código', required=True, index=True)
    name = fields.Char(string='Nombre', required=True, translate=True)
    requires_delivery = fields.Boolean(string='Hay que recibirlo/enviarlo', default=False)
    remesable = fields.Boolean(string='Remesable', default=False)
    active = fields.Boolean(default=True)

    _sql_constraints = [
        ('code_unique', 'unique(code)', 'El código del documento de pago debe ser único.'),
    ]
