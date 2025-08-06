
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from datetime import datetime, timedelta
from dateutil.relativedelta import relativedelta
import calendar

class FixedDeposit(models.Model):
    _name = 'core_banking.fixed.deposit'
    _description = 'Fixed Deposit'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name desc'
    
    name = fields.Char(string='FD Reference', required=True, readonly=True, default='New')
    customer_id = fields.Many2one('core_banking.customer', string='Customer', required=True, 
                                 ondelete='restrict', tracking=True)
    account_id = fields.Many2one('core_banking.account', string='Linked Account', required=True,
                               ondelete='restrict', tracking=True)
    
    # Deposit Details
    principal_amount = fields.Monetary(string='Principal Amount', required=True, tracking=True)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True,
                                 default=lambda self: self.env.company.currency_id)
    interest_rate = fields.Float(string='Interest Rate (% p.a.)', required=True, tracking=True)
    term_months = fields.Integer(string='Term (Months)', required=True, tracking=True)
    
    # Dates
    deposit_date = fields.Date(string='Deposit Date', default=fields.Date.context_today, required=True)
    maturity_date = fields.Date(string='Maturity Date', compute='_compute_maturity_date', store=True)
    
    # Interest Calculation
    interest_compounding = fields.Selection([
        ('simple', 'Simple Interest'),
        ('monthly', 'Monthly Compounding'),
        ('quarterly', 'Quarterly Compounding'),
        ('annual', 'Annual Compounding')
    ], string='Interest Compounding', default='quarterly', required=True)
    
    interest_payout = fields.Selection([
        ('maturity', 'At Maturity'),
        ('monthly', 'Monthly'),
        ('quarterly', 'Quarterly'),
        ('annual', 'Annual')
    ], string='Interest Payout', default='maturity', required=True)
    
    # Computed Fields
    maturity_amount = fields.Monetary(string='Maturity Amount', compute='_compute_maturity_amount', store=True)
    accrued_interest = fields.Monetary(string='Accrued Interest', compute='_compute_accrued_interest', store=True)
    current_value = fields.Monetary(string='Current Value', compute='_compute_current_value', store=True)
    
    # Status
    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('matured', 'Matured'),
        ('withdrawn', 'Withdrawn'),
        ('renewed', 'Renewed')
    ], string='Status', default='draft', tracking=True)
    
    # Early Withdrawal
    allow_early_withdrawal = fields.Boolean(string='Allow Early Withdrawal', default=True)
    early_withdrawal_penalty_rate = fields.Float(string='Early Withdrawal Penalty (%)', default=1.0)
    
    # Related
    company_id = fields.Many2one('res.company', string='Company', 
                                default=lambda self: self.env.company)
    branch_id = fields.Many2one('core_banking.branch', string='Branch', required=True)
    certificate_id = fields.Many2one('core_banking.deposit.certificate', string='Certificate')
    
    @api.depends('deposit_date', 'term_months')
    def _compute_maturity_date(self):
        for deposit in self:
            if deposit.deposit_date and deposit.term_months:
                deposit.maturity_date = deposit.deposit_date + relativedelta(months=deposit.term_months)
            else:
                deposit.maturity_date = False
    
    @api.depends('principal_amount', 'interest_rate', 'term_months', 'interest_compounding')
    def _compute_maturity_amount(self):
        for deposit in self:
            if deposit.principal_amount and deposit.interest_rate and deposit.term_months:
                principal = deposit.principal_amount
                rate = deposit.interest_rate / 100
                months = deposit.term_months
                
                if deposit.interest_compounding == 'simple':
                    interest = principal * rate * months / 12
                    deposit.maturity_amount = principal + interest
                else:
                    # Compound interest calculation
                    compounding_periods = {
                        'monthly': 12,
                        'quarterly': 4,
                        'annual': 1
                    }.get(deposit.interest_compounding, 4)
                    
                    years = months / 12
                    compound_rate = 1 + (rate / compounding_periods)
                    periods = compounding_periods * years
                    
                    deposit.maturity_amount = principal * (compound_rate ** periods)
            else:
                deposit.maturity_amount = 0.0
    
    @api.depends('principal_amount', 'interest_rate', 'deposit_date', 'interest_compounding')
    def _compute_accrued_interest(self):
        today = fields.Date.context_today(self)
        for deposit in self:
            if deposit.state == 'active' and deposit.deposit_date:
                days_elapsed = (today - deposit.deposit_date).days
                if days_elapsed > 0:
                    principal = deposit.principal_amount
                    annual_rate = deposit.interest_rate / 100
                    
                    if deposit.interest_compounding == 'simple':
                        deposit.accrued_interest = principal * annual_rate * days_elapsed / 365
                    else:
                        # Simplified daily compounding for accrued interest
                        daily_rate = annual_rate / 365
                        deposit.accrued_interest = principal * ((1 + daily_rate) ** days_elapsed - 1)
                else:
                    deposit.accrued_interest = 0.0
            else:
                deposit.accrued_interest = 0.0
    
    @api.depends('principal_amount', 'accrued_interest')
    def _compute_current_value(self):
        for deposit in self:
            deposit.current_value = deposit.principal_amount + deposit.accrued_interest
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('core_banking.fixed.deposit') or 'New'
        return super().create(vals_list)
    
    def action_activate(self):
        """Activate the fixed deposit"""
        self.write({'state': 'active'})
        self.generate_certificate()
    
    def action_mature(self):
        """Process maturity of fixed deposit"""
        self.ensure_one()
        if self.state != 'active':
            raise UserError(_('Only active deposits can be matured'))
        
        # Credit maturity amount to linked account
        if self.account_id:
            self.account_id.deposit(
                self.maturity_amount,
                reference=f'FD-MAT-{self.name}',
                description=f'Fixed Deposit Maturity: {self.name}'
            )
        
        self.write({'state': 'matured'})
    
    def action_withdraw_early(self, withdrawal_amount=None):
        """Process early withdrawal with penalty"""
        self.ensure_one()
        
        if not self.allow_early_withdrawal:
            raise UserError(_('Early withdrawal not allowed for this deposit'))
        
        if self.state != 'active':
            raise UserError(_('Only active deposits can be withdrawn'))
        
        amount = withdrawal_amount or self.current_value
        penalty = amount * self.early_withdrawal_penalty_rate / 100
        net_amount = amount - penalty
        
        # Credit net amount to linked account
        if self.account_id:
            self.account_id.deposit(
                net_amount,
                reference=f'FD-EARLY-{self.name}',
                description=f'Early FD Withdrawal: {self.name} (Penalty: {penalty})'
            )
        
        self.write({'state': 'withdrawn'})
        
        return {
            'gross_amount': amount,
            'penalty': penalty,
            'net_amount': net_amount
        }
    
    def generate_certificate(self):
        """Generate deposit certificate"""
        self.ensure_one()
        if not self.certificate_id:
            certificate = self.env['core_banking.deposit.certificate'].create({
                'deposit_id': self.id,
                'certificate_number': self.env['ir.sequence'].next_by_code('core_banking.deposit.certificate') or 'CERT-NEW',
                'issue_date': fields.Date.context_today(self),
            })
            self.certificate_id = certificate.id


