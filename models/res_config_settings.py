from odoo import fields, models


class ResConfigSettings(models.TransientModel):
    _inherit = 'res.config.settings'

    foreign_dm_limit = fields.Monetary(
        related='company_id.foreign_dm_limit',
        readonly=False,
        currency_field='company_currency_id',
    )
    foreign_dgm_limit = fields.Monetary(
        related='company_id.foreign_dgm_limit',
        readonly=False,
        currency_field='company_currency_id',
    )
    foreign_reminder_days = fields.Integer(
        related='company_id.foreign_reminder_days',
        readonly=False,
    )
    foreign_shipment_reminder_days = fields.Integer(
        related='company_id.foreign_shipment_reminder_days',
        readonly=False,
    )
    foreign_lc_deposit_account_id = fields.Many2one(
        related='company_id.foreign_lc_deposit_account_id',
        readonly=False,
    )
