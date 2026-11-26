from odoo import _, fields, models
from odoo.exceptions import UserError


class ApprovalRequest(models.Model):
    _inherit = 'approval.request'

    is_import_purchase = fields.Boolean(related='category_id.is_import_purchase')

    foreign_requisition_id = fields.Many2one(
        'foreign.purchase.requisition',
        string='Warehouse requisition',
        copy=False,
        index=True,
    )

    def _create_purchase_orders(self):
        import_requests = self.filtered('category_id.is_import_purchase')
        super(ApprovalRequest, self - import_requests)._create_purchase_orders()
        import_requests._create_import_purchase_orders()
        for request in self.filtered('foreign_requisition_id'):
            orders = request.product_line_ids.purchase_order_line_id.order_id
            if not orders:
                continue
            orders.write({'foreign_requisition_id': request.foreign_requisition_id.id})
            request.foreign_requisition_id.write({
                'purchase_order_ids': [fields.Command.link(order.id) for order in orders],
                'state': 'ordered',
            })

    def _create_import_purchase_orders(self):
        """Open the import order from the vendor and unit price typed on the request."""
        for request in self:
            if request.purchase_order_count:
                continue
            for line in request.product_line_ids:
                if not line.product_id:
                    raise UserError(_('Choose a product on every line.'))
                vendor = line.import_vendor_id
                if not vendor:
                    raise UserError(_('Enter the vendor for %s.', line.product_id.display_name))
                orders = self.env['purchase.order'].search(line._get_purchase_orders_domain(vendor))
                if orders:
                    purchase_order = orders[0]
                else:
                    purchase_order = self.env['purchase.order'].with_company(line.company_id).create(
                        line._import_purchase_order_values(vendor)
                    )
                uom = line.product_uom_id or line.product_id.uom_id
                po_line = self.env['purchase.order.line'].create({
                    'order_id': purchase_order.id,
                    'product_id': line.product_id.id,
                    'name': line.description or line.product_id.display_name,
                    'product_qty': line.quantity,
                    'product_uom_id': uom.id,
                    'price_unit': line.import_price_unit,
                    'date_planned': fields.Datetime.now(),
                })
                po_line.write({
                    'price_unit': line.import_price_unit,
                    'technical_price_unit': 0.0,
                })
                line.purchase_order_line_id = po_line.id
