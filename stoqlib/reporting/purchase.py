# -*- coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

##
## Copyright (C) 2006 Async Open Source <http://www.async.com.br>
## All rights reserved
##
## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU Lesser General Public License as published by
## the Free Software Foundation; either version 2 of the License, or
## (at your option) any later version.
##
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU Lesser General Public License for more details.
##
## You should have received a copy of the GNU Lesser General Public License
## along with this program; if not, write to the Free Software
## Foundation, Inc., or visit: http://www.gnu.org/.
##
##  Author(s):  Henrique Romano         <henrique@async.com.br>
##              Evandro Miquelito       <evandro@async.com.br>
##
##
""" Purchase report implementation """

from decimal import Decimal

from kiwi.datatypes import currency

from stoqlib.reporting.base.tables import (ObjectTableColumn as OTC,
                                           TableColumn as TC,
                                           HIGHLIGHT_NEVER)
from stoqlib.reporting.base.flowables import RIGHT, LEFT
from stoqlib.reporting.base.default_style import TABLE_LINE_BLANK
from stoqlib.lib.validators import get_formatted_price, format_quantity
from stoqlib.lib.defaults import ALL_ITEMS_INDEX, METHOD_MONEY
from stoqlib.lib.translation import stoqlib_gettext
from stoqlib.reporting.template import SearchResultsReport, BaseStoqReport
from stoqlib.domain.purchase import PurchaseOrder, PurchaseOrderView
from stoqlib.domain.interfaces import IPaymentGroup

_ = stoqlib_gettext

class PurchaseReport(SearchResultsReport):
    report_name = _("Purchase Order Report")
    main_object_name = _("orders")
    filter_format_string = _("with status <u>%s</u>")
    # This should be properly verified on SearchResultsReport. Waiting for
    # bug 2517
    obj_type = PurchaseOrderView

    def __init__(self, filename, purchases, status, *args, **kwargs):
        self.show_status_column = status == ALL_ITEMS_INDEX
        self._purchases = purchases
        SearchResultsReport.__init__(self, filename, purchases,
                                     PurchaseReport.report_name,
                                     landscape=1, *args, **kwargs)
        self._setup_table()

    def _get_columns(self):
        # XXX Bug #2430 will improve this part
        columns = [OTC(_("Number"), lambda obj: obj.order_number,
                       width=60, align=RIGHT),
                   OTC(_("Date"), lambda obj: obj.get_open_date_as_string(),
                       width=70),
                   OTC(_("Supplier"), lambda obj: obj.supplier_name,
                       width=250, truncate=True),
                   OTC(_("Qty Ordered"),
                       lambda obj: format_quantity(obj.ordered_quantity),
                       width=90, align=RIGHT),
                   OTC(_("Qty Received"),
                       lambda obj: format_quantity(obj.received_quantity),
                       width=120, align=RIGHT),
                   OTC(_("Total"),
                       lambda obj: get_formatted_price(obj.total),
                       width=85, align=RIGHT)]
        if self.show_status_column:
            columns.insert(-4, OTC(_("Status"),
                                   lambda obj: obj.get_status_str(), width=80))
        return columns

    def _setup_table(self):
        totals = [(purchase.ordered_quantity, purchase.received_quantity,
                   purchase.total)
                      for purchase in self._purchases]
        ordered, received , total = zip(*totals)
        total_ordered, total_received, total = (sum(ordered, Decimal('0')),
                                                sum(received, Decimal('0')),
                                                sum(total, currency(0)))
        summary_row = ["", "", _("Totals:"), format_quantity(total_ordered),
                       format_quantity(total_received),
                       get_formatted_price(total)]
        if self.show_status_column:
            summary_row.insert(0, "")
        self.add_object_table(self._purchases, self._get_columns(),
                              summary_row=summary_row)

