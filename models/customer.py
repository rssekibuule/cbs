from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from datetime import date, datetime

class Customer(models.Model):
    _name = 'core_banking.customer'
    _description = 'Banking Customer'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'name'

    # Basic Information
    name = fields.Char(string='Full Name', required=True, tracking=True)
    ref = fields.Char(string='Customer ID', readonly=True, copy=False, index=True, default='New')
    customer_type = fields.Selection([
        ('individual', 'Individual'),
        ('group', 'Group'),
        ('sme', 'SME'),
        ('corporate', 'Corporate')
    ], string='Customer Type', required=True, default='individual', tracking=True)
    
    # Contact Information
    email = fields.Char(string='Email', tracking=True)
    phone = fields.Char(string='Phone', tracking=True)
    mobile = fields.Char(string='Mobile', tracking=True)
    street = fields.Char(string='Street')
    street2 = fields.Char(string='Street2')
    city = fields.Char(string='City')
    state_id = fields.Many2one('res.country.state', string='State')
    zip = fields.Char(string='ZIP')
    country_id = fields.Many2one('res.country', string='Country')
    
    # KYC Information
    date_of_birth = fields.Date(string='Date of Birth')
    gender = fields.Selection([
        ('male', 'Male'),
        ('female', 'Female'),
        ('other', 'Other')
    ], string='Gender')
    nationality = fields.Many2one('res.country', string='Nationality')
    id_type = fields.Selection([
        ('national_id', 'National ID'),
        ('passport', 'Passport'),
        ('driving_license', 'Driving License')
    ], string='ID Type')
    id_number = fields.Char(string='ID Number')
    id_issue_date = fields.Date(string='ID Issue Date')
    id_expiry_date = fields.Date(string='ID Expiry Date')
    
    # Additional Information
    customer_segment_id = fields.Many2one('core_banking.customer.segment', string='Customer Segment', ondelete='set null')
    is_pep = fields.Boolean(string='Politically Exposed Person (PEP)')
    is_high_risk = fields.Boolean(string='High Risk Customer')
    notes = fields.Text(string='Internal Notes')
    
    # Status Information
    state = fields.Selection([
        ('draft', 'Draft'),
        ('verified', 'Verified'),
        ('active', 'Active'),
        ('suspended', 'Suspended'),
        ('closed', 'Closed')
    ], string='Status', default='draft', tracking=True)
    
    # Related Fields
    user_id = fields.Many2one('res.users', string='Related User', ondelete='set null')
    company_id = fields.Many2one('res.company', string='Company', default=lambda self: self.env.company, ondelete='restrict')
    branch_id = fields.Many2one('core_banking.branch', string='Branch', ondelete='set null')
    relationship_manager_id = fields.Many2one('res.users', string='Relationship Manager', ondelete='set null')
    
    # Document Management
    document_ids = fields.One2many('core_banking.customer.document', 'customer_id', string='Documents')
    
    # Related Models
    account_ids = fields.One2many('core_banking.account', 'customer_id', string='Accounts')
    loan_ids = fields.One2many('core_banking.loan', 'customer_id', string='Loans')
    
    # Computed Fields
    age = fields.Integer(string='Age', compute='_compute_age', store=True)
    total_balance = fields.Monetary(string='Total Balance', compute='_compute_total_balance', store=True)
    currency_id = fields.Many2one('res.currency', related='company_id.currency_id', store=True)
    
    # Audit Fields
    created_by = fields.Many2one('res.users', string='Created By', default=lambda self: self.env.user, ondelete='set null')
    created_date = fields.Datetime(string='Created On', default=fields.Datetime.now)
    last_updated = fields.Datetime(string='Last Updated', default=fields.Datetime.now)
    
    @api.depends('date_of_birth')
    def _compute_age(self):
        today = date.today()
        for customer in self:
            if customer.date_of_birth:
                dob = fields.Date.from_string(customer.date_of_birth)
                customer.age = today.year - dob.year - ((today.month, today.day) < (dob.month, dob.day))
            else:
                customer.age = 0
    
    @api.depends('account_ids.balance')
    def _compute_total_balance(self):
        for customer in self:
            customer.total_balance = sum(account.balance for account in customer.account_ids)
    
    @api.model
    def create(self, vals):
        if vals.get('ref', 'New') == 'New':
            vals['ref'] = self.env['ir.sequence'].next_by_code('core_banking.customer') or 'New'
        return super(Customer, self).create(vals)
    
    def write(self, vals):
        vals['last_updated'] = fields.Datetime.now()
        return super(Customer, self).write(vals)
    
    def action_verify(self):
        self.write({'state': 'verified'})
    
    def action_activate(self):
        self.write({'state': 'active'})
    
    def action_suspend(self):
        self.write({'state': 'suspended'})
    
    def action_close(self):
        if any(account.balance != 0 for account in self.account_ids):
            raise UserError(_('Cannot close customer with non-zero account balances'))
        self.write({'state': 'closed'})
    
    def name_get(self):
        result = []
        for customer in self:
            name = f"{customer.ref} - {customer.name}" if customer.ref else customer.name
            result.append((customer.id, name))
        return result


class CustomerDocument(models.Model):
    _name = 'core_banking.customer.document'
    _description = 'Customer Document'
    _order = 'date_uploaded desc'
    
    name = fields.Char(string='Document Name', required=True)
    customer_id = fields.Many2one('core_banking.customer', string='Customer', ondelete='cascade')
    document_type = fields.Selection([
        ('id_proof', 'ID Proof'),
        ('address_proof', 'Address Proof'),
        ('photo', 'Photograph'),
        ('signature', 'Signature Specimen'),
        ('other', 'Other')
    ], string='Document Type', required=True)
    file = fields.Binary(string='File', required=True)
    file_name = fields.Char(string='File Name')
    date_uploaded = fields.Datetime(string='Uploaded On', default=fields.Datetime.now)
    uploaded_by = fields.Many2one('res.users', string='Uploaded By', default=lambda self: self.env.user, ondelete='set null')
    notes = fields.Text(string='Notes')
    is_verified = fields.Boolean(string='Verified', default=False)
    verified_by = fields.Many2one('res.users', string='Verified By', ondelete='set null')
    verification_date = fields.Datetime(string='Verification Date')
    expiry_date = fields.Date(string='Expiry Date')


class CustomerSegment(models.Model):
    _name = 'core_banking.customer.segment'
    _description = 'Customer Segment'
    
    name = fields.Char(string='Segment Name', required=True)
    code = fields.Char(string='Code', required=True)
    description = fields.Text(string='Description')
    min_balance = fields.Float(string='Minimum Balance')
    max_balance = fields.Float(string='Maximum Balance')
    benefits = fields.Text(string='Benefits')
    active = fields.Boolean(string='Active', default=True)
    
    _sql_constraints = [
        ('code_uniq', 'unique (code)', 'Segment code must be unique!'),
    ]
