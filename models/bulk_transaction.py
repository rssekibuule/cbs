
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
import csv
import base64
import io

class BulkTransaction(models.Model):
    _name = 'core_banking.bulk.transaction'
    _description = 'Bulk Transaction Processing'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'create_date desc'
    
    name = fields.Char(string='Batch Reference', required=True, readonly=True, default='New')
    transaction_type = fields.Selection([
        ('bulk_transfer', 'Bulk Transfer'),
        ('salary_payment', 'Salary Payment'),
        ('bulk_deposit', 'Bulk Deposit'),
        ('bulk_withdrawal', 'Bulk Withdrawal'),
    ], string='Transaction Type', required=True)
    
    # File Upload
    import_file = fields.Binary(string='Import File', help='CSV file with transaction details')
    import_filename = fields.Char(string='Filename')
    
    # Batch Information
    total_transactions = fields.Integer(string='Total Transactions', compute='_compute_batch_info', store=True)
    total_amount = fields.Monetary(string='Total Amount', compute='_compute_batch_info', store=True)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True,
                                 default=lambda self: self.env.company.currency_id)
    
    # Processing Status
    state = fields.Selection([
        ('draft', 'Draft'),
        ('validated', 'Validated'),
        ('processing', 'Processing'),
        ('completed', 'Completed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='draft', tracking=True)
    
    processed_count = fields.Integer(string='Processed Count', default=0)
    failed_count = fields.Integer(string='Failed Count', default=0)
    success_count = fields.Integer(string='Success Count', default=0)
    
    # Related
    company_id = fields.Many2one('res.company', string='Company', 
                                default=lambda self: self.env.company)
    branch_id = fields.Many2one('core_banking.branch', string='Branch', required=True)
    
    # Transactions
    transaction_ids = fields.One2many('core_banking.transaction', 'bulk_transaction_id', 
                                    string='Transactions')
    bulk_line_ids = fields.One2many('core_banking.bulk.transaction.line', 'bulk_transaction_id',
                                  string='Transaction Lines')
    
    # Processing Details
    processing_date = fields.Datetime(string='Processing Date')
    processed_by = fields.Many2one('res.users', string='Processed By')
    error_log = fields.Text(string='Error Log')
    
    @api.depends('bulk_line_ids.amount')
    def _compute_batch_info(self):
        for record in self:
            record.total_transactions = len(record.bulk_line_ids)
            record.total_amount = sum(record.bulk_line_ids.mapped('amount'))
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('core_banking.bulk.transaction') or 'New'
        return super().create(vals_list)
    
    def action_import_file(self):
        """Import transactions from CSV file"""
        self.ensure_one()
        
        if not self.import_file:
            raise UserError(_('Please upload a CSV file'))
        
        try:
            # Decode the file
            file_content = base64.b64decode(self.import_file)
            csv_data = file_content.decode('utf-8')
            
            # Parse CSV
            csv_reader = csv.DictReader(io.StringIO(csv_data))
            lines_to_create = []
            
            required_fields = ['account_number', 'amount', 'reference']
            if self.transaction_type == 'bulk_transfer':
                required_fields.append('destination_account')
            
            for row_num, row in enumerate(csv_reader, start=2):
                # Validate required fields
                missing_fields = [field for field in required_fields if not row.get(field)]
                if missing_fields:
                    raise UserError(_('Missing required fields in row %d: %s') % 
                                  (row_num, ', '.join(missing_fields)))
                
                # Find accounts
                account = self.env['core_banking.account'].search([
                    ('account_number', '=', row['account_number'])
                ], limit=1)
                
                if not account:
                    raise UserError(_('Account not found in row %d: %s') % (row_num, row['account_number']))
                
                destination_account = False
                if self.transaction_type == 'bulk_transfer':
                    destination_account = self.env['core_banking.account'].search([
                        ('account_number', '=', row['destination_account'])
                    ], limit=1)
                    
                    if not destination_account:
                        raise UserError(_('Destination account not found in row %d: %s') % 
                                      (row_num, row['destination_account']))
                
                lines_to_create.append({
                    'bulk_transaction_id': self.id,
                    'account_id': account.id,
                    'destination_account_id': destination_account.id if destination_account else False,
                    'amount': float(row['amount']),
                    'reference': row['reference'],
                    'description': row.get('description', ''),
                    'row_number': row_num,
                })
            
            # Create bulk transaction lines
            self.bulk_line_ids.unlink()  # Remove existing lines
            self.env['core_banking.bulk.transaction.line'].create(lines_to_create)
            
            self.state = 'validated'
            
        except Exception as e:
            raise UserError(_('Error processing file: %s') % str(e))
    
    def action_process_batch(self):
        """Process all transactions in the batch"""
        self.ensure_one()
        
        if self.state != 'validated':
            raise UserError(_('Batch must be validated before processing'))
        
        self.write({
            'state': 'processing',
            'processing_date': fields.Datetime.now(),
            'processed_by': self.env.user.id,
        })
        
        success_count = 0
        failed_count = 0
        error_messages = []
        
        for line in self.bulk_line_ids:
            try:
                # Create transaction based on type
                transaction_vals = {
                    'transaction_type': self._get_transaction_type(),
                    'account_id': line.account_id.id,
                    'destination_account_id': line.destination_account_id.id if line.destination_account_id else False,
                    'amount': line.amount if self.transaction_type != 'bulk_withdrawal' else -line.amount,
                    'currency_id': self.currency_id.id,
                    'reference': line.reference,
                    'description': line.description or f'Bulk {self.transaction_type}: {line.reference}',
                    'bulk_transaction_id': self.id,
                    'state': 'draft',
                }
                
                transaction = self.env['core_banking.transaction'].create(transaction_vals)
                transaction.action_post()
                
                line.state = 'processed'
                success_count += 1
                
            except Exception as e:
                line.write({
                    'state': 'failed',
                    'error_message': str(e)
                })
                failed_count += 1
                error_messages.append(f'Line {line.row_number}: {str(e)}')
        
        # Update batch status
        self.write({
            'success_count': success_count,
            'failed_count': failed_count,
            'processed_count': success_count + failed_count,
            'error_log': '\n'.join(error_messages) if error_messages else False,
            'state': 'completed' if failed_count == 0 else 'failed'
        })
    
    def _get_transaction_type(self):
        """Map bulk transaction type to individual transaction type"""
        mapping = {
            'bulk_transfer': 'transfer',
            'salary_payment': 'deposit',
            'bulk_deposit': 'deposit',
            'bulk_withdrawal': 'withdrawal',
        }
        return mapping.get(self.transaction_type, 'other')


class BulkTransactionLine(models.Model):
    _name = 'core_banking.bulk.transaction.line'
    _description = 'Bulk Transaction Line'
    
    bulk_transaction_id = fields.Many2one('core_banking.bulk.transaction', string='Bulk Transaction',
                                        ondelete='cascade', required=True)
    row_number = fields.Integer(string='Row Number')
    
    # Transaction Details
    account_id = fields.Many2one('core_banking.account', string='Account', required=True)
    destination_account_id = fields.Many2one('core_banking.account', string='Destination Account')
    amount = fields.Monetary(string='Amount', required=True)
    currency_id = fields.Many2one('res.currency', related='bulk_transaction_id.currency_id', store=True)
    reference = fields.Char(string='Reference', required=True)
    description = fields.Text(string='Description')
    
    # Processing Status
    state = fields.Selection([
        ('pending', 'Pending'),
        ('processed', 'Processed'),
        ('failed', 'Failed')
    ], string='Status', default='pending')
    error_message = fields.Text(string='Error Message')
    
    transaction_id = fields.Many2one('core_banking.transaction', string='Created Transaction',
                                   ondelete='set null', readonly=True)


class ScheduledTransaction(models.Model):
    _name = 'core_banking.scheduled.transaction'
    _description = 'Scheduled Transaction'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    
    name = fields.Char(string='Reference', required=True, readonly=True, default='New')
    transaction_type = fields.Selection([
        ('deposit', 'Deposit'),
        ('withdrawal', 'Withdrawal'),
        ('transfer', 'Transfer'),
        ('payment', 'Payment'),
    ], string='Transaction Type', required=True)
    
    # Account Information
    account_id = fields.Many2one('core_banking.account', string='Account', required=True)
    destination_account_id = fields.Many2one('core_banking.account', string='Destination Account')
    
    # Transaction Details
    amount = fields.Monetary(string='Amount', required=True)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True,
                                 default=lambda self: self.env.company.currency_id)
    reference = fields.Char(string='Reference')
    description = fields.Text(string='Description')
    
    # Scheduling
    scheduled_date = fields.Datetime(string='Scheduled Date', required=True)
    auto_process = fields.Boolean(string='Auto Process', default=True)
    
    # Status
    state = fields.Selection([
        ('scheduled', 'Scheduled'),
        ('processed', 'Processed'),
        ('failed', 'Failed'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='scheduled', tracking=True)
    
    # Processing
    processed_date = fields.Datetime(string='Processed Date')
    transaction_id = fields.Many2one('core_banking.transaction', string='Created Transaction',
                                   ondelete='set null')
    error_message = fields.Text(string='Error Message')
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('core_banking.scheduled.transaction') or 'New'
        return super().create(vals_list)
    
    def action_process_now(self):
        """Process scheduled transaction immediately"""
        self.ensure_one()
        
        if self.state != 'scheduled':
            raise UserError(_('Only scheduled transactions can be processed'))
        
        try:
            # Create the actual transaction
            transaction_vals = {
                'transaction_type': self.transaction_type,
                'account_id': self.account_id.id,
                'destination_account_id': self.destination_account_id.id if self.destination_account_id else False,
                'amount': self.amount if self.transaction_type != 'withdrawal' else -self.amount,
                'currency_id': self.currency_id.id,
                'reference': self.reference or self.name,
                'description': self.description or f'Scheduled {self.transaction_type}: {self.name}',
                'transaction_date': fields.Datetime.now(),
                'state': 'draft',
            }
            
            transaction = self.env['core_banking.transaction'].create(transaction_vals)
            transaction.action_post()
            
            self.write({
                'state': 'processed',
                'processed_date': fields.Datetime.now(),
                'transaction_id': transaction.id
            })
            
        except Exception as e:
            self.write({
                'state': 'failed',
                'error_message': str(e)
            })
            raise UserError(_('Failed to process transaction: %s') % str(e))
    
    @api.model
    def _cron_process_scheduled_transactions(self):
        """Cron job to process due scheduled transactions"""
        due_transactions = self.search([
            ('state', '=', 'scheduled'),
            ('auto_process', '=', True),
            ('scheduled_date', '<=', fields.Datetime.now())
        ])
        
        for transaction in due_transactions:
            try:
                transaction.action_process_now()
            except Exception as e:
                # Log error but continue processing other transactions
                transaction.write({
                    'state': 'failed',
                    'error_message': str(e)
                })
