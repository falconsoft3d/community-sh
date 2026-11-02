"""
Copy business data from another Odoo (any version from 8) into an instance (Odoo 14+) over
XML-RPC: contacts, product categories, products and variants, sales, purchases, invoices and
their payments.

Each copied record gets an xmlid csh_migration.<model>_<source id> in the target, so running
the migration again skips what is already there and continues where it stopped. Reference
data (countries, currencies, units, taxes, payment terms) is matched by natural key, never copied.
"""
import logging
import xmlrpc.client

logger = logging.getLogger(__name__)

XMLID_MODULE = 'csh_migration'
BATCH = 200
STEPS = ['contacts', 'categories', 'products', 'sales', 'purchases', 'invoices', 'payments']
STEP_LABELS = {
    'contacts': 'Contactos', 'categories': 'Categorías', 'products': 'Productos y variantes',
    'sales': 'Ventas', 'purchases': 'Compras', 'invoices': 'Facturas de venta y compra',
    'payments': 'Pagos de venta y compra',
}
INVOICE_TYPES = ['out_invoice', 'out_refund', 'in_invoice', 'in_refund']
MIN_TARGET_VERSION = 14


class MigrationError(Exception):
    pass


class Odoo:
    """XML-RPC client for one database (works with Odoo 8 to 20)."""

    def __init__(self, url, db, login, password):
        self.url, self.db, self.password = url.rstrip('/'), db, password
        common = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/common', allow_none=True)
        try:
            self.version = int(str(common.version()['server_version']).split('.')[0].replace('saas~', ''))
            self.uid = common.authenticate(db, login, password, {})
        except (OSError, xmlrpc.client.Error) as e:
            raise MigrationError(f'No se pudo conectar con {self.url}: {e}')
        if not self.uid:
            raise MigrationError(f'Usuario o contraseña incorrectos en {self.url} (base de datos {db})')
        self.models = xmlrpc.client.ServerProxy(f'{self.url}/xmlrpc/2/object', allow_none=True)
        self._fields = {}

    def call(self, model, method, *args, **kwargs):
        return self.models.execute_kw(self.db, self.uid, self.password, model, method, list(args), kwargs)

    def has_model(self, model):
        return bool(self.call('ir.model', 'search', [('model', '=', model)], limit=1))

    def fields(self, model):
        if model not in self._fields:
            self._fields[model] = self.call(model, 'fields_get', attributes=['type', 'relation', 'store'])
        return self._fields[model]

    def search_read(self, model, domain, fields, order='id'):
        """Every matching record, archived ones included, in batches."""
        available = [f for f in fields if f in self.fields(model)]
        offset, records = 0, []
        while True:
            batch = self.call(model, 'search_read', domain, fields=available, order=order, offset=offset,
                              limit=BATCH, context={'active_test': False})
            records += batch
            if len(batch) < BATCH:
                return records
            offset += BATCH


def m2o_id(value):
    """Id of a many2one as search_read returns it ([id, name] or False)."""
    return value[0] if isinstance(value, (list, tuple)) and value else (value or False)


