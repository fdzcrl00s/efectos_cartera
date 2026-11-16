from odoo import SUPERUSER_ID, api


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    groups = env['account.effect.group'].search(
        [('cartera_number', 'in', [False, '/'])], order='create_date, id'
    )
    remittances = env['account.effect.remittance'].search(
        [('cartera_number', 'in', [False, '/'])], order='create_date, id'
    )
    pending = [(record.create_date, 0, record.id, record) for record in groups]
    pending += [(record.create_date, 1, record.id, record) for record in remittances]
    for _created, _model_order, _record_id, record in sorted(
        pending, key=lambda item: (item[0] or False, item[1], item[2])
    ):
        record._assign_cartera_number()
        record._sync_container_effect()