class PurchaseOrderReport(BaseStoqReport):
    report_name = _("Purchase Order")

    def __init__(self, filename, order):
        self._order = order
        BaseStoqReport.__init__(self, filename, PurchaseOrderReport.report_name,
                                landscape=True)
        self._setup_order_details_table()
        self.add_blank_space(10)
        self._setup_items_table()

    def _get_items_table_columns(self):
        return [
            OTC(_("Item"),
                lambda obj: ("%s - %s" % (obj.sellable.code,
                                          obj.sellable.get_description())),
                expand=True, truncate=True),
            OTC(_("Quantity"), lambda obj: format_quantity(obj.quantity),
                width=80, align=RIGHT),
            # FIXME: This column should be virtual, waiting for bug #2764
            OTC("Unit", lambda obj: obj.sellable.get_unit_description(),
                virtual=False, width=60, align=LEFT),
            OTC(_("Cost"), lambda obj: get_formatted_price(obj.cost),
                width=70, align=RIGHT),
            OTC(_("Total"),
                lambda obj: get_formatted_price(obj.get_total()), width=70,
                align=RIGHT),
            ]

    def _add_items_table(self, items):
        total_cost = Decimal("0.0")
        total_value = Decimal("0.0")
        for item in items:
            total_value += item.quantity * item.cost
            total_cost += item.cost
        extra_row = ["", _("Totals:"), "", get_formatted_price(total_cost),
                     get_formatted_price(total_value)]
        self.add_object_table(items, self._get_items_table_columns(),
                              summary_row=extra_row)

    def _add_ordered_items_table(self, items):
        self.add_paragraph(_("Ordered Items"), style="Title")
        self._add_items_table(items)

    def _add_received_items_table(self, items):
        self.add_paragraph(_("Received Items"), style="Title")
        if not items:
            self.add_paragraph(_("There is no received items"))
            return
        self._add_items_table(items)

    def _get_freight_line(self):
        freight_line = []
        transporter = self._order.get_transporter_name() or _("Not Specified")
        freight_line.extend([_("Transporter:"), transporter, _("Freight:")])
        if self._order.freight_type == PurchaseOrder.FREIGHT_FOB:
            freight_line.append("%.2f %%" % self._order.freight)
        else:
            freight_line.append("CIF")
        return freight_line

    def _setup_payment_group_data(self):
        group = IPaymentGroup(self._order)
        if not group:
            return
        if group.default_method == METHOD_MONEY:
            msg = _("Paid in cash")
        else:
            method_name = group.get_default_payment_method_name()
            if group.installments_number > 1:
                msg = (_("Paid with %s in %d installments")
                       % (method_name, group.installments_number))
            else:
                msg = (_("Paid with %s in %d installments")
                       % (method_name, group.installments_number))
        self.add_paragraph(msg, style="Normal-Bold")

    def _setup_order_details_table(self):
        cols = [TC("", width=100), TC("", width=285, expand=True,
                                      truncate=True),
                TC("", width=50), TC("", width=285, expand=True,
                                     truncate=True)]
        data = [[_("Open Date:"), self._order.get_open_date_as_string(),
                 _("Status:"), self._order.get_status_str()],
                [_("Supplier:"), self._order.get_supplier_name(),
                 _("Branch:"), self._order.get_branch_name()],
                ]
        data.append(self._get_freight_line())
        self.add_column_table(data, cols, do_header=False,
                              highlight=HIGHLIGHT_NEVER, margins=2,
                              table_line=TABLE_LINE_BLANK, width=730)
        if self._order.expected_receival_date:
            expected_date = self._order.expected_receival_date.strftime("%x")
        else:
            expected_date = _("Not Specified")
        self.add_paragraph(_("Expected Receival Date: %s") % expected_date)
        self.add_blank_space(5)
        self._setup_payment_group_data()

    def _setup_items_table(self):
        items = self._order.get_items()
        received_items = [item for item in items if item.has_been_received()]
        # XXX: Stoqlib Reporting try to apply len() on the table data, but
        # Purchase's get_items returns a SelectResult instance (SQLObject)
        # that not supports the len operator.
        self._add_ordered_items_table(list(self._order.get_items()))
        self._add_received_items_table(received_items)

    #
    # BaseStoqReport hooks
    #

    def get_title(self):
        order_number = self._order.get_order_number_str()
        return _("Purchase Order #%s") % order_number
