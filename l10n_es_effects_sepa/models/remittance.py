from odoo import fields, models, _
from odoo.exceptions import UserError
from xml.etree.ElementTree import Element, SubElement, tostring
from xml.dom import minidom


class AccountEffectRemittance(models.Model):
    _inherit = 'account.effect.remittance'

    sepa_creditor_identifier = fields.Char(related='company_id.sepa_creditor_identifier', readonly=False, string='Identificador acreedor SEPA')
    sepa_message_id = fields.Char(string='ID mensaje SEPA', copy=False)
    sepa_file = fields.Binary(string='Fichero SEPA', readonly=True, attachment=True)
    sepa_filename = fields.Char(string='Nombre fichero', readonly=True)
    sepa_generated = fields.Boolean(string='SEPA generado', readonly=True)

    def action_generate_sepa(self):
        for rem in self:
            effects = rem.effect_ids.filtered(lambda e: e.payment_state not in ('paid', 'cancelled'))
            if not effects:
                raise UserError(_('La remesa no contiene efectos pendientes.'))
            if not rem.sepa_creditor_identifier:
                raise UserError(_('Configura el Identificador acreedor SEPA de la empresa.'))
            missing = effects.filtered(lambda e: not e.bank_account_id or not e.bank_account_id.acc_number)
            if missing:
                raise UserError(_('Hay efectos sin cuenta bancaria del cliente/proveedor.'))
            msg_id = rem.sepa_message_id or 'REM-%s' % rem.name
            root = Element('Document', {'xmlns': 'urn:iso:std:iso:20022:tech:xsd:pain.008.001.08'})
            cstmr = SubElement(root, 'CstmrDrctDbtInitn')
            hdr = SubElement(cstmr, 'GrpHdr')
            SubElement(hdr, 'MsgId').text = msg_id
            SubElement(hdr, 'CreDtTm').text = fields.Datetime.now().isoformat()
            SubElement(hdr, 'NbOfTxs').text = str(len(effects))
            SubElement(hdr, 'CtrlSum').text = '%.2f' % sum(effects.mapped('amount'))
            org = SubElement(hdr, 'InitgPty')
            SubElement(org, 'Nm').text = rem.company_id.name
            pmt = SubElement(cstmr, 'PmtInf')
            SubElement(pmt, 'PmtInfId').text = rem.name
            SubElement(pmt, 'PmtMtd').text = 'DD'
            SubElement(pmt, 'NbOfTxs').text = str(len(effects))
            SubElement(pmt, 'CtrlSum').text = '%.2f' % sum(effects.mapped('amount'))
            tp = SubElement(pmt, 'PmtTpInf')
            svc = SubElement(tp, 'SvcLvl')
            SubElement(svc, 'Cd').text = 'SEPA'
            cdtr = SubElement(pmt, 'Cdtr')
            SubElement(cdtr, 'Nm').text = rem.company_id.name
            for eff in effects:
                tx = SubElement(pmt, 'DrctDbtTxInf')
                amt = SubElement(tx, 'InstdAmt', {'Ccy': rem.currency_id.name})
                amt.text = '%.2f' % eff.amount
                mnd = SubElement(tx, 'DrctDbtTx')
                mnd_id = SubElement(mnd, 'MndtRltdInf')
                SubElement(mnd_id, 'MndtId').text = eff.reference or eff.effect_number
                dbtr = SubElement(tx, 'Dbtr')
                SubElement(dbtr, 'Nm').text = eff.partner_id.name
                dbtr_acct = SubElement(tx, 'DbtrAcct')
                dbtr_id = SubElement(dbtr_acct, 'Id')
                SubElement(dbtr_id, 'IBAN').text = eff.bank_account_id.acc_number.replace(' ', '')
                rmt = SubElement(tx, 'RmtInf')
                SubElement(rmt, 'Ustrd').text = eff.reference or eff.effect_number
            xml = minidom.parseString(tostring(root, encoding='utf-8')).toprettyxml(indent='  ', encoding='utf-8')
            rem.write({'sepa_message_id': msg_id, 'sepa_file': xml, 'sepa_filename': '%s.xml' % rem.name, 'sepa_generated': True, 'state': 'generated'})
        return True
