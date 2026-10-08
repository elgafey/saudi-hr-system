import logging
from collections import defaultdict
from datetime import datetime, time, timedelta

import pytz

from odoo import api, fields, models, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class InventoryBalanceWizard(models.TransientModel):
    _name = 'inventory.balance.wizard'
    _description = 'Company-Wide Inventory Balance Report Wizard'

    date_from = fields.Date(
        string='Date From',
        required=True,
        default=lambda self: fields.Date.today().replace(day=1),
    )
    date_to = fields.Date(
        string='Date To',
        required=True,
        default=fields.Date.today,
    )
    company_id = fields.Many2one(
        'res.company',
        string='Company',
        required=True,
        default=lambda self: self.env.company,
    )
    categ_id = fields.Many2one(
        'product.category',
        string='Product Category',
    )
    product_id = fields.Many2one(
        'product.product',
        string='Product',
    )
    include_no_movement = fields.Boolean(
        string='Show Products with No Movement',
        default=False,
    )

    @api.constrains('date_from', 'date_to')
    def _check_dates(self):
        for rec in self:
            if rec.date_from and rec.date_to and rec.date_from > rec.date_to:
                raise ValidationError(_('Date From must be before Date To.'))

    def action_print_pdf(self):
        self.ensure_one()
        return self.env.ref(
            'custom_inventory_balance_report.action_report_inventory_balance'
        ).report_action(self)

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _user_filter_domain(self):
        domain = []
        if self.categ_id:
            domain.append(('categ_id', 'child_of', self.categ_id.id))
        if self.product_id:
            domain.append(('id', '=', self.product_id.id))
        return domain

    def _storable_product_domain(self):
        Product = self.env['product.product']
        if 'is_storable' in Product._fields:
            return [('is_storable', '=', True)]
        if 'type' in Product._fields:
            return [('type', '=', 'product')]
        return []

    def _get_product_domain(self):
        domain = self._storable_product_domain()
        domain += self._user_filter_domain()
        return domain

    def _utc_start(self, date_val):
        tz_name = self.env.user.tz or 'UTC'
        try:
            user_tz = pytz.timezone(tz_name)
        except Exception:
            user_tz = pytz.UTC
        local_dt = user_tz.localize(datetime.combine(date_val, time.min))
        return local_dt.astimezone(pytz.UTC).replace(tzinfo=None)

    def _internal_locations(self, company):
        return self.env['stock.location'].search([
            ('usage', '=', 'internal'),
            '|',
            ('company_id', '=', company.id),
            ('company_id', '=', False),
        ])

    def _qty_field_name(self):
        Move = self.env['stock.move']
        for fname in ('quantity', 'product_qty', 'product_uom_qty'):
            if fname in Move._fields:
                return fname
        return 'product_uom_qty'

    @staticmethod
    def _move_company_direction(move):
        src_internal = move.location_id.usage == 'internal'
        dst_internal = move.location_dest_id.usage == 'internal'
        if dst_internal and not src_internal:
            return 'in'
        if src_internal and not dst_internal:
            return 'out'
        return 'none'

    def _move_qty_in_product_uom(self, move, qty_field):
        qty = move[qty_field] or 0.0
        if (
            move.product_uom
            and move.product_id
            and move.product_uom != move.product_id.uom_id
        ):
            try:
                qty = move.product_uom._compute_quantity(
                    qty, move.product_id.uom_id
                )
            except Exception:
                pass
        return qty

    def _valuation_cost_source(self):
        Product = self.env['product.product']
        if 'standard_price' in Product._fields:
            return 'product.standard_price'
        return False

    def _product_cost(self, product, cost_source):
        if cost_source == 'product.standard_price':
            return product.standard_price or 0.0
        return 0.0

    # ------------------------------------------------------------------
    # Report data
    # ------------------------------------------------------------------

    @api.model
    def _empty_totals(self):
        return {
            'opening_qty': 0.0, 'opening_val': 0.0,
            'incoming_qty': 0.0, 'incoming_val': 0.0,
            'outgoing_qty': 0.0, 'outgoing_val': 0.0,
            'closing_qty': 0.0, 'closing_val': 0.0,
        }

    def _discover_activity_product_ids(self, internal_locations, dt_to_excl):
        move_domain = [
            ('state', '=', 'done'),
            ('date', '<', dt_to_excl),
            '|',
            ('location_id', 'in', internal_locations.ids),
            ('location_dest_id', 'in', internal_locations.ids),
        ]
        moves = self.env['stock.move'].search(move_domain)
        product_ids = set(moves.product_id.ids)

        if 'product_id' in self.env['stock.quant']._fields:
            quants = self.env['stock.quant'].search([
                ('location_id', 'in', internal_locations.ids),
                ('quantity', '!=', 0.0),
            ])
            product_ids.update(quants.product_id.ids)

        return moves, product_ids

    def _resolve_products(self, activity_product_ids):
        Product = self.env['product.product']
        filter_domain = self._user_filter_domain()

        if self.include_no_movement:
            domain = self._get_product_domain()
            products = Product.search(domain, order='name')
            if activity_product_ids:
                extra = Product.search(
                    [('id', 'in', list(activity_product_ids))] + filter_domain,
                    order='name',
                )
                products = products | extra
            return products

        if not activity_product_ids:
            return Product.browse([])
        return Product.search(
            [('id', 'in', list(activity_product_ids))] + filter_domain,
            order='name',
        )

    def _log_diagnostics(
        self,
        date_from,
        date_to,
        company,
        dt_from,
        dt_to_excl,
        all_moves,
        move_line_count,
        discovered_count,
        incoming_count,
        outgoing_count,
        internal_count,
        lines,
        cost_source,
        valuation_available,
    ):
        # ============================================================
        # TEMPORARY DIAGNOSTIC LOGGING — remove after issue is fixed
        # ============================================================
        _logger.info(
            "Inventory Balance Report DEBUG\n"
            "Date From: %s\n"
            "Date To: %s\n"
            "Date From (UTC): %s\n"
            "Date To (UTC, exclusive upper bound): %s\n"
            "Company: %s\n"
            "Done stock moves found: %s\n"
            "Stock move lines found: %s\n"
            "Products discovered: %s\n"
            "Incoming moves: %s\n"
            "Outgoing moves: %s\n"
            "Internal transfers: %s\n"
            "Final products: %s\n"
            "Valuation/cost source actually used: %s\n"
            "Valuation source available: %s",
            date_from,
            date_to,
            dt_from,
            dt_to_excl,
            company.display_name if company else False,
            len(all_moves),
            move_line_count,
            discovered_count,
            incoming_count,
            outgoing_count,
            internal_count,
            len(lines),
            cost_source or 'none',
            valuation_available,
        )
        if not valuation_available:
            _logger.warning(
                "Inventory Balance Report: no reliable valuation/cost source "
                "available in this Odoo 19 environment. All Value columns "
                "are 0.0. Quantity columns are still calculated from done "
                "stock moves."
            )
        if lines:
            sample = lines[0]
            expected_close = (
                sample['opening_qty']
                + sample['incoming_qty']
                - sample['outgoing_qty']
            )
            _logger.info(
                "Inventory Balance Report DEBUG sample product %s: "
                "Opening=%s Incoming=%s Outgoing=%s Closing=%s "
                "Opening+Incoming-Outgoing=%s",
                sample['product_name'],
                sample['opening_qty'],
                sample['incoming_qty'],
                sample['outgoing_qty'],
                sample['closing_qty'],
                expected_close,
            )
        # ============================================================
        # END TEMPORARY DIAGNOSTIC LOGGING
        # ============================================================

    def _get_report_data(self):
        self.ensure_one()
        company = self.company_id
        date_from = self.date_from
        date_to = self.date_to

        dt_from = self._utc_start(date_from)
        dt_to_excl = self._utc_start(date_to + timedelta(days=1))
        qty_field = self._qty_field_name()
        cost_source = self._valuation_cost_source()
        valuation_available = bool(cost_source)

        internal_locations = self._internal_locations(company)

        all_moves, activity_product_ids = self._discover_activity_product_ids(
            internal_locations, dt_to_excl
        )

        products = self._resolve_products(activity_product_ids)
        if not products:
            self._log_diagnostics(
                date_from, date_to, company, dt_from, dt_to_excl,
                all_moves, 0, 0, 0, 0, 0, [],
                cost_source, valuation_available,
            )
            return {'lines': [], 'totals': self._empty_totals()}

        product_id_set = set(products.ids)

        opening_moves = all_moves.filtered(
            lambda m: m.date < dt_from and m.product_id.id in product_id_set
        )
        period_moves = all_moves.filtered(
            lambda m: m.date >= dt_from and m.product_id.id in product_id_set
        )

        move_line_count = 0
        if all_moves:
            move_line_count = self.env['stock.move.line'].search_count([
                ('move_id', 'in', all_moves.ids),
            ])

        opening = defaultdict(lambda: {'qty': 0.0})
        period_in = defaultdict(lambda: {'qty': 0.0})
        period_out = defaultdict(lambda: {'qty': 0.0})

        for move in opening_moves:
            direction = self._move_company_direction(move)
            if direction == 'none':
                continue
            pid = move.product_id.id
            qty = self._move_qty_in_product_uom(move, qty_field)
            if direction == 'in':
                opening[pid]['qty'] += qty
            else:
                opening[pid]['qty'] -= qty

        incoming_count = 0
        outgoing_count = 0
        internal_count = 0

        for move in period_moves:
            direction = self._move_company_direction(move)
            src_internal = move.location_id.usage == 'internal'
            dst_internal = move.location_dest_id.usage == 'internal'
            pid = move.product_id.id
            qty = self._move_qty_in_product_uom(move, qty_field)

            if src_internal and dst_internal:
                internal_count += 1
            elif dst_internal and not src_internal:
                incoming_count += 1
            elif src_internal and not dst_internal:
                outgoing_count += 1

            if direction == 'in':
                period_in[pid]['qty'] += qty
            elif direction == 'out':
                period_out[pid]['qty'] += qty

        lines = []
        for product in products:
            pid = product.id
            open_qty = opening[pid]['qty']
            inc_qty = period_in[pid]['qty']
            out_qty = period_out[pid]['qty']
            close_qty = open_qty + inc_qty - out_qty

            cost = self._product_cost(product, cost_source)
            open_val = open_qty * cost
            inc_val = inc_qty * cost
            out_val = out_qty * cost
            close_val = close_qty * cost

            has_activity = any([
                open_qty, open_val, inc_qty, inc_val,
                out_qty, out_val, close_qty, close_val,
            ])
            if not has_activity and not self.include_no_movement:
                continue

            lines.append({
                'product': product,
                'product_name': product.display_name,
                'uom': product.uom_id.name or '',
                'opening_qty': open_qty,
                'opening_val': open_val,
                'incoming_qty': inc_qty,
                'incoming_val': inc_val,
                'outgoing_qty': out_qty,
                'outgoing_val': out_val,
                'closing_qty': close_qty,
                'closing_val': close_val,
            })

        totals = {
            'opening_qty': sum(l['opening_qty'] for l in lines),
            'opening_val': sum(l['opening_val'] for l in lines),
            'incoming_qty': sum(l['incoming_qty'] for l in lines),
            'incoming_val': sum(l['incoming_val'] for l in lines),
            'outgoing_qty': sum(l['outgoing_qty'] for l in lines),
            'outgoing_val': sum(l['outgoing_val'] for l in lines),
            'closing_qty': sum(l['closing_qty'] for l in lines),
            'closing_val': sum(l['closing_val'] for l in lines),
        }

        self._log_diagnostics(
            date_from,
            date_to,
            company,
            dt_from,
            dt_to_excl,
            all_moves,
            move_line_count,
            len(activity_product_ids),
            incoming_count,
            outgoing_count,
            internal_count,
            lines,
            cost_source,
            valuation_available,
        )

        return {'lines': lines, 'totals': totals}
