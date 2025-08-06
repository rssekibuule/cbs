
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
    
    # Related
    company_id = fields.Many2one('res.company', string='Company', 
                                default=lambda self: self.env.company)
    branch_id = fields.Many2one('core_banking.branch', string='Branch', required=True)
    
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
    
    @api.depends('principal_amount')  # Add payment dependencies when payment model exists  
    def _compute_total_paid(self):
        for loan in self:
            loan.total_paid = 0.0  # Simplified for now
    
    @api.model
    def create(self, vals):
        if vals.get('name', 'New') == 'New':
            vals['name'] = self.env['ir.sequence'].next_by_code('core_banking.loan') or 'New'
        return super(Loan, self).create(vals)
    
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
