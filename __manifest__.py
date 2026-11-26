{
    'name': 'Foreign Purchase',
    'version': '19.0.1.6.0',
    'category': 'Supply Chain/Purchase',
    'summary': 'Import orders, letter of credit, approval bands, and landed cost hold',
    'description': """
Foreign purchases are opened from Purchase > Orders > Foreign Purchases.

Each import order has an Import / LC tab for the letter of credit, the
deposit, the Incoterm, shipment notes, documents, and third-party claims.
Department Manager, Deputy General Manager, and General Manager approve by
the order value in company currency. Goods received on an import stay in
the warehouse until the landed cost is validated.
    """,
    'author': 'Top System Solutions Technologies PLC',
    'license': 'LGPL-3',
    'depends': [
        'purchase_stock',
        'stock_landed_costs',
        'approvals_purchase',
    ],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'data/currency_data.xml',
        'data/product_data.xml',
        'data/approval_category_data.xml',
        'data/requisition_data.xml',
        'data/ir_cron.xml',
        'views/approval_product_line_views.xml',
        'views/purchase_order_views.xml',
        'views/warehouse_requisition_views.xml',
        'views/landed_cost_report_views.xml',
        'views/res_config_settings_views.xml',
        'report/utilization_letter.xml',
    ],
    'installable': True,
    'application': False,
}
