import base64

from odoo import Command, fields
from odoo.exceptions import UserError, ValidationError
from odoo.tests import tagged

from odoo.addons.account.tests.common import AccountTestInvoicingCommon


@tagged('post_install', '-at_install')
class TestForeignPurchase(AccountTestInvoicingCommon):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.company.write({
            'foreign_dm_limit': 100000.0,
            'foreign_dgm_limit': 1000000.0,
        })
        cls.env.user.write({
            'group_ids': [Command.link(cls.env.ref('purchase.group_purchase_manager').id)],
        })
        cls.currency = cls.env['res.currency'].create({
            'name': 'USX',
            'symbol': 'USX',
            'rounding': 0.01,
            'currency_unit_label': 'Dollar',
            'currency_subunit_label': 'Cent',
        })
        cls.env['res.currency.rate'].create({
            'name': fields.Date.today(),
            'currency_id': cls.currency.id,
            'company_id': cls.company.id,
            'inverse_company_rate': 150.0,
        })
        cls.incoterm = cls.env.ref('account.incoterm_FOB')

    def _create_import(self, price_unit=150.0, qty=40.0):
        order = self.env['purchase.order'].create({
            'partner_id': self.partner_a.id,
            'purchase_type': 'import',
            'currency_id': self.currency.id,
            'incoterm_id': self.incoterm.id,
            'import_payment_method': 'lc',
            'lc_number': 'LC-TEST',
            'lc_opening_date': fields.Date.today(),
            'lc_latest_shipment_date': fields.Date.today(),
            'lc_expiry_date': fields.Date.add(fields.Date.today(), days=30),
            'lc_deposit_percent': 50.0,
            'order_line': [Command.create({
                'product_id': self.product_a.id,
                'name': 'Floodlight',
                'product_qty': qty,
                'price_unit': price_unit,
                'product_uom_id': self.product_a.uom_id.id,
                'date_planned': fields.Datetime.now(),
            })],
        })
        order.order_line.price_unit = price_unit
        return order

    def test_floodlight_deposit_and_approval_band(self):
        order = self._create_import()
        self.assertEqual(order.amount_total, 6000.0)
        self.assertEqual(order.lc_deposit_amount, 3000.0)
        self.assertEqual(order.balance_foreign_amount, 3000.0)
        self.assertAlmostEqual(order.amount_total_cc, 900000.0, places=2)
        self.assertAlmostEqual(order.deposit_company_amount, 450000.0, places=2)
        self.assertAlmostEqual(order.import_company_rate, 150.0, places=2)
        self.assertIn('6000.00', order.import_approval_text)
        self.assertIn('900000.00', order.import_approval_text)
        self.assertEqual(order._import_approval_levels(), ['dm', 'dgm'])
        settlement, exchange, applied, bank = order._lc_settlement_figures(6000.0, 900000.0, 152.0, 450000.0)
        self.assertAlmostEqual(settlement, 912000.0, places=2)
        self.assertAlmostEqual(exchange, 12000.0, places=2)
        self.assertAlmostEqual(applied, 450000.0, places=2)
        self.assertAlmostEqual(bank, 462000.0, places=2)
        self.assertAlmostEqual(order._lc_cancel_refund(300.0), 22500.0, places=2)

        with self.assertRaises(UserError):
            order.button_confirm()

        order.action_submit_import_approval()
        self.assertEqual(order.import_approval_state, 'dm')
        order.action_approve_import()
        self.assertEqual(order.import_approval_state, 'dgm')
        order.action_approve_import()
        self.assertEqual(order.import_approval_state, 'approved')

    def test_above_dgm_limit_needs_general_manager(self):
        order = self._create_import(price_unit=200.0, qty=40.0)
        self.assertGreater(order.amount_total_cc, 1000000.0)
        self.assertEqual(order._import_approval_levels(), ['dm', 'dgm', 'gm'])

    def test_small_order_stops_at_department_manager(self):
        order = self._create_import(price_unit=10.0, qty=1.0)
        self.assertEqual(order._import_approval_levels(), ['dm'])
        order.action_submit_import_approval()
        order.action_approve_import()
        self.assertEqual(order.import_approval_state, 'approved')

    def test_shipment_date_cannot_pass_expiry(self):
        order = self._create_import(price_unit=10.0, qty=1.0)
        with self.assertRaises(ValidationError):
            order.lc_latest_shipment_date = fields.Date.add(order.lc_expiry_date, days=1)

    def test_bank_wire_settlement_uses_the_full_bill(self):
        order = self._create_import()
        settlement, exchange, applied, bank = order._lc_settlement_figures(6000.0, 900000.0, 152.0, 0.0)
        self.assertAlmostEqual(settlement, 912000.0, places=2)
        self.assertAlmostEqual(exchange, 12000.0, places=2)
        self.assertAlmostEqual(applied, 0.0, places=2)
        self.assertAlmostEqual(bank, 912000.0, places=2)

    def test_supplier_comparison_lists_the_other_quote(self):
        first = self._create_import()
        second = self._create_import(price_unit=160.0)
        first.action_load_supplier_comparison()
        sources = first.comparison_ids.source_order_id
        self.assertIn(first, sources)
        self.assertIn(second, sources)

    def test_warehouse_requisition_creates_import_request(self):
        requisition = self.env['foreign.purchase.requisition'].create({
            'specification': '40 floodlights, IP65',
            'product_id': self.product_a.id,
            'quantity': 40.0,
            'proforma': base64.b64encode(b'proforma'),
            'proforma_name': 'proforma.pdf',
        })
        requisition.action_submit()
        requisition.action_mark_proforma()
        self.assertEqual(requisition.state, 'proforma')
        requisition.action_create_import_request()
        self.assertEqual(requisition.state, 'requested')
        self.assertEqual(requisition.approval_request_id.foreign_requisition_id, requisition)
        self.assertEqual(requisition.approval_request_id.category_id.is_import_purchase, True)

    def test_no_hold_without_an_import_receipt(self):
        held = self.env['stock.move']._foreign_purchase_qty_on_hold(self.product_a, self.company)
        self.assertFalse(held)
