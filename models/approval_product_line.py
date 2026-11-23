from odoo import _, fields, models
from odoo.exceptions import UserError
from odoo.fields import Domain


class ApprovalProductLine(models.Model):
    _inherit = 'approval.product.line'

    import_vendor_id = fields.Many2one(
        'res.partner',
        string='Vendor',
        check_company=True,
    )
    import_price_unit = fields.Float(
        string='Unit Price',
        digits='Product Price',
        help='Price in the supplier currency. Import orders use USD.',
    )

    def _check_products_vendor(self):
        import_lines = self.filtered(
            lambda line: line.approval_request_id.category_id.is_import_purchase
        )
        others = self - import_lines
        if others:
            super(ApprovalProductLine, others)._check_products_vendor()
        missing = import_lines.filtered(lambda line: not line.import_vendor_id)
        if missing:
            names = ', '.join(missing.mapped('product_id.display_name'))
            raise UserError(_('Enter the vendor and the unit price for %s.', names))

    def _get_purchase_orders_domain(self, vendor):
        if self.approval_request_id.category_id.is_import_purchase:
            usd = self.env.ref('base.USD', raise_if_not_found=False)
            currency = usd if usd and usd.active else self.company_id.currency_id
            return Domain([
                ('company_id', '=', self.company_id.id),
                ('partner_id', '=', vendor.id),
                ('state', '=', 'draft'),
                ('purchase_type', '=', 'import'),
                ('currency_id', '=', currency.id),
            ])
        domain = super()._get_purchase_orders_domain(vendor)
        return domain & Domain([('purchase_type', '=', 'local')])

    def _import_purchase_order_values(self, vendor):
        self.ensure_one()
        fob = self.env.ref('account.incoterm_FOB', raise_if_not_found=False)
        usd = self.env.ref('base.USD', raise_if_not_found=False)
        currency = usd if usd and usd.active else self.company_id.currency_id
        picking_type = self.env['purchase.order']._get_picking_type(self.company_id.id)
        vals = {
            'origin': self.approval_request_id.name,
            'partner_id': vendor.id,
            'company_id': self.company_id.id,
            'currency_id': currency.id,
            'purchase_type': 'import',
            'payment_term_id': vendor.property_supplier_payment_term_id.id,
            'fiscal_position_id': self.env['account.fiscal.position']._get_fiscal_position(vendor).id,
        }
        if fob:
            vals['incoterm_id'] = fob.id
        if picking_type:
            vals['picking_type_id'] = picking_type.id
        return vals

    def _get_purchase_order_values(self, vendor):
        if self.approval_request_id.category_id.is_import_purchase:
            return self._import_purchase_order_values(vendor)
        return super()._get_purchase_order_values(vendor)
