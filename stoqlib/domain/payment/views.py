# -*- Mode: Python; coding: utf-8 -*-
# vi:si:et:sw=4:sts=4:ts=4

##
## Copyright (C) 2007-2010 Async Open Source <http://www.async.com.br>
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
## Author(s): Stoq Team <stoq-devel@async.com.br>
##

import datetime

from kiwi.datatypes import converter

from stoqlib.database.orm import AND, OR, const
from stoqlib.database.orm import Alias, LEFTJOINOn, INNERJOINOn
from stoqlib.database.orm import Viewable, Field
from stoqlib.domain.account import BankAccount
from stoqlib.domain.payment.category import PaymentCategory
from stoqlib.domain.payment.comment import PaymentComment
from stoqlib.domain.payment.group import PaymentGroup
from stoqlib.domain.payment.method import (CheckData, PaymentMethod,
                                           CreditCardData)
from stoqlib.domain.payment.operation import get_payment_operation
from stoqlib.domain.payment.payment import Payment, PaymentChangeHistory
from stoqlib.domain.payment.renegotiation import PaymentRenegotiation
from stoqlib.domain.person import Person, CreditProvider
from stoqlib.domain.purchase import PurchaseOrder
from stoqlib.domain.sale import Sale
from stoqlib.lib.translation import stoqlib_gettext


_ = stoqlib_gettext


class _CommentsSummary(Viewable):
    columns = dict(
        id=PaymentComment.q.paymentID,
        comments_number=const.COUNT(PaymentComment.q.id),
    )


class BasePaymentView(Viewable):
    CommentsSummary = Alias(_CommentsSummary, '_comments')

    columns = dict(
        # Payment
        id=Payment.q.id,
        identifier=Payment.q.identifier,
        description=Payment.q.description,
        due_date=Payment.q.due_date,
        status=Payment.q.status,
        paid_date=Payment.q.paid_date,
        value=Payment.q.value,
        paid_value=Payment.q.paid_value,
        payment_number=Payment.q.payment_number,
        group_id=Payment.q.groupID,

        # PaymentGroup
        renegotiated_id=PaymentGroup.q.renegotiationID,

        # PaymentMethod
        method_name=PaymentMethod.q.method_name,
        method_id=PaymentMethod.q.id,

        # PaymentCategory
        color=PaymentCategory.q.color,
        category=PaymentCategory.q.name,

        # PaymentComment
        comments_number=Field('_comments', 'comments_number'),

        # Sale
        sale_id=Sale.q.id,

        # Purchase
        purchase_id=PurchaseOrder.q.id,
        purchase_status=PurchaseOrder.q.status,
    )

    PaymentGroup_Sale = Alias(PaymentGroup, 'payment_group_sale')
    PaymentGroup_Purchase = Alias(PaymentGroup, 'payment_group_purchase')

    _count_joins = [
        LEFTJOINOn(None, PaymentGroup,
                   PaymentGroup.q.id == Payment.q.groupID),
        LEFTJOINOn(None, PaymentCategory,
                   PaymentCategory.q.id == Payment.q.categoryID),
        INNERJOINOn(None, PaymentMethod,
                    Payment.q.methodID == PaymentMethod.q.id),

        # Purchase
        LEFTJOINOn(None, PaymentGroup_Purchase,
                   PaymentGroup_Purchase.q.id == Payment.q.groupID),
        LEFTJOINOn(None, PurchaseOrder,
                   PurchaseOrder.q.groupID == PaymentGroup_Purchase.q.id),

        # Sale
        LEFTJOINOn(None, PaymentGroup_Sale,
                   PaymentGroup_Sale.q.id == Payment.q.groupID),
        LEFTJOINOn(None, Sale,
                   Sale.q.groupID == PaymentGroup_Sale.q.id),
    ]

    joins = _count_joins + [
        LEFTJOINOn(None, CommentsSummary,
                   Field('_comments', 'id') == Payment.q.id),
        ]

    @classmethod
    def post_search_callback(cls, conn, sresults):
        # FIXME: Use storm api to create this query storm.expr.compile
        from stoqlib.database.orm import Select
        select = Select(['COUNT(*) as count',
                         'SUM(value) as sum'],
                        join=cls._count_joins,
                        clause=sresults.clause,
                        staticTables=sresults.tables)
        return conn.sqlrepr(select)

    def can_change_due_date(self):
        return self.status not in [Payment.STATUS_PAID,
                                   Payment.STATUS_CANCELLED]

    def can_cancel_payment(self):
        """Only  lonely payments and pending can be cancelled
        """
        if self.sale_id or self.purchase_id:
            return False

        return self.status == Payment.STATUS_PENDING

    def get_status_str(self):
        return Payment.statuses[self.status]

    def is_late(self):
        if self.status in [Payment.STATUS_PAID, Payment.STATUS_CANCELLED]:
            return False

        return (datetime.date.today() - self.due_date.date()).days > 0

    def get_days_late(self):
        if not self.is_late():
            return 0

        days_late = datetime.date.today() - self.due_date.date()
        if days_late.days < 0:
            return 0

        return days_late.days

    def is_paid(self):
        return self.status == Payment.STATUS_PAID

    @property
    def payment(self):
        return Payment.get(self.id, connection=self.get_connection())

    @property
    def group(self):
        return PaymentGroup.get(self.group_id, connection=self.get_connection())

    @property
    def purchase(self):
        if self.purchase_id:
            return PurchaseOrder.get(self.purchase_id, self.get_connection())

    @property
    def operation(self):
        method = PaymentMethod.get(self.method_id,
                                   connection=self.get_connection())
        return method.operation

    @property
    def sale(self):
        if self.sale_id:
            return Sale.get(self.sale_id, self.get_connection())

    @classmethod
    def select_pending(cls, due_date=None, connection=None):
        query = cls.q.status == Payment.STATUS_PENDING

        if due_date:
            if isinstance(due_date, tuple):
                date_query = AND(const.DATE(cls.q.due_date) >= due_date[0],
                                 const.DATE(cls.q.due_date) <= due_date[1])
            else:
                date_query = const.DATE(cls.q.due_date) == due_date

            query = AND(query, date_query)

        return cls.select(query, connection=connection)


