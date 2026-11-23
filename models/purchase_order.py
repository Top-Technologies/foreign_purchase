from datetime import timedelta

from odoo import _, api, Command, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools.float_utils import float_compare


class PurchaseOrder(models.Model):
    _inherit = 'purchase.order'

    purchase_type = fields.Selection(
        selection=[
            ('local', 'Local'),
            ('import', 'Import'),
        ],
        string='Purchase Type',
        default='local',
        required=True,
        tracking=True,
        index=True,
    )
    import_payment_method = fields.Selection(
        selection=[
            ('lc', 'Letter of credit'),
            ('tt', 'Bank wire'),
            ('cad', 'Cash against documents'),
        ],
        string='Payment Method',
        tracking=True,
    )
    import_officer_id = fields.Many2one(
        'res.users',
        string='Import Officer',
        tracking=True,
        domain=[('share', '=', False)],
    )
    import_approval_state = fields.Selection(
        selection=[
            ('draft', 'Not submitted'),
            ('dm', 'Waiting for Department Manager'),
            ('dgm', 'Waiting for Deputy General Manager'),
            ('gm', 'Waiting for General Manager'),
            ('approved', 'Approved'),
        ],
        string='Import Approval',
        default='draft',
        tracking=True,
        copy=False,
    )
    can_approve_import = fields.Boolean(compute='_compute_import_buttons')
    can_create_landed_cost = fields.Boolean(compute='_compute_import_buttons')
    lc_number = fields.Char(string='LC Number', tracking=True, copy=False)
    lc_opening_date = fields.Date(string='Opening Date', tracking=True)
    lc_latest_shipment_date = fields.Date(string='Latest Shipment Date', tracking=True)
    lc_expiry_date = fields.Date(string='Expiry Date', tracking=True)
    lc_deposit_percent = fields.Float(string='Deposit %', default=50.0)
    lc_deposit_amount = fields.Monetary(
        string='Deposit',
        currency_field='currency_id',
        compute='_compute_lc_deposit_amount',
        inverse='_inverse_lc_deposit_amount',
        store=True,
        readonly=False,
    )
    lc_deposit_payment_id = fields.Many2one(
        'account.payment',
        string='Deposit Payment',
        copy=False,
        check_company=True,
    )
    lc_deposit_move_id = fields.Many2one(
        'account.move',
        string='Bank deposit entry',
        copy=False,
        check_company=True,
    )
    lc_deposit_open = fields.Monetary(
        string='Deposit still with the bank',
        currency_field='company_currency_id',
        copy=False,
    )
    lc_settlement_rate = fields.Float(
        string='Settlement rate',
        digits=(12, 6),
        help='Company currency for 1 unit of the order currency on the day the bank pays. The floodlight example uses 152.',
    )
    lc_settlement_move_id = fields.Many2one(
        'account.move',
        string='Settlement entry',
        copy=False,
        check_company=True,
    )
    lc_exchange_difference = fields.Monetary(
        string='Exchange difference',
        currency_field='company_currency_id',
        copy=False,
        help='Posted when the foreign bill is settled by LC, bank wire, or cash against documents. A positive amount is a loss. It is not added to the product cost.',
    )
    lc_cancelled_amount = fields.Monetary(
        string='Cancelled LC balance',
        currency_field='currency_id',
        copy=False,
        help='Foreign amount the bank will not pay, for example because fewer goods were shipped.',
    )
    lc_cancel_move_id = fields.Many2one(
        'account.move',
        string='LC balance cancellation',
        copy=False,
        check_company=True,
    )
    import_company_rate = fields.Float(
        string='Rate',
        compute='_compute_import_amounts',
        digits=(12, 6),
    )
    import_approval_text = fields.Char(string='Approval amount', compute='_compute_import_amounts')
    deposit_company_amount = fields.Monetary(
        string='Deposit in company currency',
        currency_field='company_currency_id',
        compute='_compute_import_amounts',
    )
    balance_foreign_amount = fields.Monetary(
        string='Still to pay',
        currency_field='currency_id',
        compute='_compute_import_amounts',
    )
    expected_arrival_date = fields.Date(string='Expected arrival', tracking=True)
    shipment_reference = fields.Char(string='Shipment Reference', tracking=True)
    shipment_note = fields.Text(string='Shipment Note')
    doc_bill_of_lading = fields.Boolean(string='Bill of lading')
    doc_packing_list = fields.Boolean(string='Packing list')
    doc_commercial_invoice = fields.Boolean(string='Commercial invoice')
    doc_certificate_of_origin = fields.Boolean(string='Certificate of origin')
    doc_insurance = fields.Boolean(string='Insurance')
    doc_duty = fields.Boolean(string='Duty')
    doc_clearing = fields.Boolean(string='Clearing')
    doc_customs_declaration = fields.Boolean(string='Customs declaration')
    utilization_sent = fields.Boolean(string='Utilization letter sent', copy=False, tracking=True)
    utilization_date = fields.Date(string='Utilization Date', copy=False)
    utilization_letter = fields.Binary(string='Signed utilization letter', attachment=True, copy=False)
    utilization_letter_name = fields.Char(copy=False)
    file_closed = fields.Boolean(string='File Closed', copy=False, tracking=True)
    file_closed_date = fields.Date(string='File Closed On', copy=False)
    claim_ids = fields.One2many('foreign.purchase.claim', 'order_id', string='Third-party Claims')
    discrepancy_ids = fields.One2many(
        'foreign.purchase.discrepancy',
        'order_id',
        string='Goods discrepancy reports',
    )
    requisition_id = fields.Many2one(
        'foreign.purchase.requisition',
        string='Warehouse requisition',
        copy=False,
        index=True,
    )
    comparison_ids = fields.One2many(
        'foreign.purchase.comparison',
        'order_id',
        string='Supplier comparison',
    )
    landed_cost_ids = fields.Many2many(
        'stock.landed.cost',
        string='Landed Costs',
        compute='_compute_landed_cost_ids',
    )
    landed_cost_count = fields.Integer(compute='_compute_landed_cost_ids')
    landed_cost_status = fields.Selection(
        selection=[
            ('waiting_receipt', 'Waiting for receipt'),
            ('pending', 'Landed cost not validated'),
            ('done', 'Landed cost validated'),
        ],
        string='Landed Cost',
        copy=False,
        tracking=True,
    )

    @api.depends('import_approval_state', 'purchase_type', 'state')
    @api.depends_context('uid')
    def _compute_import_buttons(self):
        user = self.env.user
        is_manager = user.has_group('purchase.group_purchase_manager')
        can_landed = user.has_group('stock.group_stock_manager') or user.has_group(
            'foreign_purchase.group_foreign_finance'
        )
        groups = {
            'dm': user.has_group('foreign_purchase.group_foreign_dm'),
            'dgm': user.has_group('foreign_purchase.group_foreign_dgm'),
            'gm': user.has_group('foreign_purchase.group_foreign_gm'),
        }
        for order in self:
            order.can_approve_import = (
                order.purchase_type == 'import'
                and order.state in ('draft', 'sent')
                and order.import_approval_state in ('dm', 'dgm', 'gm')
                and (is_manager or groups.get(order.import_approval_state))
            )
            order.can_create_landed_cost = can_landed

    @api.depends('lc_deposit_percent', 'amount_total', 'currency_id')
    def _compute_lc_deposit_amount(self):
        for order in self:
            amount = order.amount_total * (order.lc_deposit_percent or 0.0) / 100.0
            order.lc_deposit_amount = order.currency_id.round(amount) if order.currency_id else amount

    def _inverse_lc_deposit_amount(self):
        for order in self:
            if order.currency_id and not order.currency_id.is_zero(order.amount_total):
                order.lc_deposit_percent = (order.lc_deposit_amount / order.amount_total) * 100.0

    @api.depends(
        'purchase_type',
        'lc_deposit_amount',
        'amount_total',
        'amount_total_cc',
        'currency_id',
        'company_id',
        'company_currency_id',
        'lc_opening_date',
        'date_order',
        'lc_deposit_payment_id.amount_company_currency_signed',
    )
    def _compute_import_amounts(self):
        for order in self:
            on_date = order.lc_opening_date or (order.date_order.date() if order.date_order else fields.Date.context_today(order))
            order.deposit_company_amount = order._company_amount(order.lc_deposit_amount, on_date)
            order.balance_foreign_amount = (order.amount_total or 0.0) - (order.lc_deposit_amount or 0.0)
            if order.purchase_type == 'import' and order.amount_total and order.currency_id:
                rate = order.amount_total_cc / order.amount_total
                order.import_company_rate = rate
                order.import_approval_text = _(
                    '%(foreign).2f %(cur)s at %(rate).2f = %(company).2f %(cc)s',
                    foreign=order.amount_total,
                    cur=order.currency_id.name,
                    rate=rate,
                    company=order.amount_total_cc,
                    cc=order.company_currency_id.name or '',
                )
            else:
                order.import_company_rate = 0.0
                order.import_approval_text = False

    @api.depends('picking_ids')
    def _compute_landed_cost_ids(self):
        costs = self.env['stock.landed.cost']
        if self.picking_ids:
            costs = self.env['stock.landed.cost'].search([
                ('picking_ids', 'in', self.picking_ids.ids),
            ])
        for order in self:
            order_costs = costs.filtered(lambda cost: order.picking_ids & cost.picking_ids)
            order.landed_cost_ids = order_costs
            order.landed_cost_count = len(order_costs)

    @api.onchange('purchase_type')
    def _onchange_purchase_type(self):
        if self.purchase_type != 'import':
            return
        fob = self.env.ref('account.incoterm_FOB', raise_if_not_found=False)
        if fob and not self.incoterm_id:
            self.incoterm_id = fob
        usd = self.env.ref('base.USD', raise_if_not_found=False)
        if usd and usd.active and self.currency_id == self.company_id.currency_id:
            self.currency_id = usd

    @api.constrains(
        'lc_opening_date',
        'lc_latest_shipment_date',
        'lc_expiry_date',
        'import_payment_method',
        'lc_deposit_percent',
    )
    def _check_lc_dates(self):
        for order in self:
            if order.lc_deposit_percent < 0 or order.lc_deposit_percent > 100:
                raise ValidationError(_('The deposit percent must be between 0 and 100.'))
            if order.import_payment_method != 'lc':
                continue
            if order.lc_opening_date and order.lc_expiry_date and order.lc_expiry_date < order.lc_opening_date:
                raise ValidationError(_('The LC expiry date must be on or after the opening date.'))
            if (
                order.lc_latest_shipment_date
                and order.lc_expiry_date
                and order.lc_latest_shipment_date > order.lc_expiry_date
            ):
                raise ValidationError(_('The latest shipment date must be on or before the LC expiry date.'))

    @api.model_create_multi
    def create(self, vals_list):
        orders = super().create(vals_list)
        orders.filtered(lambda order: order.purchase_type == 'import')._update_landed_cost_status()
        return orders

    def write(self, vals):
        if self.env.context.get('skip_import_approval_reset'):
            result = super().write(vals)
            if vals.get('expected_arrival_date'):
                self._apply_expected_arrival()
            return result
        if vals.get('purchase_type'):
            locked = self.filtered(
                lambda order: order.state in ('purchase', 'done') and vals['purchase_type'] != order.purchase_type
            )
            if locked:
                raise UserError(_(
                    'You cannot change the purchase type after the order is confirmed: %s.',
                    ', '.join(locked.mapped('name')),
                ))
        if vals.get('state') == 'purchase':
            pending = self.filtered(
                lambda order: order.purchase_type == 'import' and order.import_approval_state != 'approved'
            )
            if pending:
                raise UserError(_(
                    'This import order still needs approval before it can be confirmed: %s.',
                    ', '.join(pending.mapped('name')),
                ))
        result = super().write(vals)
        if any(key in vals for key in ('currency_id', 'order_line')):
            to_reset = self.filtered(
                lambda order: order.purchase_type == 'import'
                and order.state in ('draft', 'sent')
                and order.import_approval_state != 'draft'
            )
            if to_reset:
                to_reset.with_context(skip_import_approval_reset=True).write({
                    'import_approval_state': 'draft',
                })
                for order in to_reset:
                    order.message_post(body=_(
                        'Approval was cleared because the order changed. Submit it again.'
                    ))
        if 'purchase_type' in vals or 'state' in vals:
            self.filtered(lambda order: order.purchase_type == 'import')._update_landed_cost_status()
        if vals.get('expected_arrival_date'):
            self._apply_expected_arrival()
        return result

    def button_confirm(self):
        for order in self.filtered(lambda item: item.purchase_type == 'import'):
            order._check_import_ready_to_confirm()
        result = super().button_confirm()
        imports = self.filtered(lambda order: order.purchase_type == 'import')
        imports._update_landed_cost_status()
        imports._apply_expected_arrival()
        return result

    def button_draft(self):
        result = super().button_draft()
        imports = self.filtered(lambda order: order.purchase_type == 'import')
        imports.with_context(skip_import_approval_reset=True).write({'import_approval_state': 'draft'})
        return result

    def _check_import_ready_to_confirm(self):
        self.ensure_one()
        if self.import_approval_state != 'approved':
            raise UserError(_(
                'Submit this import and wait until the Department Manager, Deputy General Manager, and General Manager have approved their step.'
            ))
        if self.currency_id == self.company_id.currency_id:
            raise UserError(_('An import order must use a foreign currency. USD is the usual choice.'))
        if not self.incoterm_id:
            raise UserError(_('Set the Incoterm. Imports use FOB.'))

    def _import_approval_levels(self):
        self.ensure_one()
        amount = self.amount_total_cc or 0.0
        rounding = self.company_currency_id.rounding or 0.01
        levels = ['dm']
        if float_compare(amount, self.company_id.foreign_dm_limit, precision_rounding=rounding) > 0:
            levels.append('dgm')
        if float_compare(amount, self.company_id.foreign_dgm_limit, precision_rounding=rounding) > 0:
            levels.append('gm')
        return levels

    def action_submit_import_approval(self):
        for order in self:
            if order.purchase_type != 'import':
                raise UserError(_('Only an import order is sent through this approval.'))
            if order.state not in ('draft', 'sent'):
                raise UserError(_('Submit the order for approval while it is still a quotation.'))
            if not order.order_line.filtered(lambda line: not line.display_type):
                raise UserError(_('Add at least one product before submitting the import.'))
            levels = order._import_approval_levels()
            order.with_context(skip_import_approval_reset=True).write({
                'import_approval_state': levels[0],
            })
            order.message_post(body=_(
                'Submitted for import approval. %(amount)s Next step: %(step)s.',
                amount=order.import_approval_text or '',
                step=dict(order._fields['import_approval_state'].selection).get(levels[0]),
            ))

    def action_approve_import(self):
        labels = dict(self._fields['import_approval_state'].selection)
        for order in self:
            if not order.can_approve_import:
                raise UserError(_('You are not the approver for the current step of %s.', order.name))
            levels = order._import_approval_levels()
            current = order.import_approval_state
            if current not in levels:
                new_state = 'approved'
            else:
                index = levels.index(current)
                new_state = levels[index + 1] if index + 1 < len(levels) else 'approved'
            order.with_context(skip_import_approval_reset=True).write({
                'import_approval_state': new_state,
            })
            order.message_post(body=_('Import approval moved to: %s.', labels.get(new_state)))

    def action_reset_import_approval(self):
        drafts = self.filtered(lambda order: order.state in ('draft', 'sent', 'to approve'))
        drafts.with_context(skip_import_approval_reset=True).write({'import_approval_state': 'draft'})
        for order in drafts:
            order.message_post(body=_('Import approval was reset.'))

    def _company_amount(self, amount, on_date):
        self.ensure_one()
        if not amount or not self.currency_id or not self.company_currency_id:
            return 0.0
        return self.currency_id._convert(
            amount,
            self.company_currency_id,
            self.company_id,
            on_date or fields.Date.context_today(self),
        )

    def _check_lc_details(self):
        self.ensure_one()
        if self.import_payment_method != 'lc':
            return
        missing = []
        if not self.lc_number:
            missing.append(_('LC number'))
        if not self.lc_opening_date:
            missing.append(_('opening date'))
        if not self.lc_latest_shipment_date:
            missing.append(_('latest shipment date'))
        if not self.lc_expiry_date:
            missing.append(_('expiry date'))
        if missing:
            raise UserError(_('Fill in the letter of credit before continuing: %s.', ', '.join(missing)))

    def _bank_journal_and_account(self):
        self.ensure_one()
        journal = self.env['account.journal'].search([
            ('type', '=', 'bank'),
            ('company_id', '=', self.company_id.id),
            ('currency_id', 'in', (False, self.company_currency_id.id)),
        ], limit=1) or self.env['account.journal'].search([
            ('type', '=', 'bank'),
            ('company_id', '=', self.company_id.id),
        ], limit=1)
        if not journal or not journal.default_account_id:
            raise UserError(_('Set a bank journal with a bank account before recording the letter of credit.'))
        return journal

    def _general_journal(self):
        self.ensure_one()
        journal = self.company_id.currency_exchange_journal_id or self.env['account.journal'].search([
            ('type', '=', 'general'),
            ('company_id', '=', self.company_id.id),
        ], limit=1)
        if not journal:
            raise UserError(_('Set a miscellaneous journal before posting the letter of credit entries.'))
        return journal

    def action_register_lc_deposit(self):
        self.ensure_one()
        if self.state not in ('purchase', 'done'):
            raise UserError(_('Confirm the order before recording the deposit.'))
        if self.import_payment_method != 'lc':
            raise UserError(_('Record a letter-of-credit deposit only when the payment method is Letter of credit.'))
        self._check_lc_details()
        if self.currency_id.is_zero(self.lc_deposit_amount):
            raise UserError(_('Enter the deposit percent or the deposit amount first.'))
        if self.lc_deposit_move_id:
            return self._action_open_record(self.lc_deposit_move_id, _('LC Deposit'))
        deposit_account = self.company_id.foreign_lc_deposit_account_id
        if not deposit_account:
            raise UserError(_('Set the LC deposit account in Purchase settings. It holds the birr margin kept by the bank.'))
        if self.company_currency_id.is_zero(self.deposit_company_amount):
            raise UserError(_('The deposit in company currency is zero. Check the exchange rate on the opening date.'))
        bank = self._bank_journal_and_account()
        label = _('LC %(lc)s deposit for %(order)s', lc=self.lc_number, order=self.name)
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self._general_journal().id,
            'date': self.lc_opening_date or fields.Date.context_today(self),
            'ref': label,
            'line_ids': [
                Command.create({
                    'name': label,
                    'account_id': deposit_account.id,
                    'debit': self.deposit_company_amount,
                    'credit': 0.0,
                }),
                Command.create({
                    'name': label,
                    'account_id': bank.default_account_id.id,
                    'debit': 0.0,
                    'credit': self.deposit_company_amount,
                }),
            ],
        })
        move.action_post()
        self.with_context(skip_import_approval_reset=True).write({
            'lc_deposit_move_id': move.id,
            'lc_deposit_open': self.deposit_company_amount,
        })
        self.message_post(body=_(
            'Bank deposit %(move)s posted for %(amount).2f %(currency)s. This is the margin kept by the bank, not a payment to the supplier.',
            move=move.display_name,
            amount=self.deposit_company_amount,
            currency=self.company_currency_id.name,
        ))
        return self._action_open_record(move, _('LC Deposit'))

    def action_mark_utilization_sent(self):
        self.ensure_one()
        if self.import_payment_method != 'lc':
            raise UserError(_('A utilization letter is used for a letter of credit.'))
        self._check_lc_details()
        if not self.utilization_letter:
            raise UserError(_('Attach the signed utilization letter first. The bank form can be the signed file.'))
        if not self.lc_deposit_move_id:
            raise UserError(_('Record the bank deposit before attaching the utilization letter to that payment.'))
        self.write({
            'utilization_sent': True,
            'utilization_date': fields.Date.context_today(self),
        })
        self.env['ir.attachment'].create({
            'name': self.utilization_letter_name or _('Utilization letter %s', self.lc_number),
            'datas': self.utilization_letter,
            'res_model': 'account.move',
            'res_id': self.lc_deposit_move_id.id,
        })
        self.message_post(body=_('Utilization letter marked as sent for LC %s and attached to the bank deposit.', self.lc_number))
        self.lc_deposit_move_id.message_post(body=_('Signed utilization letter attached from %s.', self.name))

    def action_print_utilization_letter(self):
        self.ensure_one()
        if self.import_payment_method != 'lc':
            raise UserError(_('A utilization letter is used for a letter of credit.'))
        self._check_lc_details()
        return self.env.ref('foreign_purchase.action_report_utilization_letter').report_action(self)

    def action_create_landed_cost(self):
        self.ensure_one()
        receipts = self._import_receipts().filtered(lambda picking: picking.state == 'done')
        if not receipts:
            raise UserError(_('Validate the receipt before creating the landed cost. Leave the goods in the warehouse.'))
        if self.landed_cost_status == 'done' and self.landed_cost_ids:
            return self.action_view_landed_costs()
        cost = self.env['stock.landed.cost'].create({
            'picking_ids': [Command.set(receipts.ids)],
            'description': _('Import %s', self.name),
        })
        self._update_landed_cost_status()
        return self._action_open_record(cost, _('Landed Cost'))

    def action_view_landed_costs(self):
        self.ensure_one()
        return self._action_open_record(self.landed_cost_ids, _('Landed Costs'))

    def action_close_import_file(self):
        document_fields = [
            ('doc_bill_of_lading', _('Bill of lading')),
            ('doc_packing_list', _('Packing list')),
            ('doc_commercial_invoice', _('Commercial invoice')),
            ('doc_customs_declaration', _('Customs declaration')),
        ]
        for order in self:
            if order.purchase_type != 'import':
                raise UserError(_('Only an import file can be closed from this button.'))
            if order.state not in ('purchase', 'done'):
                raise UserError(_('Confirm the order before closing the file.'))
            if not order.import_payment_method:
                raise UserError(_('Choose the payment method before closing the file.'))
            if order.import_payment_method == 'lc':
                order._check_lc_details()
            if not order._import_receipts().filtered(lambda picking: picking.state == 'done'):
                raise UserError(_('Receive the goods before closing the file.'))
            missing = [label for field_name, label in document_fields if not order[field_name]]
            if missing:
                raise UserError(_('These documents are still missing: %s.', ', '.join(missing)))
            order.with_context(skip_import_approval_reset=True).write({
                'file_closed': True,
                'file_closed_date': fields.Date.context_today(order),
            })
            order.message_post(body=_('Import file closed.'))

    def action_reopen_import_file(self):
        self.with_context(skip_import_approval_reset=True).write({
            'file_closed': False,
            'file_closed_date': False,
        })

    def _apply_expected_arrival(self):
        for order in self.filtered('expected_arrival_date'):
            when = fields.Datetime.to_datetime(order.expected_arrival_date)
            receipts = order.picking_ids.filtered(
                lambda picking: picking.state not in ('done', 'cancel') and picking.location_id.usage == 'supplier'
            )
            if receipts:
                receipts.write({'scheduled_date': when})

    def _lc_settlement_figures(self, foreign_amount, booked_company_amount, rate, deposit_open):
        self.ensure_one()
        company = self.company_currency_id
        settlement = company.round(foreign_amount * rate)
        exchange = company.round(settlement - booked_company_amount)
        applied = min(max(deposit_open, 0.0), settlement)
        bank = company.round(settlement - applied)
        return settlement, exchange, applied, bank

    def _lc_cancel_refund(self, cancelled_foreign):
        self.ensure_one()
        if not self.lc_deposit_amount or self.currency_id.is_zero(self.lc_deposit_amount):
            return 0.0
        opening_rate = self.deposit_company_amount / self.lc_deposit_amount
        return self.company_currency_id.round(
            cancelled_foreign * opening_rate * (self.lc_deposit_percent or 0.0) / 100.0
        )

    def action_settle_lc(self):
        """Pay the supplier bill at the settlement rate and release the bank margin.

        The exchange difference is on the whole foreign amount. For 6,000 USD booked
        at 150 and settled at 152, the loss is 12,000 in company currency.
        """
        self.ensure_one()
        if self.import_payment_method != 'lc':
            raise UserError(_('Settle a letter of credit only when that is the payment method.'))
        return self._post_foreign_settlement(apply_deposit=True)

    def action_settle_foreign_payment(self):
        """Pay a bank wire or cash-against-documents bill and post the exchange difference."""
        self.ensure_one()
        if self.import_payment_method not in ('tt', 'cad'):
            raise UserError(_('Use Settle Payment for a bank wire or cash against documents.'))
        return self._post_foreign_settlement(apply_deposit=False)

    def _post_foreign_settlement(self, apply_deposit):
        self.ensure_one()
        title = _('LC Settlement') if apply_deposit else _('Foreign Payment')
        if self.lc_settlement_move_id:
            return self._action_open_record(self.lc_settlement_move_id, title)
        bills = self.invoice_ids.filtered(
            lambda move: move.state == 'posted'
            and move.move_type == 'in_invoice'
            and move.currency_id == self.currency_id
            and move.payment_state not in ('paid', 'in_payment', 'reversed')
        )
        if not bills:
            raise UserError(_('Post the supplier bill in the order currency before settling the payment.'))
        payable_lines = bills.line_ids.filtered(
            lambda line: line.account_id.account_type == 'liability_payable' and not line.reconciled
        )
        if not payable_lines:
            raise UserError(_('The supplier bill has no open payable line to settle.'))
        foreign = sum(bills.mapped('amount_residual'))
        booked = abs(sum(payable_lines.mapped('amount_residual')))
        rate = self.lc_settlement_rate or self._company_amount(1.0, fields.Date.context_today(self))
        if rate <= 0:
            raise UserError(_('Enter the settlement rate. It is the company currency paid for 1 unit of the order currency.'))
        deposit_open = self.lc_deposit_open if apply_deposit else 0.0
        _settlement, exchange, applied, bank_amount = self._lc_settlement_figures(
            foreign, booked, rate, deposit_open,
        )
        bank = self._bank_journal_and_account()
        deposit_account = self.company_id.foreign_lc_deposit_account_id
        if applied and not deposit_account:
            raise UserError(_('Set the LC deposit account in Purchase settings before settling.'))
        loss_account = self.company_id.expense_currency_exchange_account_id
        gain_account = self.company_id.income_currency_exchange_account_id
        if exchange > 0 and not loss_account:
            raise UserError(_('Set the Loss Exchange Rate account on the company before settling.'))
        if exchange < 0 and not gain_account:
            raise UserError(_('Set the Gain Exchange Rate account on the company before settling.'))
        if apply_deposit:
            label = _('LC %(lc)s settlement for %(order)s', lc=self.lc_number or self.name, order=self.name)
        elif self.import_payment_method == 'cad':
            label = _('Cash against documents for %(order)s', order=self.name)
        else:
            label = _('Bank wire for %(order)s', order=self.name)
        lines = [Command.create({
            'name': label,
            'account_id': payable_lines[:1].account_id.id,
            'partner_id': self.partner_id.id,
            'currency_id': self.currency_id.id,
            'amount_currency': foreign,
            'debit': booked,
            'credit': 0.0,
        })]
        if exchange > 0:
            lines.append(Command.create({
                'name': _('Exchange difference'),
                'account_id': loss_account.id,
                'debit': exchange,
                'credit': 0.0,
            }))
        elif exchange < 0:
            lines.append(Command.create({
                'name': _('Exchange difference'),
                'account_id': gain_account.id,
                'debit': 0.0,
                'credit': abs(exchange),
            }))
        if applied:
            lines.append(Command.create({
                'name': _('LC deposit applied'),
                'account_id': deposit_account.id,
                'debit': 0.0,
                'credit': applied,
            }))
        if bank_amount:
            lines.append(Command.create({
                'name': label,
                'account_id': bank.default_account_id.id,
                'debit': 0.0,
                'credit': bank_amount,
            }))
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self._general_journal().id,
            'date': fields.Date.context_today(self),
            'ref': label,
            'line_ids': lines,
        })
        move.action_post()
        payable_line = move.line_ids.filtered(
            lambda line: line.account_id == payable_lines[:1].account_id and line.partner_id == self.partner_id
        )
        (payable_lines | payable_line).reconcile()
        values = {
            'lc_settlement_rate': rate,
            'lc_settlement_move_id': move.id,
            'lc_exchange_difference': exchange,
        }
        if apply_deposit:
            values['lc_deposit_open'] = self.lc_deposit_open - applied
        self.with_context(skip_import_approval_reset=True).write(values)
        self.message_post(body=_(
            'Foreign payment settled at %(rate).2f. Exchange difference %(diff).2f %(currency)s. Bank paid %(bank).2f and the deposit applied was %(deposit).2f.',
            rate=rate,
            diff=exchange,
            currency=self.company_currency_id.name,
            bank=bank_amount,
            deposit=applied,
        ))
        return self._action_open_record(move, title)

    def action_load_supplier_comparison(self):
        """Line up this order with other open import quotes for the same goods."""
        self.ensure_one()
        if self.purchase_type != 'import':
            raise UserError(_('A supplier comparison is used on an import order.'))
        products = self.order_line.product_id
        others = self.env['purchase.order']
        if products:
            others = self.search([
                ('purchase_type', '=', 'import'),
                ('state', 'in', ('draft', 'sent', 'to approve', 'purchase')),
                ('id', '!=', self.id),
                ('company_id', '=', self.company_id.id),
                ('order_line.product_id', 'in', products.ids),
            ])
        if self.requisition_id:
            others |= self.search([
                ('requisition_id', '=', self.requisition_id.id),
                ('id', '!=', self.id),
                ('state', '!=', 'cancel'),
            ])
        already = set(self.comparison_ids.source_order_id.ids)
        commands = []
        for order in (self | others).sorted('id'):
            if order.id in already:
                continue
            commands.append(Command.create({
                'partner_id': order.partner_id.id,
                'currency_id': order.currency_id.id,
                'amount_total': order.amount_total,
                'incoterm_id': order.incoterm_id.id,
                'source_order_id': order.id,
                'selected': order == self and order.state in ('purchase', 'done'),
            }))
        if commands:
            self.comparison_ids = commands
        return True

    def action_cancel_lc_balance(self):
        """Return the margin held for a foreign amount the bank will not pay."""
        self.ensure_one()
        if self.currency_id.is_zero(self.lc_cancelled_amount):
            raise UserError(_('Enter the cancelled letter-of-credit balance in the order currency first.'))
        if self.lc_cancel_move_id:
            return self._action_open_record(self.lc_cancel_move_id, _('LC Balance Cancellation'))
        if not self.lc_deposit_move_id:
            raise UserError(_('Record the bank deposit before cancelling an unused balance.'))
        refund = self._lc_cancel_refund(self.lc_cancelled_amount)
        if self.company_currency_id.is_zero(refund):
            raise UserError(_('The refund against the deposit is zero. Check the deposit percent and the opening rate.'))
        if refund > self.lc_deposit_open + self.company_currency_id.rounding:
            raise UserError(_('The refund is larger than the deposit still held by the bank.'))
        bank = self._bank_journal_and_account()
        deposit_account = self.company_id.foreign_lc_deposit_account_id
        if not deposit_account:
            raise UserError(_('Set the LC deposit account in Purchase settings.'))
        label = _('LC %(lc)s unused balance %(amount)s %(cur)s',
                  lc=self.lc_number or self.name,
                  amount=self.lc_cancelled_amount,
                  cur=self.currency_id.name)
        move = self.env['account.move'].create({
            'move_type': 'entry',
            'journal_id': self._general_journal().id,
            'date': fields.Date.context_today(self),
            'ref': label,
            'line_ids': [
                Command.create({
                    'name': label,
                    'account_id': bank.default_account_id.id,
                    'debit': refund,
                    'credit': 0.0,
                }),
                Command.create({
                    'name': label,
                    'account_id': deposit_account.id,
                    'debit': 0.0,
                    'credit': refund,
                }),
            ],
        })
        move.action_post()
        self.with_context(skip_import_approval_reset=True).write({
            'lc_cancel_move_id': move.id,
            'lc_deposit_open': self.lc_deposit_open - refund,
        })
        self.message_post(body=_(
            'Cancelled %(foreign)s %(cur)s. The bank returned %(refund).2f %(cc)s of the deposit.',
            foreign=self.lc_cancelled_amount,
            cur=self.currency_id.name,
            refund=refund,
            cc=self.company_currency_id.name,
        ))
        return self._action_open_record(move, _('LC Balance Cancellation'))

    def _import_receipts(self):
        return self.picking_ids.filtered(
            lambda picking: picking.location_id.usage == 'supplier'
            and picking.location_dest_id.usage == 'internal'
            and picking.state != 'cancel'
        )

    def _update_landed_cost_status(self):
        for order in self:
            if order.purchase_type != 'import':
                if order.landed_cost_status:
                    order.with_context(skip_import_approval_reset=True).landed_cost_status = False
                continue
            receipts = order._import_receipts().filtered(lambda picking: picking.state == 'done')
            if not receipts:
                status = 'waiting_receipt'
            else:
                covered = self.env['stock.landed.cost'].search([
                    ('state', '=', 'done'),
                    ('picking_ids', 'in', receipts.ids),
                ]).picking_ids
                status = 'done' if all(picking in covered for picking in receipts) else 'pending'
            if order.landed_cost_status != status:
                order.with_context(skip_import_approval_reset=True).landed_cost_status = status

    def _action_open_record(self, records, name):
        action = {
            'type': 'ir.actions.act_window',
            'name': name,
            'res_model': records._name,
            'domain': [('id', 'in', records.ids)],
            'context': {'create': False},
        }
        if len(records) == 1:
            action.update({'view_mode': 'form', 'res_id': records.id})
        else:
            action['view_mode'] = 'list,form'
        return action

    @api.model
    def _cron_foreign_purchase_reminders(self):
        today = fields.Date.context_today(self)
        orders = self.search([
            ('purchase_type', '=', 'import'),
            ('state', 'in', ('purchase', 'done')),
            ('file_closed', '=', False),
        ])
        for order in orders:
            expiry_days = order.company_id.foreign_reminder_days or 0
            shipment_days = order.company_id.foreign_shipment_reminder_days or 0
            shipped = bool(order.shipment_reference) or bool(
                order._import_receipts().filtered(lambda picking: picking.state == 'done')
            )
            if order.lc_expiry_date and order.lc_expiry_date <= today + timedelta(days=expiry_days):
                order._schedule_import_reminder(
                    _('LC expiry'),
                    _('Letter of credit %(lc)s on %(order)s expires on %(date)s.',
                      lc=order.lc_number or '-',
                      order=order.name,
                      date=fields.Date.to_string(order.lc_expiry_date)),
                    order.lc_expiry_date,
                )
            if (
                not shipped
                and order.lc_latest_shipment_date
                and order.lc_latest_shipment_date <= today + timedelta(days=shipment_days)
            ):
                order._schedule_import_reminder(
                    _('Latest shipment date'),
                    _('The latest shipment date for %(order)s is %(date)s. The goods have not shipped.',
                      order=order.name,
                      date=fields.Date.to_string(order.lc_latest_shipment_date)),
                    order.lc_latest_shipment_date,
                )
            if order.landed_cost_status == 'pending':
                order._schedule_import_reminder(
                    _('Landed cost still open'),
                    _('Validate the landed cost of %(order)s before the goods are issued.', order=order.name),
                    today,
                )

    def _schedule_import_reminder(self, summary, note, deadline):
        self.ensure_one()
        user = self.import_officer_id or self.user_id
        if not user:
            return
        if self.activity_ids.filtered(lambda activity: activity.summary == summary and activity.user_id == user):
            return
        self.activity_schedule(
            'mail.mail_activity_data_todo',
            user_id=user.id,
            summary=summary,
            note=note,
            date_deadline=deadline,
        )
