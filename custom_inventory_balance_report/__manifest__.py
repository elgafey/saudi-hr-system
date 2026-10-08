{
    'name': 'Custom Inventory Balance Report',
    'version': '19.0.1.0.0',
    'category': 'Inventory/Inventory',
    'summary': 'Company-Wide Inventory Balance & Movement Report',
    'description': """
Company-Wide Inventory Balance & Movement Report
================================================
- Opening / Incoming / Outgoing / Closing per product
- All warehouses aggregated to company level
- Uses done stock.move quantities (Odoo 19)
- Value from product.standard_price when available, else 0.0
- PDF report (A4 Landscape)
    """,
    'author': 'Custom Development',
    'license': 'LGPL-3',
    'depends': ['stock'],
    'data': [
        'security/ir.model.access.csv',
        'views/inventory_balance_wizard_views.xml',
        'report/inventory_balance_report.xml',
        'report/inventory_balance_report_template.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'post_init_hook': 'post_init_hook',
}
