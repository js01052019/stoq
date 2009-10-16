# -*- Mode: Python; coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

##
## Copyright (C) 2009 Async Open Source <http://www.async.com.br>
## All rights reserved
##
## This program is free software; you can redistribute it and/or modify
## it under the terms of the GNU General Public License as published by
## the Free Software Foundation; either version 2 of the License, or
## (at your option) any later version.
##
## This program is distributed in the hope that it will be useful,
## but WITHOUT ANY WARRANTY; without even the implied warranty of
## MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
## GNU General Public License for more details.
##
## You should have received a copy of the GNU General Public License
## along with this program; if not, write to the Free Software
## Foundation, Inc., or visit: http://www.gnu.org/.
##
## Author(s):   George Y. Kussumoto      <george@async.com.br>
##

import os

from kiwi.log import Logger
from stoqlib.database.runtime import get_connection
from stoqlib.domain.events import SaleConfirmEvent
from stoqlib.gui.events import StartApplicationEvent
from stoqlib.lib.message import info
from stoqlib.lib.translation import stoqlib_gettext

from nfegenerator import NFeGenerator

_ = stoqlib_gettext
log = Logger("stoq-nfe-plugin")


class NFeUI(object):
    def __init__(self):
        self.conn = get_connection()

        StartApplicationEvent.connect(self._on_StartApplicationEvent)
        SaleConfirmEvent.connect(self._on_SaleConfirm)
        self._blocked_pos = False

    #
    # Private
    #

    def _get_save_location(self):
        stoq_dir = os.path.join(os.environ['HOME'], '.stoq')
        if not os.path.isdir(stoq_dir):
            os.mkdir(stoq_dir)
        nfe_dir = os.path.join(stoq_dir, 'generated_nfe')
        if not os.path.isdir(nfe_dir):
            os.mkdir(nfe_dir)

        return nfe_dir

    def _can_create_nfe(self, sale):
        # FIXME: certainly, there is more conditions to check before we create
        #        the nfe. Maybe the user should have a chance to fix the
        #        missing information before we create the nfe.
        return sale.client is not None

    def _create_nfe(self, sale, trans):
        if self._can_create_nfe(sale):
            generator = NFeGenerator(sale, trans)
            generator.generate()
            generator.save(location=self._get_save_location())

    def _disable_print_invoice(self, uimanager):
        # since the nfe plugin was enabled, the user must not be able to print
        # the regular fiscal invoice (replaced by the nfe).
        widget = uimanager.get_widget('/menubar/TillMenu/print_invoice')
        widget.hide()

    def _disable_invoice_configuration(self, uimanager):
        # since the nfe plugin was enabled, the user must not be able to edit
        # an invoice layout or configure a printer.
        base_ui = '/menubar/settings_menu/'
        invoice_layout = uimanager.get_widget(base_ui + 'invoices')
        invoice_layout.hide()
        invoice_printer = uimanager.get_widget(base_ui + 'invoice_printers')
        invoice_printer.hide()

    #
    # Events
    #

    def _on_StartApplicationEvent(self, appname, app):
        if appname == 'sales':
            self._disable_print_invoice(app.main_window.uimanager)
        if appname == 'admin':
            self._disable_invoice_configuration(app.main_window.uimanager)
        if appname == 'pos':
            info(_(u'POS can not be used within NF-e plugin.'))
        # Disable POS application.
        if not self._blocked_pos:
            runner = app.runner
            runner.block_application('pos')
            self._blocked_pos = True

    def _on_SaleConfirm(self, sale, trans):
        self._create_nfe(sale, trans)
