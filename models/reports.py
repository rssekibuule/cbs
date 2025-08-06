
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

class BankingReport(models.TransientModel):
    _name = 'core_banking.report'
    _description = 'Banking Reports'
    
    report_type = fields.Selection([
        ('balance_sheet', 'Balance Sheet'),
        ('profit_loss', 'Profit & Loss'),
        ('cash_flow', 'Cash Flow Statement'),
        ('customer_analysis', 'Customer Analysis'),
        ('loan_portfolio', 'Loan Portfolio Analysis'),
        ('deposit_analysis', 'Deposit Analysis'),
        ('transaction_summary', 'Transaction Summary')
    ], string='Report Type', required=True)
    
    # Date Range
    date_from = fields.Date(string='From Date', required=True, 
                           default=lambda self: fields.Date.today().replace(day=1))
    date_to = fields.Date(string='To Date', required=True,
                         default=fields.Date.today)
    
    # Filters
    branch_ids = fields.Many2many('core_banking.branch', string='Branches')
    customer_segment_ids = fields.Many2many('core_banking.customer.segment', string='Customer Segments')
    account_type_ids = fields.Many2many('core_banking.account.type', string='Account Types')
    
    # Report Data
    report_html = fields.Html(string='Report', readonly=True)
    
    def generate_report(self):
        """Generate the selected report"""
        self.ensure_one()
        
        if self.report_type == 'balance_sheet':
            self._generate_balance_sheet()
        elif self.report_type == 'profit_loss':
            self._generate_profit_loss()
        elif self.report_type == 'customer_analysis':
            self._generate_customer_analysis()
        elif self.report_type == 'loan_portfolio':
            self._generate_loan_portfolio()
        elif self.report_type == 'deposit_analysis':
            self._generate_deposit_analysis()
        elif self.report_type == 'transaction_summary':
            self._generate_transaction_summary()
        
        return {
            'name': _('Banking Report'),
            'view_mode': 'form',
            'res_model': 'core_banking.report',
            'res_id': self.id,
            'type': 'ir.actions.act_window',
            'target': 'current',
        }
    
    def _generate_balance_sheet(self):
        """Generate Balance Sheet"""
        # Customer Deposits (Liabilities)
        deposits_domain = [
            ('state', '=', 'active'),
            ('last_transaction_date', '>=', self.date_from),
            ('last_transaction_date', '<=', self.date_to)
        ]
        if self.branch_ids:
            deposits_domain.append(('branch_id', 'in', self.branch_ids.ids))
        
        accounts = self.env['core_banking.account'].search(deposits_domain)
        total_deposits = sum(accounts.mapped('balance'))
        
        # Loans (Assets)
        loans_domain = [
            ('state', 'in', ['disbursed', 'closed']),
            ('disbursement_date', '>=', self.date_from),
            ('disbursement_date', '<=', self.date_to)
        ]
        if self.branch_ids:
            loans_domain.append(('branch_id', 'in', self.branch_ids.ids))
        
        loans = self.env['core_banking.loan'].search(loans_domain)
        total_loans = sum(loans.mapped('outstanding_balance'))
        
        # Fixed Deposits (Liabilities)
        fd_domain = [
            ('state', '=', 'active'),
            ('deposit_date', '>=', self.date_from),
            ('deposit_date', '<=', self.date_to)
        ]
        if self.branch_ids:
            fd_domain.append(('branch_id', 'in', self.branch_ids.ids))
        
        fixed_deposits = self.env['core_banking.fixed.deposit'].search(fd_domain)
        total_fixed_deposits = sum(fixed_deposits.mapped('current_value'))
        
        # Generate HTML
        html = f"""
        <div class="o_report_layout">
            <h2>Balance Sheet</h2>
            <p>Period: {self.date_from} to {self.date_to}</p>
            
            <table class="table table-striped">
                <thead>
                    <tr>
                        <th>Assets</th>
                        <th class="text-right">Amount</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>Loans Outstanding</td>
                        <td class="text-right">{total_loans:,.2f}</td>
                    </tr>
                    <tr class="table-info">
                        <td><strong>Total Assets</strong></td>
                        <td class="text-right"><strong>{total_loans:,.2f}</strong></td>
                    </tr>
                </tbody>
            </table>
            
            <table class="table table-striped">
                <thead>
                    <tr>
                        <th>Liabilities</th>
                        <th class="text-right">Amount</th>
                    </tr>
                </thead>
                <tbody>
                    <tr>
                        <td>Customer Deposits</td>
                        <td class="text-right">{total_deposits:,.2f}</td>
                    </tr>
                    <tr>
                        <td>Fixed Deposits</td>
                        <td class="text-right">{total_fixed_deposits:,.2f}</td>
                    </tr>
                    <tr class="table-info">
                        <td><strong>Total Liabilities</strong></td>
                        <td class="text-right"><strong>{total_deposits + total_fixed_deposits:,.2f}</strong></td>
                    </tr>
                </tbody>
            </table>
        </div>
        """
        
        self.report_html = html
    
    def _generate_customer_analysis(self):
        """Generate Customer Analysis Report"""
        domain = []
        if self.branch_ids:
            domain.append(('branch_id', 'in', self.branch_ids.ids))
        if self.customer_segment_ids:
            domain.append(('customer_segment_id', 'in', self.customer_segment_ids.ids))
        
        customers = self.env['core_banking.customer'].search(domain)
        
        # Customer Segmentation
        segment_data = {}
        for customer in customers:
            segment = customer.customer_segment_id.name if customer.customer_segment_id else 'Unassigned'
            if segment not in segment_data:
                segment_data[segment] = {'count': 0, 'total_balance': 0}
            segment_data[segment]['count'] += 1
            segment_data[segment]['total_balance'] += customer.total_balance
        
        # Top customers by balance
        top_customers = customers.sorted('total_balance', reverse=True)[:10]
        
        html = f"""
        <div class="o_report_layout">
            <h2>Customer Analysis Report</h2>
            <p>Total Customers: {len(customers)}</p>
            
            <h3>Customer Segmentation</h3>
            <table class="table table-striped">
                <thead>
                    <tr>
                        <th>Segment</th>
                        <th>Customer Count</th>
                        <th>Total Balance</th>
                        <th>Average Balance</th>
                    </tr>
                </thead>
                <tbody>
        """
        
        for segment, data in segment_data.items():
            avg_balance = data['total_balance'] / data['count'] if data['count'] > 0 else 0
            html += f"""
                    <tr>
                        <td>{segment}</td>
                        <td>{data['count']}</td>
                        <td>{data['total_balance']:,.2f}</td>
                        <td>{avg_balance:,.2f}</td>
                    </tr>
            """
        
        html += """
                </tbody>
            </table>
            
            <h3>Top 10 Customers by Balance</h3>
            <table class="table table-striped">
                <thead>
                    <tr>
                        <th>Customer</th>
                        <th>Total Balance</th>
                        <th>Account Count</th>
                    </tr>
                </thead>
                <tbody>
        """
        
        for customer in top_customers:
            html += f"""
                    <tr>
                        <td>{customer.name}</td>
                        <td>{customer.total_balance:,.2f}</td>
                        <td>{len(customer.account_ids)}</td>
                    </tr>
            """
        
        html += """
                </tbody>
            </table>
        </div>
        """
        
        self.report_html = html
    
    def _generate_loan_portfolio(self):
        """Generate Loan Portfolio Analysis"""
        domain = [('state', 'in', ['approved', 'disbursed', 'closed', 'defaulted'])]
        if self.branch_ids:
            domain.append(('branch_id', 'in', self.branch_ids.ids))
        
        loans = self.env['core_banking.loan'].search(domain)
        
        # Portfolio Summary
        total_loans = len(loans)
        total_principal = sum(loans.mapped('principal_amount'))
        total_outstanding = sum(loans.mapped('outstanding_balance'))
        total_paid = sum(loans.mapped('total_paid'))
        
        # Loan Status Breakdown
        status_data = {}
        for loan in loans:
            status = loan.state
            if status not in status_data:
                status_data[status] = {'count': 0, 'amount': 0}
            status_data[status]['count'] += 1
            status_data[status]['amount'] += loan.principal_amount
        
        # Overdue Analysis
        overdue_loans = loans.filtered('is_overdue')
        total_overdue_amount = sum(overdue_loans.mapped('overdue_amount'))
        
        html = f"""
        <div class="o_report_layout">
            <h2>Loan Portfolio Analysis</h2>
            
            <div class="row">
                <div class="col-md-3">
                    <div class="card">
                        <div class="card-body">
                            <h5>Total Loans</h5>
                            <h3>{total_loans}</h3>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card">
                        <div class="card-body">
                            <h5>Total Principal</h5>
                            <h3>{total_principal:,.0f}</h3>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card">
                        <div class="card-body">
                            <h5>Outstanding</h5>
                            <h3>{total_outstanding:,.0f}</h3>
                        </div>
                    </div>
                </div>
                <div class="col-md-3">
                    <div class="card">
                        <div class="card-body">
                            <h5>Overdue Amount</h5>
                            <h3 class="text-danger">{total_overdue_amount:,.0f}</h3>
                        </div>
                    </div>
                </div>
            </div>
            
            <h3>Loan Status Breakdown</h3>
            <table class="table table-striped">
                <thead>
                    <tr>
                        <th>Status</th>
                        <th>Count</th>
                        <th>Amount</th>
                        <th>Percentage</th>
                    </tr>
                </thead>
                <tbody>
        """
        
        for status, data in status_data.items():
            percentage = (data['amount'] / total_principal * 100) if total_principal > 0 else 0
            html += f"""
                    <tr>
                        <td>{status.title()}</td>
                        <td>{data['count']}</td>
                        <td>{data['amount']:,.2f}</td>
                        <td>{percentage:.1f}%</td>
                    </tr>
            """
        
        html += """
                </tbody>
            </table>
        </div>
        """
        
        self.report_html = html
    
    def _generate_deposit_analysis(self):
        """Generate Deposit Analysis Report"""
        # Regular Accounts
        account_domain = [('state', '=', 'active')]
        if self.branch_ids:
            account_domain.append(('branch_id', 'in', self.branch_ids.ids))
        
        accounts = self.env['core_banking.account'].search(account_domain)
        total_account_balance = sum(accounts.mapped('balance'))
        
        # Fixed Deposits
        fd_domain = [('state', '=', 'active')]
        if self.branch_ids:
            fd_domain.append(('branch_id', 'in', self.branch_ids.ids))
        
        fixed_deposits = self.env['core_banking.fixed.deposit'].search(fd_domain)
        total_fd_balance = sum(fixed_deposits.mapped('current_value'))
        
        # Account Type Analysis
        type_data = {}
        for account in accounts:
            acc_type = account.account_type_id.name
            if acc_type not in type_data:
                type_data[acc_type] = {'count': 0, 'balance': 0}
            type_data[acc_type]['count'] += 1
            type_data[acc_type]['balance'] += account.balance
        
        html = f"""
        <div class="o_report_layout">
            <h2>Deposit Analysis Report</h2>
            
            <div class="row">
                <div class="col-md-4">
                    <div class="card">
                        <div class="card-body">
                            <h5>Total Accounts</h5>
                            <h3>{len(accounts)}</h3>
                        </div>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="card">
                        <div class="card-body">
                            <h5>Account Deposits</h5>
                            <h3>{total_account_balance:,.0f}</h3>
                        </div>
                    </div>
                </div>
                <div class="col-md-4">
                    <div class="card">
                        <div class="card-body">
                            <h5>Fixed Deposits</h5>
                            <h3>{total_fd_balance:,.0f}</h3>
                        </div>
                    </div>
                </div>
            </div>
            
            <h3>Account Type Breakdown</h3>
            <table class="table table-striped">
                <thead>
                    <tr>
                        <th>Account Type</th>
                        <th>Count</th>
                        <th>Total Balance</th>
                        <th>Average Balance</th>
                    </tr>
                </thead>
                <tbody>
        """
        
        for acc_type, data in type_data.items():
            avg_balance = data['balance'] / data['count'] if data['count'] > 0 else 0
            html += f"""
                    <tr>
                        <td>{acc_type}</td>
                        <td>{data['count']}</td>
                        <td>{data['balance']:,.2f}</td>
                        <td>{avg_balance:,.2f}</td>
                    </tr>
            """
        
        html += """
                </tbody>
            </table>
        </div>
        """
        
        self.report_html = html
    
    def _generate_transaction_summary(self):
        """Generate Transaction Summary Report"""
        domain = [
            ('transaction_date', '>=', self.date_from),
            ('transaction_date', '<=', self.date_to),
            ('state', '=', 'posted')
        ]
        if self.branch_ids:
            domain.append(('branch_id', 'in', self.branch_ids.ids))
        
        transactions = self.env['core_banking.transaction'].search(domain)
        
        # Transaction Type Summary
        type_data = {}
        for txn in transactions:
            txn_type = txn.transaction_type
            if txn_type not in type_data:
                type_data[txn_type] = {'count': 0, 'amount': 0}
            type_data[txn_type]['count'] += 1
            type_data[txn_type]['amount'] += abs(txn.amount)
        
        # Daily Transaction Volume
        daily_data = {}
        for txn in transactions:
            date_str = txn.transaction_date.date().strftime('%Y-%m-%d')
            if date_str not in daily_data:
                daily_data[date_str] = {'count': 0, 'amount': 0}
            daily_data[date_str]['count'] += 1
            daily_data[date_str]['amount'] += abs(txn.amount)
        
        total_transactions = len(transactions)
        total_amount = sum(abs(txn.amount) for txn in transactions)
        
        html = f"""
        <div class="o_report_layout">
            <h2>Transaction Summary Report</h2>
            <p>Period: {self.date_from} to {self.date_to}</p>
            
            <div class="row">
                <div class="col-md-6">
                    <div class="card">
                        <div class="card-body">
                            <h5>Total Transactions</h5>
                            <h3>{total_transactions}</h3>
                        </div>
                    </div>
                </div>
                <div class="col-md-6">
                    <div class="card">
                        <div class="card-body">
                            <h5>Total Volume</h5>
                            <h3>{total_amount:,.0f}</h3>
                        </div>
                    </div>
                </div>
            </div>
            
            <h3>Transaction Type Breakdown</h3>
            <table class="table table-striped">
                <thead>
                    <tr>
                        <th>Transaction Type</th>
                        <th>Count</th>
                        <th>Total Amount</th>
                        <th>Average Amount</th>
                    </tr>
                </thead>
                <tbody>
        """
        
        for txn_type, data in type_data.items():
            avg_amount = data['amount'] / data['count'] if data['count'] > 0 else 0
            html += f"""
                    <tr>
                        <td>{txn_type.title()}</td>
                        <td>{data['count']}</td>
                        <td>{data['amount']:,.2f}</td>
                        <td>{avg_amount:,.2f}</td>
                    </tr>
            """
        
        html += """
                </tbody>
            </table>
        </div>
        """
        
        self.report_html = html


