from odoo import _, api, fields, models
from odoo.exceptions import UserError


class ForeignPurchaseRequisition(models.Model):
    _name = 'foreign.purchase.requisition'
    _description = 'Warehouse Requisition'
    _inherit = ['mail.thread', 'mail.activity.mixin']
    _order = 'id desc'

    name = fields.Char(default='New', copy=False, readonly=True, tracking=True)
    requester_id = fields.Many2one(
        'res.users',
        string='Requester',
        required=True,
        default=lambda self: self.env.user,
        tracking=True,
        domain=[('share', '=', False)],
    )
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    request_date = fields.Date(default=fields.Date.context_today, required=True)
    product_id = fields.Many2one('product.product', string='Product', tracking=True)
    specification = fields.Text(string='Specification', required=True)
    quantity = fields.Float(default=1.0, required=True)
    uom_id = fields.Many2one('uom.uom', string='Unit')
    proforma = fields.Binary(string='Supplier proforma', attachment=True, copy=False)
    proforma_name = fields.Char(copy=False)
    approval_request_id = fields.Many2one(
        'approval.request',
        string='Import Purchase Request',
        copy=False,
        readonly=True,
    )
    purchase_order_ids = fields.Many2many(
        'purchase.order',
        'foreign_requisition_purchase_rel',
        'requisition_id',
        'order_id',
        string='Purchase orders',
        copy=False,
    )
    state = fields.Selection(
        selection=[
            ('draft', 'Draft'),
            ('submitted', 'Submitted'),
            ('proforma', 'Proforma received'),
            ('requested', 'Purchase request created'),
            ('ordered', 'Purchase order opened'),
            ('cancel', 'Cancelled'),
        ],
        default='draft',
        required=True,
        tracking=True,
        copy=False,
    )

    @api.onchange('product_id')
    def _onchange_product_id(self):
        if self.product_id:
            self.uom_id = self.product_id.uom_id
            if not self.specification:
                self.specification = self.product_id.display_name

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('name', 'New') == 'New':
                vals['name'] = self.env['ir.sequence'].next_by_code('foreign.purchase.requisition') or 'New'
        return super().create(vals_list)

    def action_submit(self):
        for requisition in self:
            if requisition.quantity <= 0:
                raise UserError(_('Enter the quantity on %s.', requisition.name))
            requisition.state = 'submitted'
        return True

    def action_mark_proforma(self):
        for requisition in self:
            if requisition.state not in ('submitted', 'proforma'):
                raise UserError(_('Submit the requisition before recording the proforma.'))
            if not requisition.proforma:
                raise UserError(_('Attach the supplier proforma on %s first.', requisition.name))
            requisition.state = 'proforma'
        return True

    def action_create_import_request(self):
        self.ensure_one()
        if self.approval_request_id:
            return self.action_open_import_request()
        if self.state not in ('submitted', 'proforma'):
            raise UserError(_('Submit the warehouse requisition before raising the import purchase request.'))
        if not self.product_id:
            raise UserError(_('Choose the product before raising the import purchase request.'))
        if self.quantity <= 0:
            raise UserError(_('Enter the quantity before raising the import purchase request.'))
        category = self.env.ref('foreign_purchase.approval_category_import_purchase', raise_if_not_found=False)
        if not category:
            raise UserError(_('The Import Purchase Request approval category is missing.'))
        request = self.env['approval.request'].create({
            'name': self.name,
            'category_id': category.id,
            'request_owner_id': self.requester_id.id,
            'foreign_requisition_id': self.id,
            'reason': self.specification,
            'product_line_ids': [fields.Command.create({
                'product_id': self.product_id.id,
                'description': self.specification,
                'quantity': self.quantity,
            })],
        })
        self.write({
            'approval_request_id': request.id,
            'state': 'requested',
        })
        if self.proforma:
            self.env['ir.attachment'].create({
                'name': self.proforma_name or _('Proforma %s', self.name),
                'datas': self.proforma,
                'res_model': 'approval.request',
                'res_id': request.id,
            })
        return self.action_open_import_request()

    def action_open_import_request(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Import Purchase Request'),
            'res_model': 'approval.request',
            'view_mode': 'form',
            'res_id': self.approval_request_id.id,
        }

    def action_open_purchase_orders(self):
        self.ensure_one()
        action = {
            'type': 'ir.actions.act_window',
            'name': _('Purchase Orders'),
            'res_model': 'purchase.order',
            'domain': [('id', 'in', self.purchase_order_ids.ids)],
        }
        if len(self.purchase_order_ids) == 1:
            action.update({'view_mode': 'form', 'res_id': self.purchase_order_ids.id})
        else:
            action['view_mode'] = 'list,form'
        return action

    def action_cancel(self):
        self.filtered(lambda item: item.state != 'ordered').write({'state': 'cancel'})

    def action_reset_draft(self):
        self.filtered(lambda item: item.state == 'cancel' and not item.approval_request_id).write({'state': 'draft'})


class ForeignPurchaseComparison(models.Model):
    _name = 'foreign.purchase.comparison'
    _description = 'Supplier Comparison Line'
    _order = 'id'

    order_id = fields.Many2one(
        'purchase.order',
        string='Import order',
        required=True,
        ondelete='cascade',
        index=True,
    )
    company_id = fields.Many2one(related='order_id.company_id', store=True)
    partner_id = fields.Many2one('res.partner', string='Supplier', required=True)
    currency_id = fields.Many2one('res.currency', string='Currency', required=True)
    amount_total = fields.Monetary(string='Total', currency_field='currency_id')
    incoterm_id = fields.Many2one('account.incoterms', string='Incoterm')
    source_order_id = fields.Many2one('purchase.order', string='RFQ', copy=False)
    selected = fields.Boolean(string='Chosen')
    note = fields.Char()