class InPaymentView(BasePaymentView):
    columns = BasePaymentView.columns.copy()
    columns.update(dict(
        drawee=Person.q.name,
        person_id=Person.q.id,
        renegotiated_id=PaymentGroup.q.renegotiationID,
        renegotiation_id=PaymentRenegotiation.q.id,
        ))

    _count_joins = BasePaymentView._count_joins[:]
    _count_joins.append(
        LEFTJOINOn(None, Person,
                    PaymentGroup.q.payerID == Person.q.id))

    joins = BasePaymentView.joins[:]
    joins.extend([
        LEFTJOINOn(None, Person,
                    PaymentGroup.q.payerID == Person.q.id),
        LEFTJOINOn(None, PaymentRenegotiation,
                   PaymentRenegotiation.q.groupID == PaymentGroup.q.id),
    ])

    clause = (Payment.q.payment_type == Payment.TYPE_IN)

    @property
    def renegotiation(self):
        if self.renegotiation_id:
            return PaymentRenegotiation.get(self.renegotiation_id,
                                            connection=self.get_connection())

    @property
    def renegotiated(self):
        if self.renegotiated_id:
            return PaymentRenegotiation.get(self.renegotiated_id,
                                            connection=self.get_connection())

    def get_parent(self):
        return self.sale or self.renegotiation

    @classmethod
    def has_late_payments(cls, conn, person):
        """Checks if the provided person has unpaid payments that are overdue

        :param person: A :class:`person <stoqlib.domain.person.Person>` to
          check if has late payments
        :returns: True if the person has overdue payments. False otherwise
        """
        query = AND(cls.q.person_id == person.id,
                    cls.q.status == Payment.STATUS_PENDING,
                    cls.q.due_date < datetime.date.today())

        late_payments = cls.select(query, connection=conn)
        if late_payments.any():
            return True

        return False


class OutPaymentView(BasePaymentView):
    columns = BasePaymentView.columns.copy()
    columns.update(dict(
        supplier_name=Person.q.name,
    ))

    _count_joins = BasePaymentView._count_joins[:]
    _count_joins.append(
        LEFTJOINOn(None, Person,
                   BasePaymentView.PaymentGroup_Sale.q.recipientID == Person.q.id))

    joins = BasePaymentView.joins[:]
    joins.extend([
        LEFTJOINOn(None, Person,
                   Person.q.id == BasePaymentView.PaymentGroup_Sale.q.recipientID),
    ])

    clause = (Payment.q.payment_type == Payment.TYPE_OUT)


