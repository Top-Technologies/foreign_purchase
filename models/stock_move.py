from collections import defaultdict

from odoo import api, models
from odoo.tools.float_utils import float_compare


class StockMove(models.Model):
    _inherit = 'stock.move'

    @api.model
    def _foreign_purchase_qty_on_hold(self, products, company):
        """Quantity received on import receipts that still have no validated landed cost."""
        products = products.filtered(lambda product: product.is_storable)
        if not products or not company:
            return {}
        moves = self.search([
            ('state', '=', 'done'),
            ('product_id', 'in', products.ids),
            ('company_id', '=', company.id),
            ('purchase_line_id.order_id.purchase_type', '=', 'import'),
        ])
        if not moves:
            return {}
        incoming = moves.filtered(
            lambda move: move.location_id.usage == 'supplier' and move.location_dest_id.usage == 'internal'
        )
        if not incoming:
            return {}
        covered = self.env['stock.landed.cost'].search([
            ('state', '=', 'done'),
            ('company_id', '=', company.id),
            ('picking_ids', 'in', incoming.picking_id.ids),
        ]).picking_ids
        qty_by_product = defaultdict(float)
        for line in incoming.purchase_line_id:
            line_moves = moves.filtered(lambda move: move.purchase_line_id == line)
            uncovered = line_moves.filtered(
                lambda move: move.location_id.usage == 'supplier'
                and move.location_dest_id.usage == 'internal'
                and move.picking_id not in covered
            )
            if not uncovered:
                continue
            returned = line_moves.filtered(
                lambda move: move.location_id.usage == 'internal' and move.location_dest_id.usage == 'supplier'
            )
            product = line.product_id
            qty = sum(move._foreign_purchase_product_qty() for move in uncovered)
            qty -= sum(move._foreign_purchase_product_qty() for move in returned)
            rounding = product.uom_id.rounding or 0.01
            if float_compare(qty, 0.0, precision_rounding=rounding) > 0:
                qty_by_product[product] += qty
        return qty_by_product

    def _foreign_purchase_product_qty(self):
        self.ensure_one()
        if not self.product_uom or not self.product_id.uom_id:
            return self.quantity
        return self.product_uom._compute_quantity(self.quantity, self.product_id.uom_id)
