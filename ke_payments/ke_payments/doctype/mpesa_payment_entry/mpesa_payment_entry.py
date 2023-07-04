# Copyright (c) 2023, Pointershub and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from ke_payments.ke_payments.api.payment_entry import create_payment_entry, reconcile_payment_entries


class MpesaPaymentEntry(Document):
    def before_insert(self):
        self.set_missing_values()

    def set_missing_values(self):
        self.currency = "KES"
        self.full_name = ""
        if self.firstname:
            self.full_name = self.firstname
        if self.middlename:
            self.full_name += " " + self.middlename
        if self.lastname:
            self.full_name += " " + self.lastname

        register_url_list = frappe.get_all(
            "Customer To Business Register URL",
            filters={
                "register_status": "Success",
            },
            fields=["business_shortcode", "company", "mode_of_payment", "is_child", "child_shortcode"],
        )
        for record in register_url_list:
            if self.businessshortcode == record.business_shortcode or (
                    record.is_child and self.businessshortcode == record.child_shortcode):
                self.company = record.company
                self.mode_of_payment = record.mode_of_payment
                break

    def before_submit(self):
        if not self.transamount:
            frappe.throw(_("Trans Amount is required"))
        if not self.company:
            frappe.throw(_("Company is required"))
        if not self.customer:
            frappe.throw(_("Customer is required"))
        if not self.mode_of_payment:
            frappe.throw(_("Mode of Payment is required"))
        if not self.reference_doctype == "POS Invoice":
            self.payment_entry = self.create_payment_entry()
            reconcile_payment_entries(self.customer, self.company)

    def create_payment_entry(self):
        payment_entry = create_payment_entry(
            self.company,
            self.customer,
            self.transamount,
            self.currency,
            self.mode_of_payment,
            self.posting_date,
            self.transid,
            self.posting_date,
            self.submit_payment,
        )
        return payment_entry.name
