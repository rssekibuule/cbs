
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import hashlib
import secrets
import uuid

class DigitalBankingService(models.Model):
    _name = 'core_banking.digital.service'
    _description = 'Digital Banking Services'
    
    name = fields.Char(string='Service Name', required=True)
    service_type = fields.Selection([
        ('mobile_app', 'Mobile Application'),
        ('web_banking', 'Web Banking'),
        ('api_service', 'API Service'),
        ('ussd', 'USSD Service'),
        ('sms_banking', 'SMS Banking')
    ], string='Service Type', required=True)
    
    # Configuration
    is_active = fields.Boolean(string='Active', default=True)
    endpoint_url = fields.Char(string='Endpoint URL')
    api_version = fields.Char(string='API Version', default='v1')
    
    # Security
    require_authentication = fields.Boolean(string='Require Authentication', default=True)
    require_2fa = fields.Boolean(string='Require 2FA', default=False)
    session_timeout = fields.Integer(string='Session Timeout (minutes)', default=30)
    
    # Rate Limiting
    rate_limit_enabled = fields.Boolean(string='Enable Rate Limiting', default=True)
    requests_per_minute = fields.Integer(string='Requests per Minute', default=60)
    requests_per_hour = fields.Integer(string='Requests per Hour', default=1000)
    
    # Analytics
    total_requests = fields.Integer(string='Total Requests', default=0)
    successful_requests = fields.Integer(string='Successful Requests', default=0)
    failed_requests = fields.Integer(string='Failed Requests', default=0)
    last_access_date = fields.Datetime(string='Last Access')
    
    # Related
    api_key_ids = fields.One2many('core_banking.api.key', 'service_id', string='API Keys')


class APIKey(models.Model):
    _name = 'core_banking.api.key'
    _description = 'API Key Management'
    
    name = fields.Char(string='Key Name', required=True)
    service_id = fields.Many2one('core_banking.digital.service', string='Service', required=True)
    customer_id = fields.Many2one('core_banking.customer', string='Customer')
    
    # Key Details
    api_key = fields.Char(string='API Key', readonly=True)
    secret_key = fields.Char(string='Secret Key', readonly=True)
    
    # Permissions
    permissions = fields.Selection([
        ('read_only', 'Read Only'),
        ('read_write', 'Read/Write'),
        ('full_access', 'Full Access')
    ], string='Permissions', default='read_only', required=True)
    
    # Status
    is_active = fields.Boolean(string='Active', default=True)
    created_date = fields.Datetime(string='Created Date', default=fields.Datetime.now)
    last_used_date = fields.Datetime(string='Last Used')
    expiry_date = fields.Date(string='Expiry Date')
    
    # Usage Analytics
    total_requests = fields.Integer(string='Total Requests', default=0)
    successful_requests = fields.Integer(string='Successful Requests', default=0)
    failed_requests = fields.Integer(string='Failed Requests', default=0)
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            # Generate API key and secret
            vals['api_key'] = self._generate_api_key()
            vals['secret_key'] = self._generate_secret_key()
        return super().create(vals_list)
    
    def _generate_api_key(self):
        """Generate a unique API key"""
        return f"cbk_{uuid.uuid4().hex}"
    
    def _generate_secret_key(self):
        """Generate a secret key"""
        return secrets.token_urlsafe(32)
    
    def action_regenerate_keys(self):
        """Regenerate API key and secret"""
        self.ensure_one()
        self.write({
            'api_key': self._generate_api_key(),
            'secret_key': self._generate_secret_key(),
        })
    
    def action_deactivate(self):
        """Deactivate API key"""
        self.write({'is_active': False})


