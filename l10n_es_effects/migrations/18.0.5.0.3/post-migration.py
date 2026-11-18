# -*- coding: utf-8 -*-
"""Backfill the returned-effect origin only from explicit return histories."""
from odoo import SUPERUSER_ID, api

def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    histories = env['account.effect.container.payment.history'].sudo().search([
        ('type', '=', 'returned'),
        ('portfolio_effect_ids', '!=', False),
    ])
    for history in histories:
        for returned_effect in history.portfolio_effect_ids.filtered(lambda item: not item.returned_from_effect_id):
            original = returned_effect.portfolio_chain_id
            if original and original.exists():
                returned_effect.returned_from_effect_id = original.id
