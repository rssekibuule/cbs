from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from datetime import date, datetime, timedelta
import logging

_logger = logging.getLogger(__name__)

class Account(models.Model):
    _name = 'core_banking.account'
    _description = 'Bank Account'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    # Basic Information
    name = fields.Char(string='Account Name', required=True, tracking=True)
    account_number = fields.Char(string='Account Number', readonly=True, copy=False, index=True, default='New')
    account_type_id = fields.Many2one('core_banking.account.type', string='Account Type', required=True, 
                                    tracking=True, ondelete='restrict')
    customer_id = fields.Many2one('core_banking.customer', string='Primary Holder', required=True, 
                                 ondelete='restrict', tracking=True)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True, 
                                default=lambda self: self.env.company.currency_id, ondelete='restrict')
    
    # Joint Holders
    joint_holder_ids = fields.Many2many(
        'core_banking.customer', 
        'account_joint_holder_rel', 
        'account_id', 
        'customer_id',
        string='Joint Holders',
        help="Additional account holders for joint accounts"
    )
    
    # Balance Information
    balance = fields.Monetary(string='Current Balance', default=0.0, tracking=True)
    available_balance = fields.Monetary(string='Available Balance', compute='_compute_available_balance', store=True)
    hold_amount = fields.Monetary(string='Amount on Hold', default=0.0)
    
    # Status Information
    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('dormant', 'Dormant'),
        ('restricted', 'Restricted'),
        ('closed', 'Closed')
    ], string='Status', default='draft', tracking=True)
    
    # Account Features
    allow_overdraft = fields.Boolean(string='Allow Overdraft', default=False)
    overdraft_limit = fields.Monetary(string='Overdraft Limit')
    interest_rate = fields.Float(string='Interest Rate (%)', digits=(4, 6))
    interest_calculation = fields.Selection([
        ('daily', 'Daily'),
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('yearly', 'Yearly')
    ], string='Interest Calculation', default='monthly')
    
    # Related Fields
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company, 
                                ondelete='restrict')
    branch_id = fields.Many2one('core_banking.branch', string='Branch', required=True, ondelete='restrict')
    account_officer_id = fields.Many2one('res.users', string='Account Officer', ondelete='set null',
                                       tracking=True)
    
    # Transaction Information
    last_transaction_date = fields.Datetime(string='Last Transaction Date')
    statement_delivery = fields.Selection([
        ('email', 'Email'),
        ('post', 'Post'),
        ('both', 'Both'),
        ('none', 'None')
    ], string='Statement Delivery', default='email')
    
    # Audit Fields
    created_by = fields.Many2one('res.users', string='Created By', default=lambda self: self.env.user, 
                                ondelete='set null')
    created_date = fields.Datetime(string='Created On', default=fields.Datetime.now)
    activated_date = fields.Datetime(string='Activated On')
    closed_date = fields.Datetime(string='Closed On')
    
    # Related Models
    transaction_ids = fields.One2many('core_banking.transaction', 'account_id', string='Transactions')
    standing_order_ids = fields.One2many('core_banking.standing.order', 'account_id', string='Standing Orders')
    
    _sql_constraints = [
        ('account_number_uniq', 'unique (account_number, company_id)', 'Account Number must be unique per company!'),
    ]
    
    @api.depends('balance', 'hold_amount', 'overdraft_limit')
    def _compute_available_balance(self):
        for account in self:
            if account.allow_overdraft:
                account.available_balance = account.balance + account.overdraft_limit - account.hold_amount
            else:
                account.available_balance = max(0, account.balance - account.hold_amount)
    
    @api.model
    def create(self, vals):
        if vals.get('account_number', 'New') == 'New':
            vals['account_number'] = self.env['ir.sequence'].next_by_code('core_banking.account') or 'New'
        return super(Account, self).create(vals)
    
    def action_activate(self):
        self.write({
            'state': 'active',
            'activated_date': fields.Datetime.now()
        })
    
    def action_close(self):
        if self.balance != 0:
            raise UserError(_('Cannot close account with non-zero balance'))
        self.write({
            'state': 'closed',
            'closed_date': fields.Datetime.now()
        })
    
    def action_freeze(self):
        self.write({'state': 'restricted'})
    
    def action_unfreeze(self):
        self.write({'state': 'active'})
    
    def action_mark_dormant(self):
        self.write({'state': 'dormant'})
    
    def deposit(self, amount, reference='', description=''):
        """Process a deposit transaction"""
        if amount <= 0:
            raise UserError(_('Deposit amount must be positive'))
            
        self.ensure_one()
        
        # Create transaction
        transaction = self.env['core_banking.transaction'].create({
            'account_id': self.id,
            'transaction_type': 'deposit',
            'amount': amount,
            'reference': reference,
            'description': description or f'Deposit: {reference}',
            'state': 'posted',
        })
        
        # Update account balance
        self.balance += amount
        self.last_transaction_date = fields.Datetime.now()
        
        return transaction
    
    def withdraw(self, amount, reference='', description=''):
        """Process a withdrawal transaction"""
        if amount <= 0:
            raise UserError(_('Withdrawal amount must be positive'))
            
        self.ensure_one()
        
        available = self.available_balance
        if amount > available:
            raise UserError(_('Insufficient available balance. Available: %s') % available)
        
        # Create transaction
        transaction = self.env['core_banking.transaction'].create({
            'account_id': self.id,
            'transaction_type': 'withdrawal',
            'amount': -amount,  # Negative for withdrawal
            'reference': reference,
            'description': description or f'Withdrawal: {reference}',
            'state': 'posted',
        })
        
        # Update account balance
        self.balance -= amount
        self.last_transaction_date = fields.Datetime.now()
        
        return transaction


