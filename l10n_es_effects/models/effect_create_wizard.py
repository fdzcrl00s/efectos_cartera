from odoo import api, fields, models, _
from odoo.exceptions import UserError


class AccountEffectCreateWizard(models.TransientModel):
    _name = 'account.effect.create.wizard'
    _description = 'Crear elemento de cartera'

    effect_type = fields.Selection([
        ('effect', 'Efecto'),
        ('group', 'Agrupación'),
        ('remittance', 'Remesa'),
    ], string='Tipo de efecto', required=True, default='effect')
    company_type = fields.Selection([
        ('customer', 'Cliente'),
        ('supplier', 'Proveedor'),
    ], string='Tipo de empresa', required=True, default=lambda self: self.env.context.get('default_company_type', 'customer'))
    partner_id = fields.Many2one('res.partner', string='Cliente / Proveedor')
    company_id = fields.Many2one('res.company', string='Compañía', required=True, default=lambda self: self.env.company)
    currency_id = fields.Many2one('res.currency', string='Moneda', required=True, default=lambda self: self.env.company.currency_id)
    move_id = fields.Many2one('account.move', string='Factura', domain="[('company_id', '=', company_id), ('state', '=', 'posted'), ('move_type', 'in', ('out_invoice', 'in_invoice'))]")
    due_date = fields.Date(string='Fecha de vencimiento', default=fields.Date.context_today)
    amount = fields.Monetary(string='Total', currency_field='currency_id')
    bank_journal_id = fields.Many2one('account.journal', string='Banco', domain="[('type', '=', 'bank'), ('company_id', '=', company_id)]")
    partner_bank_id = fields.Many2one('res.partner.bank', string='Cuenta bancaria')
    payment_direction = fields.Selection([
        ('receive', 'Recibir dinero'),
        ('send', 'Enviar dinero'),
    ], string='Tipo de pago', compute='_compute_payment_direction', store=False)
    reference = fields.Char(string='Circular / Concepto')
    notes = fields.Text(string='Notas')

    @api.depends('company_type')
    def _compute_payment_direction(self):
        for wizard in self:
            wizard.payment_direction = 'receive' if wizard.company_type == 'customer' else 'send'

    @api.onchange('company_type')
    def _onchange_company_type(self):
        self.partner_id = False
        self.move_id = False
        self.partner_bank_id = False
        self.amount = 0.0
        self.currency_id = self.env.company.currency_id

    @api.onchange('partner_id')
    def _onchange_partner_id(self):
        if self.partner_id and self.partner_bank_id and self.partner_bank_id.partner_id != self.partner_id:
            self.partner_bank_id = False

    @api.onchange('move_id')
    def _onchange_move_id(self):
        if not self.move_id:
            return
        self.partner_id = self.move_id.partner_id
        self.company_type = 'customer' if self.move_id.move_type == 'out_invoice' else 'supplier'
        self.currency_id = self.move_id.currency_id
        payment_terms = self.move_id.line_ids.filtered(lambda line: line.display_type == 'payment_term')
        if payment_terms:
            line = payment_terms.sorted(lambda l: l.date_maturity or self.move_id.invoice_date_due or self.move_id.invoice_date)[0]
            self.due_date = line.date_maturity or self.move_id.invoice_date_due or self.move_id.invoice_date
            self.amount = abs(line.amount_residual_currency if line.currency_id and line.currency_id != self.company_id.currency_id else line.amount_residual)

    def _effect_vals(self):
        if not self.partner_id:
            raise UserError(_('Indica el cliente o proveedor.'))
        if not self.due_date:
            raise UserError(_('Indica la fecha de vencimiento.'))
        if self.amount <= 0:
            raise UserError(_('El total debe ser superior a cero.'))
        vals = {
            'company_id': self.company_id.id,
            'company_type': self.company_type,
            'partner_id': self.partner_id.id,
            'move_id': self.move_id.id if self.move_id else False,
            'invoice_reference': self.move_id.name if self.move_id else False,
            'reference': self.reference or False,
            'due_date': self.due_date,
            'amount': self.amount,
            'currency_id': self.currency_id.id,
            'bank_journal_id': self.bank_journal_id.id if self.bank_journal_id else False,
            'partner_bank_id': self.partner_bank_id.id if self.partner_bank_id else False,
            'payment_direction': self.payment_direction,
            'effect_type': 'effect',
        }
        return vals

    def _container_vals(self):
        return {
            'company_id': self.company_id.id,
            'company_type': self.company_type,
            'currency_id': self.currency_id.id,
            'date': fields.Date.context_today(self),
            'due_date': self.due_date,
            'reference': self.reference or False,
            'notes': self.notes or False,
            'bank_journal_id': self.bank_journal_id.id if self.bank_journal_id else False,
            'partner_bank_id': self.partner_bank_id.id if self.partner_bank_id else False,
            'payment_direction': self.payment_direction,
        }

    def action_create(self):
        self.ensure_one()
        if self.effect_type == 'effect':
            effect = self.env['account.effect'].create(self._effect_vals())
            return {
                'type': 'ir.actions.act_window',
                'name': _('Efecto %s') % effect.name,
                'res_model': 'account.effect',
                'view_mode': 'form',
                'res_id': effect.id,
                'target': 'current',
            }
        if self.effect_type == 'group':
            group = self.env['account.effect.group'].create(self._container_vals())
            return {
                'type': 'ir.actions.act_window',
                'name': _('Agrupación %s') % group.cartera_number,
                'res_model': 'account.effect.group',
                'view_mode': 'form',
                'res_id': group.id,
                'target': 'current',
            }
        remittance_vals = self._container_vals()
        remittance_vals['company_type'] = False
        remittance = self.env['account.effect.remittance'].create(remittance_vals)
        return {
            'type': 'ir.actions.act_window',
            'name': _('Remesa %s') % remittance.cartera_number,
            'res_model': 'account.effect.remittance',
            'view_mode': 'form',
            'res_id': remittance.id,
            'target': 'current',
        }
