
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import calendar

class LoanPayment(models.Model):
    _name = 'core_banking.loan.payment'
    _description = 'Loan Payment'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'due_date desc'
    
    name = fields.Char(string='Payment Reference', required=True, readonly=True, default='New')
    loan_id = fields.Many2one('core_banking.loan', string='Loan', required=True, ondelete='cascade')
    payment_number = fields.Integer(string='Payment Number', required=True)
    
    # Payment Details
    due_date = fields.Date(string='Due Date', required=True)
    principal_amount = fields.Monetary(string='Principal Amount', required=True)
    interest_amount = fields.Monetary(string='Interest Amount', required=True)
    total_amount = fields.Monetary(string='Total Amount', compute='_compute_total_amount', store=True)
    currency_id = fields.Many2one('res.currency', related='loan_id.currency_id', store=True)
    
    # Payment Status
    paid_amount = fields.Monetary(string='Paid Amount', default=0.0)
    outstanding_amount = fields.Monetary(string='Outstanding Amount', compute='_compute_outstanding_amount', store=True)
    payment_date = fields.Date(string='Payment Date')
    state = fields.Selection([
        ('pending', 'Pending'),
        ('partial', 'Partially Paid'),
        ('paid', 'Paid'),
        ('overdue', 'Overdue'),
        ('defaulted', 'Defaulted')
    ], string='Status', default='pending', tracking=True)
    
    # Late Payment
    days_overdue = fields.Integer(string='Days Overdue', compute='_compute_days_overdue', store=True)
    penalty_amount = fields.Monetary(string='Penalty Amount', default=0.0)
    
    # Related
    company_id = fields.Many2one('res.company', related='loan_id.company_id', store=True)
    transaction_ids = fields.One2many('core_banking.transaction', 'loan_payment_id', string='Transactions')
    
    @api.depends('principal_amount', 'interest_amount', 'penalty_amount')
    def _compute_total_amount(self):
        for payment in self:
            payment.total_amount = payment.principal_amount + payment.interest_amount + payment.penalty_amount
    
    @api.depends('total_amount', 'paid_amount')
    def _compute_outstanding_amount(self):
        for payment in self:
            payment.outstanding_amount = payment.total_amount - payment.paid_amount
    
    @api.depends('due_date', 'state')
    def _compute_days_overdue(self):
        today = fields.Date.context_today(self)
        for payment in self:
            if payment.state in ['pending', 'partial'] and payment.due_date < today:
                payment.days_overdue = (today - payment.due_date).days
                if payment.days_overdue > 0:
                    payment.state = 'overdue'
            else:
                payment.days_overdue = 0
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('core_banking.loan.payment') or 'New'
        return super().create(vals_list)
    
    def action_record_payment(self, amount, payment_date=None):
        """Record a payment against this installment"""
        self.ensure_one()
        
        if amount <= 0:
            raise UserError(_('Payment amount must be positive'))
        
        if amount > self.outstanding_amount:
            raise UserError(_('Payment amount cannot exceed outstanding amount'))
        
        # Create transaction
        transaction = self.env['core_banking.transaction'].create({
            'transaction_type': 'payment',
            'account_id': self.loan_id.customer_id.account_ids[0].id if self.loan_id.customer_id.account_ids else False,
            'amount': -amount,  # Negative for payment
            'reference': f'Loan Payment: {self.name}',
            'description': f'Payment for loan {self.loan_id.name}',
            'loan_payment_id': self.id,
            'transaction_date': payment_date or fields.Datetime.now(),
            'value_date': payment_date or fields.Date.context_today(self),
            'state': 'posted',
        })
        
        # Update payment record
        self.paid_amount += amount
        if not self.payment_date:
            self.payment_date = payment_date or fields.Date.context_today(self)
        
        # Update status
        if self.paid_amount >= self.total_amount:
            self.state = 'paid'
        elif self.paid_amount > 0:
            self.state = 'partial'
        
        return transaction


class LoanGuarantor(models.Model):
    _name = 'core_banking.loan.guarantor'
    _description = 'Loan Guarantor'
    
    loan_id = fields.Many2one('core_banking.loan', string='Loan', required=True, ondelete='cascade')
    customer_id = fields.Many2one('core_banking.customer', string='Guarantor', required=True)
    guarantee_amount = fields.Monetary(string='Guarantee Amount', required=True)
    currency_id = fields.Many2one('res.currency', related='loan_id.currency_id', store=True)
    guarantee_type = fields.Selection([
        ('personal', 'Personal Guarantee'),
        ('collateral', 'Collateral'),
        ('cash', 'Cash Security')
    ], string='Guarantee Type', required=True, default='personal')
    
    # Document Details
    document_reference = fields.Char(string='Document Reference')
    collateral_description = fields.Text(string='Collateral Description')
    collateral_value = fields.Monetary(string='Collateral Value')
    
    state = fields.Selection([
        ('active', 'Active'),
        ('released', 'Released'),
        ('invoked', 'Invoked')
    ], string='Status', default='active')
