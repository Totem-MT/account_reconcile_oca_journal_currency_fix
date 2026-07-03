# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
from odoo import api, fields, models
from odoo.addons.account_reconcile_oca.models.account_bank_statement_line import (
    AccountBankStatementLine as AccountBankStatementLineOca,
)


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

    def _oca_get_auto_reconcile_models(self, company_ids):
        return self.env["account.reconcile.model"].search(
            [
                ("rule_type", "in", ["invoice_matching", "writeoff_suggestion"]),
                ("company_id", "in", company_ids),
                ("auto_reconcile", "=", True),
            ]
        )

    def _oca_get_reconcile_model_match_amount(self, for_auto_create=False):
        self.ensure_one()
        if for_auto_create:
            return self.amount_currency or self.amount
        return self.amount_total_signed

    def _oca_get_reconcile_model_max_amount(self, aml, amount, for_auto_create=False):
        self.ensure_one()
        max_amount = amount
        if (
            not for_auto_create
            and aml.currency_id == self._get_reconcile_currency()
            and self.amount_currency
            and self.amount_total_signed
        ):
            max_amount = aml.currency_id.round(
                max_amount * self.amount_currency / self.amount_total_signed
            )
        return max_amount

    def _oca_append_reconcile_model_write_off_lines(
        self, data, reconcile_model, residual_balance, reconcile_auxiliary_id
    ):
        """Append reconcile-model write-off lines for an explicit residual balance."""
        self.ensure_one()
        currency = self._get_reconcile_currency()
        default_name = next(
            (line_data["name"] for line_data in data if line_data["kind"] == "liquidity"),
            "",
        )
        partner = (
            reconcile_model._get_partner_from_mapping(self) or self._retrieve_partner()
        )
        for line in reconcile_model._get_write_off_move_lines_dict(
            residual_balance, partner.id
        ):
            new_line = line.copy()
            new_line["name"] = new_line.get("name") or default_name
            new_line["partner_id"] = partner and partner.name_get()[0] or False
            amount = line.get("balance")
            currency_amount = False
            if self.foreign_currency_id:
                amount = self.foreign_currency_id.compute(
                    amount, self.journal_id.currency_id or self.company_currency_id
                )
            if currency != self.company_id.currency_id:
                currency_amount = self.company_id.currency_id._convert(
                    amount,
                    currency,
                    self.company_id,
                    self.date,
                )
            new_line.update(
                {
                    "reference": "reconcile_auxiliary;%s" % reconcile_auxiliary_id,
                    "id": False,
                    "amount": amount,
                    "debit": amount if amount > 0 else 0,
                    "credit": -amount if amount < 0 else 0,
                    "kind": "other",
                    "account_id": self.env["account.account"]
                    .browse(line["account_id"])
                    .name_get()[0],
                    "date": fields.Date.to_string(self.date),
                    "line_currency_id": currency.id,
                    "currency_id": self.company_id.currency_id.id,
                    "currency_amount": currency_amount or amount,
                    "name": line.get("name") or self.payment_ref,
                }
            )
            reconcile_auxiliary_id += 1
            if line.get("partner_id"):
                new_line["partner_id"] = (
                    self.env["res.partner"].browse(line["partner_id"]).name_get()[0]
                )
            elif self.partner_id:
                new_line["partner_id"] = self.partner_id.name_get()[0]
            data.append(new_line)
        return data, reconcile_auxiliary_id

    def _oca_add_model_amls_to_reconcile_data(
        self, res, data, reconcile_auxiliary_id, for_auto_create=False
    ):
        """Add matched move lines and optional tolerance write-offs to reconcile data."""
        self.ensure_one()
        amount = self._oca_get_reconcile_model_match_amount(for_auto_create)
        reconcile_model = res["model"]
        for aml in res.get("amls", self.env["account.move.line"]):
            max_amount = self._oca_get_reconcile_model_max_amount(
                aml, amount, for_auto_create=for_auto_create
            )
            reconcile_auxiliary_id, line_data = self._get_reconcile_line(
                aml,
                "other",
                is_counterpart=True,
                max_amount=max_amount,
                reconcile_auxiliary_id=reconcile_auxiliary_id,
                move=True,
            )
            amount -= sum(line.get("amount") for line in line_data)
            data += line_data

        if res.get("status") == "write_off":
            data, reconcile_auxiliary_id = self._oca_append_reconcile_model_write_off_lines(
                data, reconcile_model, amount, reconcile_auxiliary_id
            )
        return data, reconcile_auxiliary_id

    def _oca_build_liquidity_reconcile_data(self, reconcile_auxiliary_id=1):
        self.ensure_one()
        liquidity_lines, _suspense_lines, _other_lines = self._seek_for_lines()
        data = []
        for line in liquidity_lines:
            reconcile_auxiliary_id, lines = self._get_reconcile_line(
                line,
                "liquidity",
                reconcile_auxiliary_id=reconcile_auxiliary_id,
                move=True,
            )
            data += lines
        return data, reconcile_auxiliary_id

    def _oca_reconcile_data_from_model_result(
        self,
        res,
        data,
        reconcile_auxiliary_id,
        for_auto_create=False,
        manual_reference=None,
        try_auto_reconcile=False,
    ):
        self.ensure_one()
        data, reconcile_auxiliary_id = self._oca_add_model_amls_to_reconcile_data(
            res, data, reconcile_auxiliary_id, for_auto_create=for_auto_create
        )
        if try_auto_reconcile and res.get("auto_reconcile") and self.reconcile_data_info:
            self.reconcile_bank_line()
        return self._recompute_suspense_line(
            data,
            reconcile_auxiliary_id,
            manual_reference if manual_reference is not None else self.manual_reference,
        )

    def _oca_auto_reconcile_after_create(self):
        """Apply auto-reconcile models with payment-tolerance write-offs fixed."""
        models = self._oca_get_auto_reconcile_models(self.company_id.ids)
        if not models:
            return
        for record in self:
            res = models._apply_rules(record, record._retrieve_partner())
            if not res:
                continue
            data, reconcile_auxiliary_id = record._oca_build_liquidity_reconcile_data()
            if res.get("status") == "write_off" and res.get("amls"):
                reconcile_data = record._oca_reconcile_data_from_model_result(
                    res,
                    data,
                    reconcile_auxiliary_id,
                    for_auto_create=True,
                    manual_reference=record.manual_reference,
                )
            elif res.get("status") == "write_off":
                reconcile_data = record._recompute_suspense_line(
                    *record._reconcile_data_by_model(
                        data, res["model"], reconcile_auxiliary_id
                    ),
                    record.manual_reference,
                )
            elif res.get("amls"):
                reconcile_data = record._oca_reconcile_data_from_model_result(
                    res,
                    data,
                    reconcile_auxiliary_id,
                    for_auto_create=True,
                    manual_reference=record.manual_reference,
                )
            else:
                continue
            if not reconcile_data.get("can_reconcile"):
                continue
            getattr(
                record,
                "_reconcile_bank_line_%s" % record.journal_id.reconcile_mode,
            )(record._prepare_reconcile_line_data(reconcile_data["data"]))

    @api.model_create_multi
    def create(self, mvals):
        # Skip account_reconcile_oca.create (broken write_off branch) and run our own
        # auto-reconcile loop afterwards.
        records = super(AccountBankStatementLineOca, self).create(mvals)
        records._oca_auto_reconcile_after_create()
        return records

    def _default_reconcile_data(self, from_unreconcile=False):
        if not from_unreconcile:
            res = (
                self.env["account.reconcile.model"]
                .search(
                    [
                        (
                            "rule_type",
                            "in",
                            ["invoice_matching", "writeoff_suggestion"],
                        ),
                        ("company_id", "=", self.company_id.id),
                    ]
                )
                ._apply_rules(self, self._retrieve_partner())
            )
            if res and res.get("status") == "write_off" and res.get("amls"):
                data, reconcile_auxiliary_id = self._oca_build_liquidity_reconcile_data()
                return self._oca_reconcile_data_from_model_result(
                    res,
                    data,
                    reconcile_auxiliary_id,
                    for_auto_create=False,
                    try_auto_reconcile=True,
                )
        return super()._default_reconcile_data(from_unreconcile=from_unreconcile)