class MobileBankingSession(models.Model):
    _name = 'core_banking.mobile.session'
    _description = 'Mobile Banking Session'
    
    session_id = fields.Char(string='Session ID', required=True, index=True)
    customer_id = fields.Many2one('core_banking.customer', string='Customer', required=True)
    device_id = fields.Char(string='Device ID')
    device_type = fields.Selection([
        ('android', 'Android'),
        ('ios', 'iOS'),
        ('web', 'Web Browser'),
        ('other', 'Other')
    ], string='Device Type')
    
    # Session Details
    login_time = fields.Datetime(string='Login Time', default=fields.Datetime.now)
    last_activity = fields.Datetime(string='Last Activity', default=fields.Datetime.now)
    logout_time = fields.Datetime(string='Logout Time')
    
    # Security
    ip_address = fields.Char(string='IP Address')
    user_agent = fields.Text(string='User Agent')
    is_active = fields.Boolean(string='Active', default=True)
    
    # Authentication
    auth_method = fields.Selection([
        ('password', 'Password'),
        ('pin', 'PIN'),
        ('biometric', 'Biometric'),
        ('otp', 'OTP')
    ], string='Auth Method')
    
    two_factor_verified = fields.Boolean(string='2FA Verified', default=False)
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('session_id'):
                vals['session_id'] = str(uuid.uuid4())
        return super().create(vals_list)
    
    def action_logout(self):
        """Logout session"""
        self.write({
            'is_active': False,
            'logout_time': fields.Datetime.now()
        })
    
    @api.model
    def cleanup_expired_sessions(self):
        """Cleanup expired sessions"""
        timeout = fields.Datetime.now() - timedelta(hours=24)
        expired_sessions = self.search([
            ('is_active', '=', True),
            ('last_activity', '<', timeout)
        ])
        expired_sessions.action_logout()


class DigitalTransaction(models.Model):
    _name = 'core_banking.digital.transaction'
    _description = 'Digital Banking Transaction'
    _inherit = ['core_banking.transaction']
    
    # Digital Channel Information
    channel = fields.Selection([
        ('mobile_app', 'Mobile App'),
        ('web_banking', 'Web Banking'),
        ('api', 'API'),
        ('ussd', 'USSD'),
        ('sms', 'SMS')
    ], string='Channel')
    
    session_id = fields.Many2one('core_banking.mobile.session', string='Session')
    api_key_id = fields.Many2one('core_banking.api.key', string='API Key')
    device_id = fields.Char(string='Device ID')
    
    # Digital Verification
    otp_verified = fields.Boolean(string='OTP Verified', default=False)
    biometric_verified = fields.Boolean(string='Biometric Verified', default=False)
    digital_signature = fields.Text(string='Digital Signature')


class CustomerNotification(models.Model):
    _name = 'core_banking.customer.notification'
    _description = 'Customer Notification'
    
    customer_id = fields.Many2one('core_banking.customer', string='Customer', required=True)
    
    # Notification Details
    title = fields.Char(string='Title', required=True)
    message = fields.Text(string='Message', required=True)
    notification_type = fields.Selection([
        ('transaction_alert', 'Transaction Alert'),
        ('balance_alert', 'Balance Alert'),
        ('payment_due', 'Payment Due'),
        ('account_update', 'Account Update'),
        ('security_alert', 'Security Alert'),
        ('promotional', 'Promotional'),
        ('system_maintenance', 'System Maintenance')
    ], string='Type', required=True)
    
    # Delivery Channels
    send_email = fields.Boolean(string='Send Email', default=True)
    send_sms = fields.Boolean(string='Send SMS', default=False)
    send_push = fields.Boolean(string='Send Push Notification', default=True)
    
    # Status
    state = fields.Selection([
        ('draft', 'Draft'),
        ('sent', 'Sent'),
        ('delivered', 'Delivered'),
        ('failed', 'Failed')
    ], string='Status', default='draft')
    
    sent_date = fields.Datetime(string='Sent Date')
    delivered_date = fields.Datetime(string='Delivered Date')
    
    # Message Details
    email_subject = fields.Char(string='Email Subject')
    sms_content = fields.Text(string='SMS Content')
    push_content = fields.Text(string='Push Content')
    
    def action_send_notification(self):
        """Send notification via selected channels"""
        self.ensure_one()
        
        try:
            # Send email
            if self.send_email and self.customer_id.email:
                self._send_email()
            
            # Send SMS
            if self.send_sms and self.customer_id.mobile:
                self._send_sms()
            
            # Send push notification
            if self.send_push:
                self._send_push_notification()
            
            self.write({
                'state': 'sent',
                'sent_date': fields.Datetime.now()
            })
            
        except Exception as e:
            self.write({'state': 'failed'})
            raise UserError(_('Failed to send notification: %s') % str(e))
    
    def _send_email(self):
        """Send email notification"""
        # Implementation would integrate with email service
        pass
    
    def _send_sms(self):
        """Send SMS notification"""
        # Implementation would integrate with SMS gateway
        pass
    
    def _send_push_notification(self):
        """Send push notification"""
        # Implementation would integrate with push notification service
        pass


