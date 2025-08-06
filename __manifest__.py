{
    'name': "Core Banking System",
    'version': '18.0.1.0.0',
    'depends': [
        'base', 
        'mail', 
        'contacts',
        'account',
        'web',
    ],
    'author': "Your Organization",
    'category': 'Banking',
    'description': """
        Comprehensive Core Banking System
        - Customer Management (KYC, profiles, segmentation)
        - Account Management (savings, current, group accounts)
        - Loan Management (origination, approval, collections)
        - Deposit Management (savings, fixed deposits)
        - Transaction Processing
        - Accounting & General Ledger
        - Reporting & Analytics
        - Branch & Agent Banking
    """,
    'data': [
        # Security
        'security/security.xml',
        'security/ir.model.access.xml',
        
        # Data
        'data/sequences.xml',
        
        # Views
        'views/customer_views.xml',
        'views/account_views.xml',
        'views/transaction_views.xml',
        'views/loan_views.xml',
        'views/deposit_views.xml',
        'views/supporting_views.xml',
        
        # Wizards
    ],
    'demo': [],
    'assets': {
        'web.assets_backend': [
            'core_banking/static/src/scss/dashboard.scss',
            'core_banking/static/src/js/dashboard.js',
            'core_banking/static/src/xml/dashboard.xml',
        ],
        'web.assets_qweb': [
            'core_banking/static/src/xml/dashboard.xml',
        ],
    },
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}