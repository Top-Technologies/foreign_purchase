from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ForeignPurchaseClaim(models.Model):
    _name = 'foreign.purchase.claim'
    _description = 'Import Third-party Claim'
    _order = 'id desc'

    order_id = fields.Many2one(
        'purchase.order',
        string='Import Order',
        required=True,
        ondelete='cascade',
        index=True,
    )
    company_id = fields.Many2one(related='order_id.company_id', store=True)
    currency_id = fields.Many2one(related='order_id.company_currency_id')
    claim_against = fields.Selection(
        selection=[
            ('forwarder', 'Shipping company'),
            ('insurer', 'Insurer'),
            ('customs', 'Customs broker'),
            ('supplier', 'Supplier'),
            ('other', 'Other'),
        ],
        string='Claim against',
        required=True,
        default='forwarder',
    )
    partner_id = fields.Many2one('res.partner', string='Contact')
    description = fields.Char(string='Reason', required=True)
    amount = fields.Monetary(currency_field='currency_id', string='Amount in company currency')
    state = fields.Selection(
        selection=[
            ('open', 'Open'),
            ('settled', 'Settled'),
        ],
        default='open',
        required=True,
    )

    @api.model_create_multi
    def create(self, vals_list):
        claims = super().create(vals_list)
        for claim in claims:
            amount = f'{claim.amount:,.2f} {claim.currency_id.name or ""}'.strip()
            claim.order_id._schedule_import_reminder(
                _('Pay claim: %s', claim.description),
                _('%(who)s is owed %(amount)s on %(order)s. %(reason)s',
                  who=dict(claim._fields['claim_against'].selection).get(claim.claim_against),
                  amount=amount,
                  order=claim.order_id.name,
                  reason=claim.description),
                fields.Date.context_today(claim),
            )
        return claims


class ForeignPurchaseDiscrepancy(models.Model):
    _name = 'foreign.purchase.discrepancy'
    _description = 'Goods Discrepancy Report'
    _order = 'id desc'

    order_id = fields.Many2one(
        'purchase.order',
        string='Import Order',
        required=True,
        ondelete='cascade',
        index=True,
    )
    company_id = fields.Many2one(related='order_id.company_id', store=True)
    product_id = fields.Many2one('product.product', string='Product', required=True)
    qty_received = fields.Float(string='Received')
    qty_passed = fields.Float(string='Passed')
    qty_damaged = fields.Float(string='Damaged')
    weight_difference = fields.Float(string='Weight difference')
    note = fields.Text(string='Note')
    photo = fields.Binary(string='Photo', attachment=True)
    photo_name = fields.Char()
    quarantine_picking_id = fields.Many2one('stock.picking', string='Quarantine transfer', copy=False)

    def action_send_to_quarantine(self):
        for report in self:
            if report.qty_damaged <= 0:
                raise UserError(_('Enter the damaged quantity before sending goods to quarantine.'))
            if report.quarantine_picking_id:
                continue
            warehouse = report.order_id.picking_type_id.warehouse_id
            if not warehouse or not warehouse.lot_stock_id or not warehouse.int_type_id:
                raise UserError(_('The receipt warehouse has no internal transfer, so the damaged goods cannot be moved.'))
            quarantine = report._quarantine_location(warehouse)
            picking = self.env['stock.picking'].create({
                'picking_type_id': warehouse.int_type_id.id,
                'location_id': warehouse.lot_stock_id.id,
                'location_dest_id': quarantine.id,
                'origin': _('%s discrepancy', report.order_id.name),
                'move_ids': [fields.Command.create({
                    'product_id': report.product_id.id,
                    'product_uom_qty': report.qty_damaged,
                    'product_uom': report.product_id.uom_id.id,
                    'location_id': warehouse.lot_stock_id.id,
                    'location_dest_id': quarantine.id,
                    'company_id': warehouse.company_id.id,
                })],
            })
            picking.action_confirm()
            report.quarantine_picking_id = picking
            report.order_id.message_post(body=_(
                'Damaged %(qty)s %(product)s moved toward quarantine on %(transfer)s.',
                qty=report.qty_damaged,
                product=report.product_id.display_name,
                transfer=picking.display_name,
            ))
        return True

    def _quarantine_location(self, warehouse):
        location = self.env['stock.location'].search([
            ('usage', '=', 'internal'),
            ('name', '=', 'Quarantine'),
            ('location_id', '=', warehouse.lot_stock_id.id),
            ('company_id', 'in', (False, warehouse.company_id.id)),
        ], limit=1)
        if location:
            return location
        return self.env['stock.location'].create({
            'name': 'Quarantine',
            'usage': 'internal',
            'location_id': warehouse.lot_stock_id.id,
            'company_id': warehouse.company_id.id,
        })
