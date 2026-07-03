# Account Reconcile OCA: Journal Currency Fix

Workaround for a multi-currency bug in **account_reconcile_oca** (16.0.x).

## Problem

With a **company in EUR** and a **bank journal in USD** (e.g. PayPal USD), reconciliation model
proposals can cap matched invoices at the **company-currency** move total (e.g. EUR 308.22)
instead of the **journal-currency** statement amount (USD 350.85).

Typical symptoms:

- Reconcile model finds the right invoice (e.g. by order ref).
- Proposed amount on the invoice is wrong (USD 308.22 instead of USD 350.85).
- Leftover balance on suspense and spurious exchange differences.
- Deleting the proposal and selecting the invoice manually works.

This happens when the statement line has **no** `foreign_currency_id` / `amount_currency`
(normal for a USD journal) and `account_reconcile_oca` uses `amount_total_signed` (EUR) as
`max_amount` without converting to the journal currency.

## Fix

This module adjusts `max_amount` before `account_reconcile_oca` builds the proposal: when the
cap equals the liquidity line balance in company currency, it is replaced by the amount in
journal currency (`amount` on the statement line or `amount_currency` on the liquidity move
line).

## Installation

1. Add this folder to Odoo `addons_path` (e.g. next to other `odoo_kodea` modules).
2. Restart Odoo.
3. **Apps** → update list → install **Account Reconcile OCA: Journal Currency Fix**.

Requires `account_reconcile_oca` (OCA account-reconcile, 16.0).

## Verification

1. Open a PayPal USD statement line matched to a USD invoice (e.g. order 22669).
2. Without touching the lines, check the proposed invoice amount: **350.85 USD**, not 308.22.
3. Validate reconciliation → invoice paid, exchange difference ~0.42 EUR only.

## Note

This is a local workaround until OCA handles journal-currency journals without
`foreign_currency_id` on the statement line. Safe to remove once upstream fixes the case.
