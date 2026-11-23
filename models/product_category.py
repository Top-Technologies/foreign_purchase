from odoo import Command, api, models


class ProductCategory(models.Model):
    _inherit = 'product.category'

    @api.model
    def _foreign_purchase_configure_imported_goods(self):
        """Set perpetual average costing on Imported Goods when the company accounts exist."""
        category = self.env.ref(
            'foreign_purchase.product_category_imported_goods',
            raise_if_not_found=False,
        )
        if not category:
            return
        templates = self.env['product.template']
        for xmlid in (
            'foreign_purchase.product_freight',
            'foreign_purchase.product_insurance',
            'foreign_purchase.product_duty',
            'foreign_purchase.product_clearing',
            'foreign_purchase.product_port_storage',
        ):
            template = self.env.ref(xmlid, raise_if_not_found=False)
            if template:
                templates |= template
        for company in self.env['res.company'].search([]):
            category_company = category.with_company(company)
            already_set = (
                category_company.property_valuation == 'real_time'
                and category_company.property_cost_method == 'average'
                and category_company.property_stock_valuation_account_id
            )
            if not already_set:
                vals = {
                    'property_valuation': 'real_time',
                    'property_cost_method': 'average',
                }
                if company.account_stock_valuation_id:
                    vals['property_stock_valuation_account_id'] = company.account_stock_valuation_id.id
                if company.account_stock_journal_id:
                    vals['property_stock_journal'] = company.account_stock_journal_id.id
                category_company.write(vals)
            expense = self.env['account.account'].with_company(company).search([
                ('account_type', '=', 'expense'),
                ('company_ids', 'in', company.id),
            ], limit=1)
            if expense:
                missing = templates.with_company(company).filtered(
                    lambda product: not product.property_account_expense_id
                )
                if missing:
                    missing.write({'property_account_expense_id': expense.id})
            if company.foreign_dgm_limit == 500000.0:
                company.foreign_dgm_limit = 1000000.0
            if not company.foreign_lc_deposit_account_id:
                account = self.env['account.account'].with_company(company).search([
                    ('name', '=', 'LC deposit with the bank'),
                    ('company_ids', 'in', company.id),
                ], limit=1)
                if not account:
                    account = self.env['account.account'].with_company(company).create({
                        'name': 'LC deposit with the bank',
                        'code': '199001',
                        'account_type': 'asset_current',
                        'company_ids': [Command.link(company.id)],
                    })
                company.foreign_lc_deposit_account_id = account.id
