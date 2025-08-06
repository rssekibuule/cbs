
from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

class Branch(models.Model):
    _name = 'core_banking.branch'
    _description = 'Bank Branch'
    _order = 'name'
    
    name = fields.Char(string='Branch Name', required=True)
    code = fields.Char(string='Branch Code', required=True)
    address = fields.Text(string='Address')
    phone = fields.Char(string='Phone')
    email = fields.Char(string='Email')
    manager_id = fields.Many2one('res.users', string='Branch Manager', ondelete='set null')
    company_id = fields.Many2one('res.company', string='Company', 
                                default=lambda self: self.env.company, ondelete='restrict')
    active = fields.Boolean(string='Active', default=True)
    
    # Location fields
    city = fields.Char(string='City')
    state_id = fields.Many2one('res.country.state', string='State')
    country_id = fields.Many2one('res.country', string='Country')
    
    # Banking specific fields
    swift_code = fields.Char(string='SWIFT Code')
    sort_code = fields.Char(string='Sort Code')
    
    _sql_constraints = [
        ('code_uniq', 'unique (code, company_id)', 'Branch code must be unique per company!'),
    ]
    
    def name_get(self):
        result = []
        for branch in self:
            name = f"[{branch.code}] {branch.name}"
            result.append((branch.id, name))
        return result
