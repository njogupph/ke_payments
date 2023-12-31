# Copyright (c) 2023, Chris and contributors
# For license information, please see license.txt

import frappe, erpnext
from frappe import _
from frappe.utils import nowdate
from erpnext.accounts.party import get_party_account
from erpnext.accounts.utils import get_account_currency
from erpnext.accounts.doctype.journal_entry.journal_entry import (
    get_default_bank_cash_account,
)
from erpnext.setup.utils import get_exchange_rate
from erpnext.accounts.doctype.bank_account.bank_account import get_party_bank_account
from frappe.utils import getdate, get_datetime


def create_payment_entry(
    company,
    customer,
    amount,
    currency,
    mode_of_payment,
    reference_date=None,
    reference_no=None,
    posting_date=None,
    submit=0,
):
    # TODO : need to have a better way to handle currency
    date = nowdate() if not posting_date else posting_date
    party_type = "Customer"
    party_account = get_party_account(party_type, customer, company)
    party_account_currency = get_account_currency(party_account)
    if party_account_currency != currency:
        frappe.throw(
            _(
                "Currency is not correct, party account currency is {party_account_currency} and transaction currency is {currency}"
            ).format(party_account_currency=party_account_currency, currency=currency)
        )
    payment_type = "Receive"

    bank = get_bank_cash_account(company, mode_of_payment)
    company_currency = frappe.get_value("Company", company, "default_currency")
    conversion_rate = get_exchange_rate(currency, company_currency, date, "for_selling")
    paid_amount, received_amount = set_paid_amount_and_received_amount(
        party_account_currency, bank, amount, payment_type, None, conversion_rate
    )

    pe = frappe.new_doc("Payment Entry")
    pe.payment_type = payment_type
    pe.company = company
    pe.cost_center = erpnext.get_default_cost_center(company)
    pe.posting_date = date
    pe.mode_of_payment = mode_of_payment
    pe.party_type = party_type
    pe.party = customer

    pe.paid_from = party_account if payment_type == "Receive" else bank.account
    pe.paid_to = party_account if payment_type == "Pay" else bank.account
    pe.paid_from_account_currency = (
        party_account_currency if payment_type == "Receive" else bank.account_currency
    )
    pe.paid_to_account_currency = (
        party_account_currency if payment_type == "Pay" else bank.account_currency
    )
    pe.paid_amount = paid_amount
    pe.received_amount = received_amount
    pe.letter_head = frappe.get_value("Company", company, "default_letter_head")
    pe.reference_date = reference_date
    pe.reference_no = reference_no
    if pe.party_type in ["Customer", "Supplier"]:
        bank_account = get_party_bank_account(pe.party_type, pe.party)
        pe.set("bank_account", bank_account)
        pe.set_bank_account_data()

    pe.setup_party_account_field()
    pe.set_missing_values()

    if party_account and bank:
        pe.set_amounts()
    if submit:
        pe.docstatus = 1
    pe.insert(ignore_permissions=True)
    return pe


def get_bank_cash_account(company, mode_of_payment, bank_account=None):
    bank = get_default_bank_cash_account(
        company, "Bank", mode_of_payment=mode_of_payment, account=bank_account
    )

    if not bank:
        bank = get_default_bank_cash_account(
            company, "Cash", mode_of_payment=mode_of_payment, account=bank_account
        )

    return bank


def set_paid_amount_and_received_amount(
    party_account_currency,
    bank,
    outstanding_amount,
    payment_type,
    bank_amount,
    conversion_rate,
):
    paid_amount = received_amount = 0
    if party_account_currency == bank.account_currency:
        paid_amount = received_amount = abs(outstanding_amount)
    elif payment_type == "Receive":
        paid_amount = abs(outstanding_amount)
        if bank_amount:
            received_amount = bank_amount
        else:
            received_amount = paid_amount * conversion_rate

    else:
        received_amount = abs(outstanding_amount)
        if bank_amount:
            paid_amount = bank_amount
        else:
            # if party account currency and bank currency is different then populate paid amount as well
            paid_amount = received_amount * conversion_rate

    return paid_amount, received_amount


def reconcile_payment_entries(customer, company):
    # Get all Sales Invoices for the customer that are unpaid
    sales_invoices = frappe.get_all('Sales Invoice',
                                    filters={
                                        'customer': customer,
                                        'docstatus': 1,
                                        'outstanding_amount': ['>', 0]
                                    },
                                    fields=['name', 'posting_date', 'grand_total', 'outstanding_amount', 'currency']
                                    )

    # Get all unreconciled Payment Entries for the customer
    all_payments_entry = frappe.get_all("Payment Entry",
                                        filters={"party": customer, "docstatus": 1, "payment_type": "Receive"},
                                        fields=["name", "posting_date", "unallocated_amount", "paid_from_account_currency as currency"]
                                        )

    # Sort invoices based on the posting date in ascending order
    sorted_invoices = sorted(sales_invoices, key=lambda k: get_datetime(k['posting_date']))

    if len(all_payments_entry) > 0:
        for payment in all_payments_entry:
            paid_amount = payment.get("unallocated_amount")
            args = {
                "invoices": [],
                "payments": [],
            }
            for invoice in sorted_invoices:
                if paid_amount <= 0:
                    break  # if there's no amount left in the payment, stop processing invoices

                allocated_amount = min(invoice.get('outstanding_amount'), paid_amount)

                args["invoices"].append(
                    {
                        "invoice_type": "Sales Invoice",
                        "invoice_number": invoice.get("name"),
                        "invoice_date": invoice.get("posting_date"),
                        "amount": allocated_amount,
                        "outstanding_amount": invoice.get("outstanding_amount"),
                        "currency": invoice.get("currency"),
                        "exchange_rate": 0,
                    }
                )
                args["payments"].append(
                    {
                        "reference_type": "Payment Entry",
                        "reference_name": payment.get("name"),
                        "posting_date": payment.get("posting_date"),
                        "amount": allocated_amount,
                        "unallocated_amount": payment.get("unallocated_amount"),
                        "difference_amount": 0,
                        "currency": payment.get("currency"),
                        "exchange_rate": 0,
                    }
                )
                # Reduce the paid amount by the allocated amount
                paid_amount -= allocated_amount

            # Reconcile the invoices with the payment
            if args["invoices"] and args["payments"]:
                reconcile_doc = frappe.new_doc("Payment Reconciliation")
                reconcile_doc.party_type = "Customer"
                reconcile_doc.party = customer
                reconcile_doc.company = company
                reconcile_doc.receivable_payable_account = get_party_account("Customer", customer, company)
                reconcile_doc.get_unreconciled_entries()
                reconcile_doc.allocate_entries(args)
                reconcile_doc.reconcile()
