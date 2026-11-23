from odoo import api, fields, models


class StockLandedCost(models.Model):
    _inherit = 'stock.landed.cost'

    import_order_id = fields.Many2one(
        'purchase.order',
        string='Import order',
        compute='_compute_import_order',
        store=True,
    )
    import_vendor_id = fields.Many2one(
        'res.partner',
        string='Supplier',
        related='import_order_id.partner_id',
    )
    is_import = fields.Boolean(
        string='Import landed cost',
        compute='_compute_import_order',
        store=True,
    )

    @api.depends('picking_ids.move_ids.purchase_line_id.order_id.purchase_type')
    def _compute_import_order(self):
        for cost in self:
            orders = cost.picking_ids.move_ids.purchase_line_id.order_id.filtered(
                lambda order: order.purchase_type == 'import'
            )
            cost.import_order_id = orders[:1]
            cost.is_import = bool(orders)

    def button_validate(self):
        result = super().button_validate()
        orders = self.picking_ids.move_ids.purchase_line_id.order_id.filtered(
            lambda order: order.purchase_type == 'import'
        )
        orders._update_landed_cost_status()
        return result
