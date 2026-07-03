# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import models


class AccountBankStatementLine(models.Model):
    _inherit = "account.bank.statement.line"

    def _reconcile_fix_invoice_matching_max_amount(self, aml, max_amount):
        """Use the journal-currency amount when OCA caps invoices with company currency.

        account_reconcile_oca passes move.amount_total_signed (company currency, e.g. EUR
        308.22) as max_amount while the bank journal is in another currency (e.g. USD).
        When the statement line has no foreign_currency_id / amount_currency, the widget
        then caps the invoice in USD at the EUR figure.
        """
        self.ensure_one()
        reconcile_currency = self._get_reconcile_currency()
        if aml.currency_id != reconcile_currency or self.amount_currency:
            return max_amount

        company_currency = self.company_id.currency_id
        if self.currency_id == company_currency:
            return max_amount

        journal_amount = reconcile_currency.round(abs(self.amount))
        liquidity_lines, _suspense, _other = self._seek_for_lines()
        if liquidity_lines:
            liquidity_amount_currency = abs(liquidity_lines[:1].amount_currency)
            if not reconcile_currency.is_zero(liquidity_amount_currency):
                journal_amount = reconcile_currency.round(liquidity_amount_currency)

        company_cap = (
            abs(sum(liquidity_lines.mapped("balance")))
            if liquidity_lines
            else abs(max_amount)
        )
        if company_currency.compare_amounts(abs(max_amount), company_cap) == 0:
            return journal_amount
        return max_amount

    def _get_reconcile_line(
        self,
        line,
        kind,
        is_counterpart=False,
        max_amount=False,
        from_unreconcile=False,
        reconcile_auxiliary_id=False,
        move=False,
        is_reconciled=False,
    ):
        if is_counterpart and max_amount:
            max_amount = self._reconcile_fix_invoice_matching_max_amount(
                line, max_amount
            )
        return super()._get_reconcile_line(
            line,
            kind,
            is_counterpart=is_counterpart,
            max_amount=max_amount,
            from_unreconcile=from_unreconcile,
            reconcile_auxiliary_id=reconcile_auxiliary_id,
            move=move,
            is_reconciled=is_reconciled,
        )
