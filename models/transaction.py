from odoo import models, fields, api, _
from odoo.exceptions import ValidationError, UserError
from datetime import datetime
from dateutil.relativedelta import relativedelta

class Transaction(models.Model):
    _name = 'core_banking.transaction'
    _description = 'Bank Transaction'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'transaction_date desc, id desc'
    
    # Transaction Information
    name = fields.Char(string='Reference', required=True, readonly=True, default='New')
    transaction_type = fields.Selection([
        ('deposit', 'Deposit'),
        ('withdrawal', 'Withdrawal'),
        ('transfer', 'Transfer'),
        ('fee', 'Fee'),
        ('interest', 'Interest'),
        ('payment', 'Payment'),
        ('refund', 'Refund'),
        ('reversal', 'Reversal'),
        ('adjustment', 'Adjustment'),
        ('other', 'Other')
    ], string='Transaction Type', required=True, tracking=True)
    
    # Account Information
    account_id = fields.Many2one('core_banking.account', string='Account', required=True, 
                                ondelete='restrict', index=True, tracking=True)
    destination_account_id = fields.Many2one('core_banking.account', string='Destination Account',
                                           ondelete='restrict', index=True, tracking=True)
    
    # Amount Information
    amount = fields.Monetary(string='Amount', required=True, tracking=True)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True, 
                                 default=lambda self: self.env.company.currency_id,
                                 ondelete='restrict')
    exchange_rate = fields.Float(string='Exchange Rate', digits=(12, 6), default=1.0)
    amount_currency = fields.Monetary(string='Amount in Currency', compute='_compute_amount_currency',
                                    store=True, currency_field='currency_id')
    
    # Status Information
    state = fields.Selection([
        ('draft', 'Draft'),
        ('pending', 'Pending'),
        ('posted', 'Posted'),
        ('reconciled', 'Reconciled'),
        ('reversed', 'Reversed'),
        ('cancelled', 'Cancelled')
    ], string='Status', default='draft', tracking=True, index=True)
    
    # Transaction Details
    transaction_date = fields.Datetime(string='Transaction Date', default=fields.Datetime.now,
                                     required=True, index=True)
    value_date = fields.Date(string='Value Date', default=fields.Date.context_today,
                            required=True, index=True)
    reference = fields.Char(string='Reference', index=True)
    description = fields.Text(string='Description')
    notes = fields.Text(string='Internal Notes')
    
    # Related Fields
    company_id = fields.Many2one('res.company', string='Company', 
                                default=lambda self: self.env.company,
                                ondelete='restrict')
    branch_id = fields.Many2one('core_banking.branch', string='Branch', 
                              ondelete='restrict', tracking=True)
    journal_id = fields.Many2one('account.journal', string='Journal', 
                                ondelete='restrict', tracking=True)
    move_id = fields.Many2one('account.move', string='Journal Entry', 
                             ondelete='set null', copy=False)
    
    # Reversal Information
    reversed_entry_id = fields.Many2one('core_banking.transaction', string='Reversed Entry',
                                      ondelete='restrict', copy=False)
    reversal_id = fields.Many2one('core_banking.transaction', string='Reversal of',
                                 ondelete='set null', copy=False)
    
    # Audit Fields
    created_by = fields.Many2one('res.users', string='Created By', 
                               default=lambda self: self.env.user,
                               ondelete='set null', readonly=True)
    created_date = fields.Datetime(string='Created On', default=fields.Datetime.now, 
                                 readonly=True)
    posted_by = fields.Many2one('res.users', string='Posted By', 
                              ondelete='set null', readonly=True)
    posted_date = fields.Datetime(string='Posted On', readonly=True)
    
    # Computed Fields
    display_name = fields.Char(string='Display Name', compute='_compute_display_name', store=True)
    
    _sql_constraints = [
        ('amount_positive', 'CHECK(amount != 0)', 'Transaction amount cannot be zero!'),
    ]
    
    @api.depends('amount', 'exchange_rate')
    def _compute_amount_currency(self):
        for record in self:
            record.amount_currency = record.amount * record.exchange_rate
    
    @api.depends('name', 'transaction_type', 'amount', 'currency_id')
    def _compute_display_name(self):
        for record in self:
            record.display_name = f"{record.name or 'TX'}: {record.transaction_type.upper()} {record.currency_id.symbol}{abs(record.amount):,.2f}"
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('core_banking.transaction') or 'New'
        return super().create(vals_list)
    
    def write(self, vals):
        if 'state' in vals and vals['state'] == 'posted':
            vals['posted_by'] = self.env.user.id
            vals['posted_date'] = fields.Datetime.now()
        return super().write(vals)
    
    def action_post(self):
        """Post the transaction and update account balances"""
        for record in self.filtered(lambda t: t.state in ['draft', 'pending']):
            # Validate sufficient balance for debits
            if record.amount < 0:  # Debit transaction
                available_balance = record.account_id.available_balance
                if abs(record.amount) > available_balance:
                    raise UserError(_('Insufficient available balance. Available: %s, Required: %s') % 
                                  (available_balance, abs(record.amount)))
            
            # Update account balance using the amount as stored (positive/negative)
            record.account_id.balance += record.amount
            
            # For transfers, update destination account
            if record.transaction_type == 'transfer' and record.destination_account_id:
                record.destination_account_id.balance += abs(record.amount)
            
            # Update transaction state
            record.write({
                'state': 'posted',
                'posted_by': self.env.user.id,
                'posted_date': fields.Datetime.now()
            })
            
            # Update last transaction date on account
            current_time = fields.Datetime.now()
            record.account_id.last_transaction_date = current_time
            if record.destination_account_id:
                record.destination_account_id.last_transaction_date = current_time
    
    def action_reverse(self, date=None):
        """Reverse a posted transaction"""
        reversed_transactions = self.env['core_banking.transaction']
        
        for record in self.filtered(lambda t: t.state == 'posted' and not t.reversal_id):
            # Create reversal transaction
            reversal_vals = {
                'transaction_type': 'reversal',
                'account_id': record.account_id.id,
                'destination_account_id': record.destination_account_id.id,
                'amount': -record.amount,  # Reverse the amount
                'currency_id': record.currency_id.id,
                'exchange_rate': record.exchange_rate,
                'reference': f"REV-{record.reference or record.name}",
                'description': f"Reversal of {record.name}",
                'reversed_entry_id': record.id,
                'transaction_date': date or fields.Datetime.now(),
                'value_date': date or fields.Date.context_today(record),
                'state': 'posted',
            }
            
            reversal = self.create(reversal_vals)
            reversal.action_post()
            
            # Link reversal to original transaction
            record.reversal_id = reversal.id
            reversed_transactions |= reversal
            
            # Update original transaction state
            record.state = 'reversed'
        
        return reversed_transactions
    
    def action_cancel(self):
        """Cancel a draft or pending transaction"""
        for record in self.filtered(lambda t: t.state in ['draft', 'pending']):
            record.state = 'cancelled'
    
    def action_view_related_transactions(self):
        """View related transactions (reversals, transfers, etc.)"""
        self.ensure_one()
        related_ids = []
        
        if self.reversed_entry_id:
            related_ids.append(self.reversed_entry_id.id)
        if self.reversal_id:
            related_ids.append(self.reversal_id.id)
        if self.transaction_type == 'transfer' and self.destination_account_id:
            related_transfer = self.search([
                ('transaction_type', '=', 'transfer'),
                ('account_id', '=', self.destination_account_id.id),
                ('destination_account_id', '=', self.account_id.id),
                ('amount', '=', self.amount),
                ('transaction_date', '=', self.transaction_date)
            ], limit=1)
            if related_transfer:
                related_ids.append(related_transfer.id)
        
        return {
            'name': _('Related Transactions'),
            'view_mode': 'tree,form',
            'res_model': 'core_banking.transaction',
            'type': 'ir.actions.act_window',
            'domain': [('id', 'in', related_ids)],
            'context': {'create': False}
        }


class TransactionReconciliation(models.Model):
    _name = 'core_banking.transaction.reconciliation'
    _description = 'Transaction Reconciliation'
    
    name = fields.Char(string='Reference', required=True, default='New')
    transaction_ids = fields.Many2many('core_banking.transaction', string='Transactions',
                                     domain="[('state', '=', 'posted')]",
                                     context="{'default_state': 'posted'}")
    reconciliation_date = fields.Datetime(string='Reconciliation Date', default=fields.Datetime.now)
    reconciled_by = fields.Many2one('res.users', string='Reconciled By', 
                                  default=lambda self: self.env.user,
                                  ondelete='set null')
    notes = fields.Text(string='Notes')
    
    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('core_banking.transaction.reconciliation') or 'New'
        return super().create(vals_list)
    
    def action_reconcile(self):
        """Mark selected transactions as reconciled"""
        for record in self:
            record.transaction_ids.write({
                'state': 'reconciled',
                'reconciled_by': self.env.user.id,
                'reconciliation_date': fields.Datetime.now()
            })
