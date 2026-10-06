from odoo import fields, models


class ResCompany(models.Model):
    _inherit = 'res.company'

    sepa_creditor_identifier = fields.Char(string='Identificador acreedor SEPA')
