from odoo import models, fields, api, _

class CoreBanking(models.Model):
    _name = 'core.banking'
    _description = 'Core Banking System'
    
    name = fields.Char(string='Name', required=True, index=True)
    active = fields.Boolean(default=True, help='Set active to false to hide the record instead of deleting it')
    
    # Common fields for all banking models
    notes = fields.Text(string='Notes')
    state = fields.Selection([
        ('draft', 'Draft'),
        ('active', 'Active'),
        ('inactive', 'Inactive'),
        ('cancelled', 'Cancelled'),
    ], string='Status', default='draft', tracking=True)
    
    # Standard methods
    def action_activate(self):
        self.write({'state': 'active'})
        return True
        
    def action_deactivate(self):
        self.write({'state': 'inactive'})
        return True
        
    def action_cancel(self):
        self.write({'state': 'cancelled'})
        return True
        
    def action_draft(self):
        self.write({'state': 'draft'})
        return True
