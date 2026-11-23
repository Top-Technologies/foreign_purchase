from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class ResCompany(models.Model):
    _inherit = 'res.company'

    foreign_dm_limit = fields.Monetary(
        string='Department Manager limit',
        default=100000.0,
        currency_field='currency_id',
        help='Import orders up to this amount in company currency need the Department Manager.',
    )
    foreign_dgm_limit = fields.Monetary(
        string='Deputy General Manager limit',
        default=1000000.0,
        currency_field='currency_id',
        help='Import orders above the Department Manager limit, up to this amount, also need the Deputy General Manager. Orders above this amount also need the General Manager.',
    )
    foreign_reminder_days = fields.Integer(
        string='Days before LC expiry',
        default=15,
        help='How many days before the letter of credit expiry a reminder is created.',
    )
    foreign_shipment_reminder_days = fields.Integer(
        string='Days before latest shipment',
        default=10,
        help='How many days before the latest shipment date a reminder is created, if the goods have not shipped.',
    )
    foreign_lc_deposit_account_id = fields.Many2one(
        'account.account',
        string='LC deposit account',
        check_company=True,
        domain="[('account_type', '=', 'asset_current')]",
        help='Holds the birr margin the bank keeps when a letter of credit is opened.',
    )

    @api.constrains('foreign_dm_limit', 'foreign_dgm_limit', 'foreign_reminder_days', 'foreign_shipment_reminder_days')
    def _check_foreign_approval_limits(self):
        for company in self:
            if company.foreign_dgm_limit < company.foreign_dm_limit:
                raise ValidationError(_(
                    'The Deputy General Manager amount must be at least the Department Manager amount.'
                ))
            if company.foreign_reminder_days < 0 or company.foreign_shipment_reminder_days < 0:
                raise ValidationError(_('Import reminder days cannot be negative.'))