class BankingDashboard(models.Model):
    _name = 'core_banking.dashboard'
    _description = 'Banking Dashboard'
    
    name = fields.Char(string='Dashboard Name', required=True)
    user_id = fields.Many2one('res.users', string='User', default=lambda self: self.env.user)
    
    # Key Metrics (computed fields)
    total_customers = fields.Integer(string='Total Customers', compute='_compute_metrics')
    total_accounts = fields.Integer(string='Total Accounts', compute='_compute_metrics')
    total_deposits = fields.Monetary(string='Total Deposits', compute='_compute_metrics')
    total_loans = fields.Monetary(string='Total Loans', compute='_compute_metrics')
    overdue_loans = fields.Monetary(string='Overdue Loans', compute='_compute_metrics')
    
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)
    
    @api.depends()  # Will be triggered manually or by cron
    def _compute_metrics(self):
        for dashboard in self:
            # Get current metrics
            dashboard.total_customers = self.env['core_banking.customer'].search_count([('state', '=', 'active')])
            dashboard.total_accounts = self.env['core_banking.account'].search_count([('state', '=', 'active')])
            
            accounts = self.env['core_banking.account'].search([('state', '=', 'active')])
            dashboard.total_deposits = sum(accounts.mapped('balance'))
            
            loans = self.env['core_banking.loan'].search([('state', 'in', ['disbursed', 'closed'])])
            dashboard.total_loans = sum(loans.mapped('outstanding_balance'))
            dashboard.overdue_loans = sum(loans.filtered('is_overdue').mapped('overdue_amount'))
