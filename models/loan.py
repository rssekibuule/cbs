
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta

class Loan(models.Model):
    _name = 'core_banking.loan'
    _description = 'Bank Loan'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name desc'
    
    name = fields.Char(string='Loan Reference', required=True, readonly=True, default='New')
    customer_id = fields.Many2one('core_banking.customer', string='Customer', required=True, 
                                 ondelete='restrict', tracking=True)
    loan_type_id = fields.Many2one('core_banking.loan.type', string='Loan Type', required=True,
                                  ondelete='restrict', tracking=True)
    
    # Loan Details
    principal_amount = fields.Monetary(string='Principal Amount', required=True, tracking=True)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True,
                                 default=lambda self: self.env.company.currency_id)
    interest_rate = fields.Float(string='Interest Rate (%)', required=True, tracking=True)
    term_months = fields.Integer(string='Term (Months)', required=True, tracking=True)
    
    # Dates
    application_date = fields.Date(string='Application Date', default=fields.Date.context_today)
    approval_date = fields.Date(string='Approval Date')
    disbursement_date = fields.Date(string='Disbursement Date')
    maturity_date = fields.Date(string='Maturity Date', compute='_compute_maturity_date', store=True)
    
    # Status
    state = fields.Selection([
        ('draft', 'Draft'),
        ('submitted', 'Submitted'),
        ('approved', 'Approved'),
        ('rejected', 'Rejected'),
        ('disbursed', 'Disbursed'),
        ('closed', 'Closed'),
        ('defaulted', 'Defaulted')
    ], string='Status', default='draft', tracking=True)
    
    # Computed Fields
    outstanding_balance = fields.Monetary(string='Outstanding Balance', 
                                        compute='_compute_outstanding_balance', store=True)
    total_paid = fields.Monetary(string='Total Paid', compute='_compute_total_paid', store=True)
    
    # Payment Information
    payment_frequency = fields.Selection([
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('semi_annual', 'Semi-Annual'),
        ('annual', 'Annual')
    ], string='Payment Frequency', default='monthly', required=True)
    emi_amount = fields.Monetary(string='EMI Amount', compute='_compute_emi_amount', store=True)
    
    # Related
    company_id = fields.Many2one('res.company', string='Company', 
                                default=lambda self: self.env.company)
    branch_id = fields.Many2one('core_banking.branch', string='Branch', required=True)
    payment_ids = fields.One2many('core_banking.loan.payment', 'loan_id', string='Payment Schedule')
    guarantor_ids = fields.One2many('core_banking.loan.guarantor', 'loan_id', string='Guarantors')
    
    # Collections
    is_overdue = fields.Boolean(string='Is Overdue', compute='_compute_overdue_status', store=True)
    overdue_days = fields.Integer(string='Days Overdue', compute='_compute_overdue_status', store=True)
    overdue_amount = fields.Monetary(string='Overdue Amount', compute='_compute_overdue_status', store=True)
    
    @api.depends('disbursement_date', 'term_months')
    def _compute_maturity_date(self):
        for loan in self:
            if loan.disbursement_date and loan.term_months:
                loan.maturity_date = loan.disbursement_date + relativedelta(months=loan.term_months)
            else:
                loan.maturity_date = False
    
    @api.depends('principal_amount')  # Add payment dependencies when payment model exists
    def _compute_outstanding_balance(self):
        for loan in self:
            loan.outstanding_balance = loan.principal_amount  # Simplified for now
    
    @api.depends('principal_amount', 'interest_rate', 'term_months')
    def _compute_emi_amount(self):
        for loan in self:
            if loan.principal_amount and loan.interest_rate and loan.term_months:
                # EMI Calculation: P * r * (1+r)^n / ((1+r)^n - 1)
                principal = loan.principal_amount
                monthly_rate = loan.interest_rate / 100 / 12
                months = loan.term_months
                
                if monthly_rate > 0:
                    emi = principal * monthly_rate * ((1 + monthly_rate) ** months) / (((1 + monthly_rate) ** months) - 1)
                    loan.emi_amount = emi
                else:
                    loan.emi_amount = principal / months
            else:
                loan.emi_amount = 0.0
    
    @api.depends('payment_ids.paid_amount')
    def _compute_total_paid(self):
        for loan in self:
            loan.total_paid = sum(payment.paid_amount for payment in loan.payment_ids)
    
    @api.depends('payment_ids.state', 'payment_ids.due_date', 'payment_ids.outstanding_amount')
    def _compute_overdue_status(self):
        today = fields.Date.context_today(self)
        for loan in self:
            overdue_payments = loan.payment_ids.filtered(
                lambda p: p.state in ['pending', 'partial'] and p.due_date < today
            )
            loan.is_overdue = bool(overdue_payments)
            loan.overdue_days = max(overdue_payments.mapped('days_overdue') or [0])
            loan.overdue_amount = sum(overdue_payments.mapped('outstanding_amount'))
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('core_banking.loan') or 'New'
        return super().create(vals_list)
    
    def action_submit(self):
        self.write({'state': 'submitted'})
    
    def action_approve(self):
        self.write({
            'state': 'approved',
            'approval_date': fields.Date.context_today(self)
        })
    
    def action_reject(self):
        self.write({'state': 'rejected'})
    
    def action_disburse(self):
        self.write({
            'state': 'disbursed',
            'disbursement_date': fields.Date.context_today(self)
        })
        self.generate_payment_schedule()
    
    def generate_payment_schedule(self):
        """Generate payment schedule for the loan"""
        self.ensure_one()
        
        if self.payment_ids:
            raise UserError(_('Payment schedule already exists'))
        
        if not self.disbursement_date or not self.term_months or not self.emi_amount:
            raise UserError(_('Cannot generate schedule: missing disbursement date, term, or EMI amount'))
        
        # Calculate payment dates based on frequency
        frequency_months = {
            'monthly': 1,
            'quarterly': 3,
            'semi_annual': 6,
            'annual': 12
        }.get(self.payment_frequency, 1)
        
        payment_count = self.term_months // frequency_months
        payment_amount = self.emi_amount * frequency_months if self.payment_frequency != 'monthly' else self.emi_amount
        
        outstanding_principal = self.principal_amount
        monthly_interest_rate = self.interest_rate / 100 / 12
        
        payments = []
        for i in range(1, payment_count + 1):
            # Calculate due date
            due_date = self.disbursement_date + relativedelta(months=i * frequency_months)
            
            # Calculate interest on outstanding principal
            months_elapsed = frequency_months
            interest_amount = outstanding_principal * monthly_interest_rate * months_elapsed
            principal_amount = payment_amount - interest_amount
            
            # Ensure principal doesn't exceed outstanding
            if principal_amount > outstanding_principal:
                principal_amount = outstanding_principal
                payment_amount = principal_amount + interest_amount
            
            payments.append({
                'loan_id': self.id,
                'payment_number': i,
                'due_date': due_date,
                'principal_amount': principal_amount,
                'interest_amount': interest_amount,
                'state': 'pending'
            })
            
            outstanding_principal -= principal_amount
            if outstanding_principal <= 0:
                break
        
        # Create payment records
        self.env['core_banking.loan.payment'].create(payments)
    
    def action_mark_default(self):
        """Mark loan as defaulted"""
        self.write({'state': 'defaulted'})


class LoanType(models.Model):
    _name = 'core_banking.loan.type'
    _description = 'Loan Type'
    
    name = fields.Char(string='Loan Type', required=True)
    code = fields.Char(string='Code', required=True)
    description = fields.Text(string='Description')
    min_amount = fields.Monetary(string='Minimum Amount')
    max_amount = fields.Monetary(string='Maximum Amount')
    default_interest_rate = fields.Float(string='Default Interest Rate (%)')
    max_term_months = fields.Integer(string='Maximum Term (Months)')
    currency_id = fields.Many2one('res.currency', string='Currency',
                                 default=lambda self: self.env.company.currency_id)
    active = fields.Boolean(string='Active', default=True)
    
    _sql_constraints = [
        ('code_uniq', 'unique (code)', 'Loan type code must be unique!'),
    ]