class AccountType(models.Model):
    _name = 'core_banking.account.type'
    _description = 'Account Type'
    _order = 'sequence, name'
    
    name = fields.Char(string='Account Type', required=True, translate=True)
    code = fields.Char(string='Code', required=True)
    description = fields.Text(string='Description')
    sequence = fields.Integer(string='Sequence', default=10)
    sequence_id = fields.Many2one('ir.sequence', string='Numbering Sequence', ondelete='set null',
                                 help='Sequence used for automatic numbering of accounts of this type')
    is_deposit = fields.Boolean(string='Is Deposit Account', default=False)
    is_loan = fields.Boolean(string='Is Loan Account', default=False)
    interest_rate = fields.Float(string='Default Interest Rate (%)', digits=(4, 6))
    minimum_balance = fields.Float(string='Minimum Balance', default=0.0)
    requires_approval = fields.Boolean(string='Requires Approval', default=False)
    active = fields.Boolean(string='Active', default=True)
    
    _sql_constraints = [
        ('code_uniq', 'unique (code)', 'Account type code must be unique!'),
    ]


class StandingOrder(models.Model):
    _name = 'core_banking.standing.order'
    _description = 'Standing Order'
    _order = 'next_execution_date'
    
    name = fields.Char(string='Reference', required=True, readonly=True, default='New')
    source_account_id = fields.Many2one('core_banking.account', string='Source Account', required=True, 
                                      ondelete='restrict')
    destination_account_id = fields.Many2one('core_banking.account', string='Destination Account', 
                                           ondelete='restrict', required=True)
    beneficiary_name = fields.Char(string='Beneficiary Name')
    beneficiary_bank = fields.Char(string='Beneficiary Bank')
    beneficiary_account = fields.Char(string='Beneficiary Account')
    amount = fields.Monetary(string='Amount', required=True)
    currency_id = fields.Many2one('res.currency', related='source_account_id.currency_id', store=True)
    frequency = fields.Selection([
        ('daily', 'Daily'),
        ('weekly', 'Weekly'),
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('yearly', 'Yearly')
    ], string='Frequency', required=True, default='monthly')
    next_execution_date = fields.Date(string='Next Execution Date', required=True)
    end_date = fields.Date(string='End Date')
    reference = fields.Char(string='Payment Reference')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('expired', 'Expired'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='draft', tracking=True)
    
    # Audit Fields
    created_by = fields.Many2one('res.users', string='Created By', default=lambda self: self.env.user,
                               ondelete='set null')
    created_date = fields.Datetime(string='Created On', default=fields.Datetime.now)
    
    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('core_banking.standing.order') or 'New'
        return super(StandingOrder, self).create(vals)
    
    def action_activate(self):
        self.write({'state': 'active'})
    
    def action_cancel(self):
        self.write({'state': 'cancelled'})
    
    def _cron_process_standing_orders(self):
        """Process standing orders that are due for execution"""
        today = fields.Date.today()
        due_orders = self.search([
            ('state', '=', 'active'),
            ('next_execution_date', '<=', today),
            '|',
            ('end_date', '=', False),
            ('end_date', '>=', today)
        ])
        
        for order in due_orders:
            try:
                # Process the standing order
                order.account_id.withdraw(
                    order.amount,
                    reference=order.reference or f'SO-{order.name}',
                    description=f'Standing Order to {order.beneficiary_name or order.destination_account_id.display_name}'
                )
                
                # Schedule next execution
                order._schedule_next_execution()
                
            except Exception as e:
                # Log error and continue with next order
                _logger.error(f"Error processing standing order {order.name}: {str(e)}")
    
    def _schedule_next_execution(self):
        """Schedule the next execution date based on frequency"""
        self.ensure_one()
        if not self.next_execution_date:
            return
            
        delta = {
            'daily': 1,
            'weekly': 7,
            'monthly': 30,
            'quarterly': 90,
            'yearly': 365
        }.get(self.frequency, 30)
        
        self.next_execution_date = fields.Date.to_date(self.next_execution_date) + timedelta(days=delta)