class DepositCertificate(models.Model):
    _name = 'core_banking.deposit.certificate'
    _description = 'Deposit Certificate'
    
    certificate_number = fields.Char(string='Certificate Number', required=True)
    deposit_id = fields.Many2one('core_banking.fixed.deposit', string='Fixed Deposit', required=True)
    issue_date = fields.Date(string='Issue Date', required=True)
    issued_by = fields.Many2one('res.users', string='Issued By', default=lambda self: self.env.user)
    
    # Certificate Details (computed from deposit)
    customer_name = fields.Char(string='Customer Name', related='deposit_id.customer_id.name', store=True)
    principal_amount = fields.Monetary(string='Principal Amount', related='deposit_id.principal_amount', store=True)
    interest_rate = fields.Float(string='Interest Rate', related='deposit_id.interest_rate', store=True)
    maturity_date = fields.Date(string='Maturity Date', related='deposit_id.maturity_date', store=True)
    maturity_amount = fields.Monetary(string='Maturity Amount', related='deposit_id.maturity_amount', store=True)
    currency_id = fields.Many2one('res.currency', related='deposit_id.currency_id', store=True)


class TermDeposit(models.Model):
    _name = 'core_banking.term.deposit'
    _description = 'Term Deposit'
    _inherit = ['core_banking.fixed.deposit']
    
    # Additional features for term deposits
    auto_renewal = fields.Boolean(string='Auto Renewal', default=False)
    renewal_instructions = fields.Text(string='Renewal Instructions')
    nomination_details = fields.Text(string='Nomination Details')
    
    def action_renew(self):
        """Renew term deposit"""
        self.ensure_one()
        if self.state != 'matured':
            raise UserError(_('Only matured deposits can be renewed'))
        
        # Create new term deposit with maturity amount as principal
        new_deposit = self.copy({
            'name': 'New',
            'principal_amount': self.maturity_amount,
            'deposit_date': fields.Date.context_today(self),
            'state': 'draft'
        })
        
        self.write({'state': 'renewed'})
        
        return {
            'name': _('Renewed Term Deposit'),
            'view_mode': 'form',
            'res_model': 'core_banking.term.deposit',
            'res_id': new_deposit.id,
            'type': 'ir.actions.act_window',
        }
