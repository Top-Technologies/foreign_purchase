from collections import defaultdict

from odoo import _, models
from odoo.exceptions import UserError
from odoo.tools.float_utils import float_compare


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    def _action_done(self):
        self._check_import_goods_not_issued_early()
        result = super()._action_done()
        orders = self.move_ids.purchase_line_id.order_id.filtered(
            lambda order: order.purchase_type == 'import'
        )
        orders._update_landed_cost_status()
        return result

    def action_cancel(self):
        result = super().action_cancel()
        orders = self.move_ids.purchase_line_id.order_id.filtered(
            lambda order: order.purchase_type == 'import'
        )
        orders._update_landed_cost_status()
        return result

    def _check_import_goods_not_issued_early(self):
        if self.env.context.get('skip_import_landed_cost_check'):
            return
        for picking in self:
            if picking.location_id.usage != 'internal':
                continue
            if picking.location_dest_id.usage not in ('internal', 'customer', 'transit'):
                continue
            moves = picking.move_ids.filtered(
                lambda move: move.state not in ('cancel', 'done')
                and move.product_id.is_storable
                and not move.product_uom.is_zero(move.quantity)
            )
            if not moves:
                continue
            on_hold = self.env['stock.move']._foreign_purchase_qty_on_hold(
                moves.product_id, picking.company_id,
            )
            if not on_hold:
                continue
            demanded = defaultdict(float)
            for move in moves:
                demanded[move.product_id] += move._foreign_purchase_product_qty()
            blocked = []
            for product, qty in demanded.items():
                held = on_hold.get(product, 0.0)
                if not held:
                    continue
                available = product.with_company(picking.company_id).qty_available - held
                rounding = product.uom_id.rounding or 0.01
                if float_compare(qty, max(available, 0.0), precision_rounding=rounding) > 0:
                    blocked.append(product.display_name)
            if blocked:
                raise UserError(_(
                    'Leave %(products)s in the warehouse. Validate the landed cost on the import receipt before issuing the goods.',
                    products=', '.join(blocked),
                ))
