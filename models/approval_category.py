from odoo import fields, models


class ApprovalCategory(models.Model):
    _inherit = 'approval.category'

    is_import_purchase = fields.Boolean(
        string='Import Purchase',
        help='Requests of this category create a foreign purchase order in USD with Incoterm FOB.',
    )