class Migration:
    def __init__(self, source, target, log=None):
        self.source, self.target = source, target
        self.maps = {}  # target model -> {source id: target id}
        self.lookups = {}
        self.log = log or (lambda text: None)
        self.counts = {}
        if target.version < MIN_TARGET_VERSION:
            raise MigrationError(f'La instancia destino debe ser Odoo {MIN_TARGET_VERSION} o posterior')

    # -- id maps kept as xmlids in the target ------------------------------------------------
    @staticmethod
    def xmlid_name(model, source_id):
        return f"{model.replace('.', '_')}_{source_id}"

    def id_map(self, model):
        if model not in self.maps:
            prefix = model.replace('.', '_') + '_'
            rows = self.target.search_read('ir.model.data', [('module', '=', XMLID_MODULE), ('model', '=', model)],
                                           ['name', 'res_id'])
            self.maps[model] = {int(r['name'][len(prefix):]): r['res_id'] for r in rows if r['name'].startswith(prefix)}
        return self.maps[model]

    def remember(self, model, source_id, target_id):
        self.target.call('ir.model.data', 'create', {
            'module': XMLID_MODULE, 'name': self.xmlid_name(model, source_id), 'model': model,
            'res_id': target_id, 'noupdate': True,
        })
        self.id_map(model)[source_id] = target_id

    def mapped(self, model, value):
        return self.id_map(model).get(m2o_id(value)) or False

    def copy(self, model, record, values, source_model=None):
        """Create the target record once; returns its id (existing or new)."""
        existing = self.id_map(model).get(record['id'])
        if existing:
            return existing
        values = {k: v for k, v in values.items() if k in self.target.fields(model)}
        try:
            target_id = self.target.call(model, 'create', values)
        except xmlrpc.client.Fault as e:
            self.log(f"  ⚠ {source_model or model} #{record['id']} no copiado: {e.faultString.strip().splitlines()[-1][:300]}")
            return False
        target_id = target_id[0] if isinstance(target_id, list) else target_id
        self.remember(model, record['id'], target_id)
        self.counts[model] = self.counts.get(model, 0) + 1
        return target_id

    # -- reference data matched by natural key -----------------------------------------------
    def lookup(self, model, source_value, key_fields, extra_domain=()):
        """Target id of the record matching the source many2one by key fields (cached)."""
        source_id = m2o_id(source_value)
        if not source_id:
            return False
        cache = self.lookups.setdefault(model, {})
        if source_id not in cache:
            source_model = self.source_model(model)
            found = self.source.search_read(source_model, [('id', '=', source_id)], key_fields)
            target_id = False
            if found:
                domain = [(f, '=', m2o_id(found[0][f]) if isinstance(found[0][f], list) else found[0][f])
                          for f in key_fields if f in self.target.fields(model) and found[0].get(f) not in (False, None)]
                if domain:
                    ids = self.target.call(model, 'search', domain + list(extra_domain), limit=1,
                                           context={'active_test': False})
                    target_id = ids[0] if ids else False
            cache[source_id] = target_id
        return cache[source_id]

    def source_model(self, model):
        if model == 'uom.uom' and not self.source.has_model('uom.uom'):
            return 'product.uom'  # Odoo 8-11
        return model

    def country(self, value):
        return self.lookup('res.country', value, ['code'])

    def currency(self, value):
        return self.lookup('res.currency', value, ['name'])

    def uom(self, value):
        return self.lookup('uom.uom', value, ['name'])

    def taxes(self, values, use):
        return [(6, 0, [tax for tax in (self.tax(tax_id, use) for tax_id in values or []) if tax])]

    def tax(self, source_id, use):
        """
        Same name, amount and use; else same amount, computation and use (charts rename their taxes
        between versions: "Tax 15%" in 16 is "15%" in 18). Missing taxes are reported once.
        """
        cache = self.lookups.setdefault('account.tax', {})
        if source_id in cache:
            return cache[source_id]
        keys = ['name', 'amount', 'amount_type', 'type_tax_use', 'price_include']
        source = self.source.search_read('account.tax', [('id', '=', source_id)], keys)
        target_id = False
        if source:
            source = source[0]
            candidates = self.target.search_read('account.tax', [('type_tax_use', '=', use), ('amount', '=', source['amount'])], keys)
            same_name = [t for t in candidates if t['name'] == source['name']]
            same_kind = [t for t in candidates if t.get('amount_type') == source.get('amount_type')
                         and bool(t.get('price_include')) == bool(source.get('price_include'))]
            match = (same_name or same_kind or [None])[0]
            target_id = match['id'] if match else False
            if not target_id:
                self.log(f"  ⚠ impuesto «{source['name']}» ({source['amount']}) sin equivalente en el destino: las líneas quedan sin él")
        cache[source_id] = target_id
        return target_id

    def payment_term(self, value):
        return self.lookup('account.payment.term', value, ['name'])

    # -- steps ---------------------------------------------------------------------------------
    def run(self, steps):
        from ..task_log import progress
        chosen = [step for step in STEPS if step in steps]
        for index, step in enumerate(chosen):
            progress(5 + 90 * index // max(len(chosen), 1), STEP_LABELS[step])
            self.log(f'▶ {STEP_LABELS[step]}')
            getattr(self, f'migrate_{step}')()
        self.log('Resumen: ' + (', '.join(f'{model}: {count}' for model, count in self.counts.items()) or 'nada nuevo que copiar'))
        return self.counts

    def migrate_contacts(self):
        if self.source.has_model('res.partner.category'):
            for tag in self.source.search_read('res.partner.category', [], ['name', 'color', 'parent_id'], order='parent_id desc, id'):
                self.copy('res.partner.category', tag, {'name': tag['name'], 'color': tag.get('color') or 0,
                                                        'parent_id': self.mapped('res.partner.category', tag.get('parent_id'))})
        fields = ['name', 'is_company', 'parent_id', 'type', 'street', 'street2', 'zip', 'city', 'state_id', 'country_id',
                  'email', 'phone', 'mobile', 'website', 'vat', 'ref', 'comment', 'function', 'active', 'category_id',
                  'customer', 'supplier', 'customer_rank', 'supplier_rank', 'lang']
        # Skip the users' and companies' own partners: the target already has its own
        user_partners = {m2o_id(u['partner_id']) for u in self.source.search_read('res.users', [], ['partner_id'])}
        user_partners |= {m2o_id(c['partner_id']) for c in self.source.search_read('res.company', [], ['partner_id'])}
        partners = [p for p in self.source.search_read('res.partner', [], fields, order='is_company desc, id')
                    if p['id'] not in user_partners]
        active_langs = {l['code'] for l in self.target.search_read('res.lang', [], ['code'])}
        for partner in partners:
            values = {k: partner.get(k) for k in ('name', 'is_company', 'street', 'street2', 'zip', 'city', 'email', 'phone',
                                                  'mobile', 'website', 'vat', 'ref', 'comment', 'function', 'active')}
            values = {k: v for k, v in values.items() if v not in (None,)}
            values['type'] = partner.get('type') if partner.get('type') in ('contact', 'invoice', 'delivery', 'other') else 'contact'
            values['country_id'] = self.country(partner.get('country_id'))
            if partner.get('state_id') and values['country_id']:
                values['state_id'] = self.lookup('res.country.state', partner['state_id'], ['code', 'name'],
                                                 [('country_id', '=', values['country_id'])])
            values['category_id'] = [(6, 0, [t for t in (self.mapped('res.partner.category', c) for c in partner.get('category_id') or []) if t])]
            values['customer_rank'] = 1 if partner.get('customer') or partner.get('customer_rank') else 0
            values['supplier_rank'] = 1 if partner.get('supplier') or partner.get('supplier_rank') else 0
            if partner.get('lang') in active_langs:
                values['lang'] = partner['lang']
            self.copy('res.partner', partner, values)
        # Second pass: links to the parent company, once every partner exists
        for partner in partners:
            parent = self.mapped('res.partner', partner.get('parent_id'))
            own = self.id_map('res.partner').get(partner['id'])
            if parent and own:
                self.target.call('res.partner', 'write', [own], {'parent_id': parent})

    def partner(self, value):
        """Target partner for a source one: copied, or the target's own for users/companies."""
        mapped = self.mapped('res.partner', value)
        if mapped:
            return mapped
        return self.lookup('res.partner', value, ['name'])

    def migrate_categories(self):
        categories = self.source.search_read('product.category', [], ['name', 'parent_id'], order='parent_id desc, id')
        existing = {c['name']: c['id'] for c in self.target.search_read('product.category', [('parent_id', '=', False)], ['name'])}
        for category in categories:
            if not category.get('parent_id') and category['name'] in existing and category['id'] not in self.id_map('product.category'):
                self.remember('product.category', category['id'], existing[category['name']])  # e.g. "All"
                continue
            self.copy('product.category', category, {'name': category['name']})
        for category in categories:
            parent, own = self.mapped('product.category', category.get('parent_id')), self.id_map('product.category').get(category['id'])
            if parent and own and parent != own:
                self.target.call('product.category', 'write', [own], {'parent_id': parent})

    def migrate_products(self):
        if 'product.category' not in self.maps or not self.id_map('product.category'):
            self.migrate_categories()
        # Attributes and values
        for attribute in self.source.search_read('product.attribute', [], ['name', 'create_variant', 'display_type']):
            values = {'name': attribute['name']}
            if attribute.get('create_variant') in ('always', 'dynamic', 'no_variant'):
                values['create_variant'] = attribute['create_variant']
            self.copy('product.attribute', attribute, values)
        for value in self.source.search_read('product.attribute.value', [], ['name', 'attribute_id']):
            attribute = self.mapped('product.attribute', value.get('attribute_id'))
            if attribute:
                self.copy('product.attribute.value', value, {'name': value['name'], 'attribute_id': attribute})

        storable_field = 'is_storable' in self.target.fields('product.template')
        template_fields = ['name', 'default_code', 'barcode', 'list_price', 'standard_price', 'type', 'categ_id', 'uom_id',
                           'uom_po_id', 'sale_ok', 'purchase_ok', 'description', 'description_sale', 'description_purchase',
                           'active', 'taxes_id', 'supplier_taxes_id', 'attribute_line_ids', 'weight', 'volume']
        templates = self.source.search_read('product.template', [], template_fields)
        lines_by_id = {}
        line_ids = [l for t in templates for l in t.get('attribute_line_ids') or []]
        if line_ids:
            for line in self.source.search_read('product.template.attribute.line', [('id', 'in', line_ids)], ['attribute_id', 'value_ids']) \
                    if self.source.has_model('product.template.attribute.line') else \
                    self.source.search_read('product.attribute.line', [('id', 'in', line_ids)], ['attribute_id', 'value_ids']):
                lines_by_id[line['id']] = line
        for template in templates:
            kind = template.get('type') or 'consu'
            values = {k: template.get(k) for k in ('name', 'default_code', 'list_price', 'sale_ok', 'purchase_ok', 'description',
                                                   'description_sale', 'description_purchase', 'active', 'weight', 'volume')}
            values = {k: v for k, v in values.items() if v is not None}
            if kind == 'product':  # storable: a type until 17, a flag from 18
                values.update({'type': 'consu', 'is_storable': True} if storable_field else {'type': 'product'})
            else:
                values['type'] = 'service' if kind == 'service' else 'consu'
            values['categ_id'] = self.mapped('product.category', template.get('categ_id')) or False
            uom = self.uom(template.get('uom_id'))
            if uom:
                values['uom_id'] = uom
                values['uom_po_id'] = self.uom(template.get('uom_po_id')) or uom
            values['taxes_id'] = self.taxes(template.get('taxes_id'), 'sale')
            values['supplier_taxes_id'] = self.taxes(template.get('supplier_taxes_id'), 'purchase')
            lines = []
            for line_id in template.get('attribute_line_ids') or []:
                line = lines_by_id.get(line_id)
                attribute = line and self.mapped('product.attribute', line.get('attribute_id'))
                value_ids = [v for v in (self.mapped('product.attribute.value', v) for v in (line or {}).get('value_ids') or []) if v]
                if attribute and value_ids:
                    lines.append((0, 0, {'attribute_id': attribute, 'value_ids': [(6, 0, value_ids)]}))
            if lines:
                values['attribute_line_ids'] = lines
            if template.get('barcode') and not lines:
                values['barcode'] = template['barcode']
            if not values['categ_id']:
                values.pop('categ_id')
            self.copy('product.template', template, values)
        self.migrate_variants()

    def migrate_variants(self):
        """Match each source variant with the one the target generated (same template, same values)."""
        if self.source.version >= 13:
            value_field = 'product_template_attribute_value_ids'
        else:
            value_field = 'attribute_value_ids'
        variants = self.source.search_read('product.product', [], ['product_tmpl_id', value_field, 'default_code', 'barcode',
                                                                   'standard_price', 'active'])
        source_ptav = {}
        if value_field == 'product_template_attribute_value_ids':
            ptav_ids = [v for p in variants for v in p.get(value_field) or []]
            if ptav_ids:
                for row in self.source.search_read('product.template.attribute.value', [('id', 'in', ptav_ids)], ['product_attribute_value_id']):
                    source_ptav[row['id']] = m2o_id(row['product_attribute_value_id'])
        target_ptav = {row['id']: m2o_id(row['product_attribute_value_id'])
                       for row in self.target.search_read('product.template.attribute.value', [], ['product_attribute_value_id'])}
        target_variants = {}
        for row in self.target.search_read('product.product', [], ['product_tmpl_id', 'product_template_attribute_value_ids']):
            key = (m2o_id(row['product_tmpl_id']), frozenset(target_ptav.get(v) for v in row['product_template_attribute_value_ids']))
            target_variants[key] = row['id']
        for variant in variants:
            if variant['id'] in self.id_map('product.product'):
                continue
            template = self.mapped('product.template', variant.get('product_tmpl_id'))
            if not template:
                continue
            raw = variant.get(value_field) or []
            values = [source_ptav.get(v) if source_ptav else v for v in raw]
            key = (template, frozenset(self.mapped('product.attribute.value', v) for v in values if v))
            target_id = target_variants.get(key)
            if not target_id:
                self.log(f"  ⚠ variante #{variant['id']} sin equivalente en el destino")
                continue
            self.remember('product.product', variant['id'], target_id)
            self.counts['product.product'] = self.counts.get('product.product', 0) + 1
            update = {k: variant[k] for k in ('default_code', 'barcode', 'standard_price', 'active') if variant.get(k) not in (None, False) or k == 'active'}
            try:
                self.target.call('product.product', 'write', [target_id], update)
            except xmlrpc.client.Fault as e:
                self.log(f"  ⚠ variante #{variant['id']}: {e.faultString.strip().splitlines()[-1][:200]}")

    def product(self, value):
        return self.mapped('product.product', value)

    def _ensure(self, *steps):
        for step in steps:
            model = {'contacts': 'res.partner', 'products': 'product.product'}[step]
            if not self.id_map(model):
                getattr(self, f'migrate_{step}')()

    def migrate_sales(self):
        if not self.target.has_model('sale.order'):
            return self.log('  La instancia destino no tiene Ventas instalado: se omite')
        self._ensure('contacts', 'products')
        orders = self.source.search_read('sale.order', [], ['name', 'partner_id', 'partner_invoice_id', 'partner_shipping_id',
                                                            'date_order', 'validity_date', 'client_order_ref', 'note', 'state',
                                                            'payment_term_id', 'order_line'])
        line_fields = ['product_id', 'name', 'product_uom_qty', 'price_unit', 'discount', 'tax_id', 'product_uom', 'display_type']
        for order in orders:
            if order['id'] in self.id_map('sale.order'):
                continue
            partner = self.partner(order.get('partner_id'))
            if not partner:
                self.log(f"  ⚠ pedido {order['name']}: cliente no encontrado")
                continue
            lines = []
            for line in self.source.search_read('sale.order.line', [('id', 'in', order.get('order_line') or [])], line_fields):
                values = {'name': line.get('name') or '/', 'product_uom_qty': line.get('product_uom_qty') or 0,
                          'price_unit': line.get('price_unit') or 0, 'discount': line.get('discount') or 0}
                if line.get('display_type'):
                    values = {'name': line['name'], 'display_type': line['display_type']}
                else:
                    values['product_id'] = self.product(line.get('product_id')) or False
                    values['tax_id'] = self.taxes(line.get('tax_id'), 'sale')
                    if not values['product_id']:
                        values.pop('product_id')
                lines.append((0, 0, values))
            values = {'name': order['name'], 'partner_id': partner, 'date_order': order.get('date_order'),
                      'client_order_ref': order.get('client_order_ref') or False, 'note': order.get('note') or False,
                      'order_line': lines,
                      'partner_invoice_id': self.partner(order.get('partner_invoice_id')) or partner,
                      'partner_shipping_id': self.partner(order.get('partner_shipping_id')) or partner}
            if order.get('validity_date'):
                values['validity_date'] = order['validity_date']
            term = self.payment_term(order.get('payment_term_id'))
            if term:
                values['payment_term_id'] = term
            target_id = self.copy('sale.order', order, values)
            if target_id and order.get('state') in ('sale', 'done'):
                self._action('sale.order', target_id, 'action_confirm', order['name'])
            elif target_id and order.get('state') == 'cancel':
                self._action('sale.order', target_id, 'action_cancel', order['name'])

    def migrate_purchases(self):
        if not self.target.has_model('purchase.order'):
            return self.log('  La instancia destino no tiene Compras instalado: se omite')
        self._ensure('contacts', 'products')
        orders = self.source.search_read('purchase.order', [], ['name', 'partner_id', 'date_order', 'partner_ref', 'notes',
                                                                'state', 'payment_term_id', 'order_line'])
        line_fields = ['product_id', 'name', 'product_qty', 'price_unit', 'taxes_id', 'date_planned', 'display_type']
        for order in orders:
            if order['id'] in self.id_map('purchase.order'):
                continue
            partner = self.partner(order.get('partner_id'))
            if not partner:
                self.log(f"  ⚠ compra {order['name']}: proveedor no encontrado")
                continue
            lines = []
            for line in self.source.search_read('purchase.order.line', [('id', 'in', order.get('order_line') or [])], line_fields):
                if line.get('display_type'):
                    lines.append((0, 0, {'name': line['name'], 'display_type': line['display_type'], 'product_qty': 0}))
                    continue
                values = {'name': line.get('name') or '/', 'product_qty': line.get('product_qty') or 0,
                          'price_unit': line.get('price_unit') or 0, 'taxes_id': self.taxes(line.get('taxes_id'), 'purchase'),
                          'date_planned': line.get('date_planned') or order.get('date_order')}
                product = self.product(line.get('product_id'))
                if product:
                    values['product_id'] = product
                lines.append((0, 0, values))
            values = {'name': order['name'], 'partner_id': partner, 'date_order': order.get('date_order'),
                      'partner_ref': order.get('partner_ref') or False, 'notes': order.get('notes') or False,
                      'order_line': lines}
            term = self.payment_term(order.get('payment_term_id'))
            if term:
                values['payment_term_id'] = term
            target_id = self.copy('purchase.order', order, values)
            if target_id and order.get('state') in ('purchase', 'done'):
                self._action('purchase.order', target_id, 'button_confirm', order['name'])
            elif target_id and order.get('state') == 'cancel':
                self._action('purchase.order', target_id, 'button_cancel', order['name'])

    def _action(self, model, record_id, method, label):
        try:
            self.target.call(model, method, [record_id])
        except xmlrpc.client.Fault as e:
            self.log(f"  ⚠ {label}: {method} falló: {e.faultString.strip().splitlines()[-1][:200]}")

    # Invoices: account.invoice until 12, account.move from 13; the target is always 14+
    def source_invoices(self):
        if self.source.version >= 13:
            fields = ['name', 'move_type', 'partner_id', 'invoice_date', 'invoice_date_due', 'ref', 'state', 'currency_id',
                      'amount_total', 'amount_residual', 'invoice_line_ids', 'invoice_payment_term_id', 'payment_reference']
            if 'move_type' not in self.source.fields('account.move'):
                fields[1] = 'type'  # Odoo 13
            rows = self.source.search_read('account.move', [(fields[1], 'in', INVOICE_TYPES)], fields)
            line_model, line_fields = 'account.move.line', ['product_id', 'name', 'quantity', 'price_unit', 'discount', 'tax_ids', 'display_type']
            for row in rows:
                row['_type'] = row.get('move_type') or row.get('type')
                row['_posted'] = row['state'] == 'posted'
                row['_number'] = row.get('name')
                row['_term'] = row.get('invoice_payment_term_id')
                row['_paid'] = (row.get('amount_total') or 0) - (row.get('amount_residual') or 0)
        else:
            fields = ['number', 'type', 'partner_id', 'date_invoice', 'date_due', 'reference', 'name', 'state', 'currency_id',
                      'amount_total', 'residual', 'invoice_line_ids', 'payment_term_id', 'payment_ids']
            rows = self.source.search_read('account.invoice', [('type', 'in', INVOICE_TYPES)], fields)
            line_model, line_fields = 'account.invoice.line', ['product_id', 'name', 'quantity', 'price_unit', 'discount',
                                                               'invoice_line_tax_ids', 'display_type']
            for row in rows:
                row['_type'] = row['type']
                row['_posted'] = row['state'] in ('open', 'paid', 'in_payment')
                row['_number'] = row.get('number')
                row['_term'] = row.get('payment_term_id')
                row['invoice_date'], row['invoice_date_due'], row['ref'] = row.get('date_invoice'), row.get('date_due'), row.get('reference') or row.get('name')
                row['_paid'] = (row.get('amount_total') or 0) - (row.get('residual') or 0) if row['_posted'] else 0
        return rows, line_model, line_fields

    def migrate_invoices(self):
        if not self.target.has_model('account.move'):
            return self.log('  La instancia destino no tiene Facturación instalado: se omite')
        self._ensure('contacts', 'products')
        invoices, line_model, line_fields = self.source_invoices()
        for invoice in invoices:
            if invoice['id'] in self.id_map('account.move') or invoice.get('state') == 'cancel':
                continue
            partner = self.partner(invoice.get('partner_id'))
            if not partner:
                self.log(f"  ⚠ factura {invoice.get('_number') or invoice['id']}: empresa no encontrada")
                continue
            use = 'sale' if invoice['_type'].startswith('out') else 'purchase'
            lines = []
            for line in self.source.search_read(line_model, [('id', 'in', invoice.get('invoice_line_ids') or [])], line_fields):
                if line.get('display_type') in ('line_section', 'line_note'):
                    lines.append((0, 0, {'name': line['name'], 'display_type': line['display_type']}))
                    continue
                if line.get('display_type') not in (None, False, 'product'):
                    continue  # tax/payment-term lines of Odoo 13+: the target computes its own
                values = {'name': line.get('name') or '/', 'quantity': line.get('quantity') or 0,
                          'price_unit': line.get('price_unit') or 0, 'discount': line.get('discount') or 0,
                          'tax_ids': self.taxes(line.get('tax_ids') or line.get('invoice_line_tax_ids'), use)}
                product = self.product(line.get('product_id'))
                if product:
                    values['product_id'] = product
                lines.append((0, 0, values))
            values = {'move_type': invoice['_type'], 'partner_id': partner, 'invoice_date': invoice.get('invoice_date') or False,
                      'ref': invoice.get('ref') or invoice.get('_number') or False,
                      'payment_reference': invoice.get('_number') or False, 'invoice_line_ids': lines}
            if invoice.get('invoice_date_due'):
                values['invoice_date_due'] = invoice['invoice_date_due']
            currency = self.currency(invoice.get('currency_id'))
            if currency:
                values['currency_id'] = currency
            term = self.payment_term(invoice.get('_term'))
            if term:
                values['invoice_payment_term_id'] = term
                values.pop('invoice_date_due', None)
            target_id = self.copy('account.move', invoice, values, source_model='factura')
            if target_id and invoice['_posted']:
                self._action('account.move', target_id, 'action_post', invoice.get('_number') or str(invoice['id']))

    def migrate_payments(self):
        """Register in the target what was paid of each migrated invoice (its own payment wizard)."""
        if not self.target.has_model('account.payment.register'):
            return self.log('  La instancia destino no tiene Facturación instalado: se omite')
        if not self.id_map('account.move'):
            self.migrate_invoices()
        invoices, _model, _fields = self.source_invoices()
        done = self.id_map('account.payment.register')  # source invoice id -> wizard id: payment already registered
        for invoice in invoices:
            target_move = self.id_map('account.move').get(invoice['id'])
            if not target_move or invoice['id'] in done or invoice.get('_paid', 0) <= 0.005:
                continue
            move = self.target.search_read('account.move', [('id', '=', target_move)], ['state', 'amount_residual'])
            if not move or move[0]['state'] != 'posted' or move[0]['amount_residual'] <= 0.005:
                continue
            context = {'active_model': 'account.move', 'active_ids': [target_move]}
            amount = min(invoice['_paid'], move[0]['amount_residual'])
            try:
                wizard = self.target.call('account.payment.register', 'create',
                                          {'amount': amount, 'payment_date': invoice.get('invoice_date') or False},
                                          context=context)
                wizard = wizard[0] if isinstance(wizard, list) else wizard
                self.target.call('account.payment.register', 'action_create_payments', [wizard], context=context)
            except xmlrpc.client.Fault as e:
                self.log(f"  ⚠ pago de {invoice.get('_number')}: {e.faultString.strip().splitlines()[-1][:200]}")
                continue
            self.remember('account.payment.register', invoice['id'], wizard)
            self.counts['pagos'] = self.counts.get('pagos', 0) + 1