class CardPaymentView(Viewable):
    """A view for credit providers."""
    _DraweePerson = Alias(Person, "drawee_person")
    _ProviderPerson = Alias(Person, "provider_person")

    columns = dict(
        id=Payment.q.id,
        identifier=Payment.q.identifier,
        description=Payment.q.description,
        drawee_name=_DraweePerson.q.name,
        provider_name=_ProviderPerson.q.name,
        due_date=Payment.q.due_date,
        paid_date=Payment.q.paid_date,
        sale_id=Sale.q.id,
        renegotiation_id=PaymentRenegotiation.q.id,
        status=Payment.q.status,
        value=Payment.q.value,
        fee=CreditCardData.q.fee,
        fee_calc=CreditCardData.q.fee_value, )

    joins = [
        INNERJOINOn(None, PaymentMethod,
                    PaymentMethod.q.id == Payment.q.methodID),
        INNERJOINOn(None, CreditCardData,
                    CreditCardData.q.paymentID == Payment.q.id),
        INNERJOINOn(None, CreditProvider,
              CreditProvider.q.id == CreditCardData.q.providerID),
        INNERJOINOn(None, _ProviderPerson,
            _ProviderPerson.q.id == CreditProvider.q.personID),
        LEFTJOINOn(None, PaymentGroup,
                    PaymentGroup.q.id == Payment.q.groupID),
        LEFTJOINOn(None, _DraweePerson,
                    _DraweePerson.q.id == PaymentGroup.q.payerID),
        LEFTJOINOn(None, Sale,
                   Sale.q.groupID == PaymentGroup.q.id),
        LEFTJOINOn(None, PaymentRenegotiation,
                   PaymentRenegotiation.q.groupID == PaymentGroup.q.id),
        ]

    def get_status_str(self):
        return Payment.statuses[self.status]

    @property
    def renegotiation(self):
        if self.renegotiation_id:
            return PaymentRenegotiation.get(self.renegotiation_id,
                                            connection=self.get_connection())

    @property
    def payment(self):
        return Payment.get(self.id, connection=self.get_connection())

    @classmethod
    def select_by_provider(cls, query, provider, having=None, connection=None):
        if provider:
            provider_query = CreditCardData.q.providerID == provider.id
            if query:
                query = AND(query, provider_query)
            else:
                query = provider_query

        return cls.select(query, having=having, connection=connection)


class _BillandCheckPaymentView(Viewable):
    """A base view for check and bill payments."""
    columns = dict(
        id=Payment.q.id,
        identifier=Payment.q.identifier,
        due_date=Payment.q.due_date,
        paid_date=Payment.q.paid_date,
        status=Payment.q.status,
        value=Payment.q.value,
        payment_number=Payment.q.payment_number,
        method_name=PaymentMethod.q.method_name,
        bank_number=BankAccount.q.bank_number,
        branch=BankAccount.q.bank_branch,
        account=BankAccount.q.bank_account,
    )

    joins = [
        LEFTJOINOn(None, CheckData, Payment.q.id == CheckData.q.paymentID),
        INNERJOINOn(None, PaymentMethod,
                    Payment.q.methodID == PaymentMethod.q.id),
        LEFTJOINOn(None, BankAccount,
                   BankAccount.q.id == CheckData.q.bank_accountID),
    ]

    clause = OR(PaymentMethod.q.method_name == 'bill',
                PaymentMethod.q.method_name == 'check')

    def get_status_str(self):
        return Payment.statuses[self.status]

    @property
    def payment(self):
        return Payment.get(self.id, connection=self.get_connection())

    @property
    def method_description(self):
        return get_payment_operation(self.method_name).description


class InCheckPaymentView(_BillandCheckPaymentView):
    """Stores information about bill and check receivings.
    """
    columns = _BillandCheckPaymentView.columns
    joins = _BillandCheckPaymentView.joins
    clause = AND(_BillandCheckPaymentView.clause,
                 Payment.q.payment_type == Payment.TYPE_IN)


class OutCheckPaymentView(_BillandCheckPaymentView):
    """Stores information about bill and check payments.
    """
    columns = _BillandCheckPaymentView.columns
    joins = _BillandCheckPaymentView.joins
    clause = AND(_BillandCheckPaymentView.clause,
                 Payment.q.payment_type == Payment.TYPE_OUT)


class PaymentChangeHistoryView(Viewable):
    """Holds information about changes to a payment.
    """

    columns = dict(
        id=PaymentChangeHistory.q.id,
        description=Payment.q.description,
        reason=PaymentChangeHistory.q.change_reason,
        change_date=PaymentChangeHistory.q.change_date,
        last_due_date=PaymentChangeHistory.q.last_due_date,
        new_due_date=PaymentChangeHistory.q.new_due_date,
        last_status=PaymentChangeHistory.q.last_status,
        new_status=PaymentChangeHistory.q.new_status,
    )

    joins = [
        INNERJOINOn(None, Payment,
                    Payment.q.id == PaymentChangeHistory.q.paymentID)
    ]

    @classmethod
    def select_by_group(cls, group, connection):
        return PaymentChangeHistoryView.select((Payment.q.groupID == group.id),
                                           connection=connection)

    @property
    def changed_field(self):
        """Return the name of the changed field."""

        if self.last_due_date:
            return _('Due Date')
        elif self.last_status:
            return _('Status')

    @property
    def from_value(self):
        if self.last_due_date:
            return converter.as_string(datetime.date, self.last_due_date)
        elif self.last_status:
            return Payment.statuses[self.last_status]

    @property
    def to_value(self):
        if self.new_due_date:
            return converter.as_string(datetime.date, self.new_due_date)
        elif self.new_status:
            return Payment.statuses[self.new_status]