class QRCodePayment(models.Model):
    _name = 'core_banking.qr.payment'
    _description = 'QR Code Payment'
    
    name = fields.Char(string='QR Reference', required=True, readonly=True, default='New')
    
    # QR Code Details
    qr_code = fields.Text(string='QR Code Data', required=True)
    qr_code_image = fields.Binary(string='QR Code Image')
    
    # Payment Details
    merchant_id = fields.Many2one('core_banking.customer', string='Merchant', required=True)
    merchant_account_id = fields.Many2one('core_banking.account', string='Merchant Account', required=True)
    amount = fields.Monetary(string='Amount')
    currency_id = fields.Many2one('res.currency', string='Currency', required=True,
                                 default=lambda self: self.env.company.currency_id)
    
    # QR Type
    qr_type = fields.Selection([
        ('static', 'Static QR'),
        ('dynamic', 'Dynamic QR')
    ], string='QR Type', default='static', required=True)
    
    # Validity
    valid_from = fields.Datetime(string='Valid From', default=fields.Datetime.now)
    valid_until = fields.Datetime(string='Valid Until')
    max_uses = fields.Integer(string='Maximum Uses', default=0, help='0 = unlimited')
    current_uses = fields.Integer(string='Current Uses', default=0)
    
    # Status
    is_active = fields.Boolean(string='Active', default=True)
    
    # Related
    payment_ids = fields.One2many('core_banking.qr.payment.transaction', 'qr_payment_id', 
                                string='Payments')
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('core_banking.qr.payment') or 'New'
            
            # Generate QR code data if not provided
            if not vals.get('qr_code'):
                vals['qr_code'] = self._generate_qr_code_data(vals)
        
        return super().create(vals_list)
    
    def _generate_qr_code_data(self, vals):
        """Generate QR code data"""
        # Simple QR code format - in real implementation, this would follow
        # standard formats like EMV QR or local standards
        data = {
            'merchant_id': vals.get('merchant_id'),
            'account': vals.get('merchant_account_id'),
            'amount': vals.get('amount', 0),
            'reference': vals.get('name', 'QR-NEW')
        }
        return str(data)


class QRPaymentTransaction(models.Model):
    _name = 'core_banking.qr.payment.transaction'
    _description = 'QR Payment Transaction'
    
    qr_payment_id = fields.Many2one('core_banking.qr.payment', string='QR Payment', required=True)
    transaction_id = fields.Many2one('core_banking.transaction', string='Transaction', required=True)
    
    # Payer Details
    payer_account_id = fields.Many2one('core_banking.account', string='Payer Account', required=True)
    
    # Payment Details
    amount = fields.Monetary(string='Amount', required=True)
    currency_id = fields.Many2one('res.currency', related='qr_payment_id.currency_id')
    payment_date = fields.Datetime(string='Payment Date', default=fields.Datetime.now)
    
    # Status
    state = fields.Selection([
        ('pending', 'Pending'),
        ('completed', 'Completed'),
        ('failed', 'Failed')
    ], string='Status', default='pending')
    
    def action_process_payment(self):
        """Process QR code payment"""
        self.ensure_one()
        
        # Validate QR code
        if not self.qr_payment_id.is_active:
            raise UserError(_('QR code is not active'))
        
        if self.qr_payment_id.valid_until and fields.Datetime.now() > self.qr_payment_id.valid_until:
            raise UserError(_('QR code has expired'))
        
        if (self.qr_payment_id.max_uses > 0 and 
            self.qr_payment_id.current_uses >= self.qr_payment_id.max_uses):
            raise UserError(_('QR code usage limit exceeded'))
        
        # Create transfer transaction
        transaction = self.env['core_banking.transaction'].create({
            'transaction_type': 'transfer',
            'account_id': self.payer_account_id.id,
            'destination_account_id': self.qr_payment_id.merchant_account_id.id,
            'amount': -self.amount,  # Debit from payer
            'reference': f'QR-{self.qr_payment_id.name}',
            'description': f'QR Payment to {self.qr_payment_id.merchant_id.name}',
            'state': 'draft'
        })
        
        # Post transaction
        transaction.action_post()
        
        # Update QR payment usage
        self.qr_payment_id.current_uses += 1
        
        # Update transaction reference
        self.transaction_id = transaction.id
        self.state = 'completed'
