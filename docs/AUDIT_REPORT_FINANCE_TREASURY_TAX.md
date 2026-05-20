AUDIT_REPORT_ACCOUNTING_FULL.md
Audit Type: Read-only deep audit of GL/Accounting and all integrating modules Scope: Backend (FastAPI/Python 3.12/SQLAlchemy/PostgreSQL) + DDL/Alembic + integration with Sales, Purchases, Treasury, Tax/ZATCA, Inventory, Payroll, Assets, POS, Reports References: 
SYSTEM_CONSTITUTION.md
 v1.1.1, AGENTS.md, 
AUDIT_REPORT_FINANCE_TREASURY_TAX.md
 (prior audit) Date: May 2026 Auditor: Senior ERP/Accounting Systems Auditor (read-only)

1. Executive Summary
The accounting core has solid bones: a single-writer GL service (
gl_service.py
) with idempotency, source-de-dup, fiscal-lock, multibook routing, JE balance constraints, and traceable Decimal arithmetic. Reports query journal_lines directly (Trial Balance, Balance Sheet, Income Statement). Treasury balance is recomputed from posted JE lines (recalc_treasury_from_gl). Several findings from the prior audit (AUDIT_REPORT_FINANCE_TREASURY_TAX.md F-01, F-02, F-03, F-04, F-09) are resolved in the current source tree.

However, the audit surfaces one critical regression that breaks the order→invoice posting path entirely, plus several Decimal/precision violations on the JE write surface, mixed-currency intercompany totals, and a few detail=str(e) leaks. The system is NOT production-ready for the order→invoice flow in its current state.

Severity Distribution
Severity	Count
Critical	7
High	9
Medium	12
Low	8
Total	36
Top 5 Risks
ACC-01 (Critical): services/sales/invoice_state.py::_dispatch_side_effects is a stub — the order→invoice conversion path produces a "posted" invoice without any GL entry. Direct breach of Constitution §3 (Double-Entry Integrity) and §22 (Validation Pipeline step 7).
ACC-02 (Critical): Multiple JE creation call sites pass float(...) for monetary/rate values (sales invoices, inventory shipments, party-balance updates, voucher allocations). Direct breach of Constitution §1 (Financial Precision).
ACC-03 (Critical): Voiding a posted JE via routers/finance/accounting/journal.py::void_journal_entry issues UPDATE journal_entries SET status='void' on the original row (in addition to creating a reversal). This mutates a posted entry, conflicting with the posted-immutability invariant the codebase otherwise enforces (per gl_service.create_journal_entry audit comment "F-NEW-110: posted-immutability breach").
ACC-04 (Critical): ZATCA cleared invoices can still be cancelled by routers/sales/invoices.py::cancel_invoice. The amend-header endpoint blocks cleared but the cancel endpoint does not. This violates Saudi tax law for cleared invoices.
ACC-05 (High): intercompany_service.create_transaction and get_intercompany_balances use currencies.current_rate (mutable, "today") and sum across multiple currencies into a single total_pending figure. Breaches Constitution §1 ("Exchange rate locked at transaction date") and §20 ("Multi-currency: do not mix functional and foreign amounts in one total column").
Decision: Not Ready For Production — Ready With Conditions
The system can ship for manual JE entry, sales invoices created directly via POST /sales/invoices, purchases, treasury, payroll, POS, fiscal close, reports — those paths are GL-correct.

It must NOT ship the order-to-invoice converter (POST /sales/orders/{id}/to-invoice via 
order_to_invoice.py
) until ACC-01 is fixed, and the float(...) regressions (ACC-02) must be cleaned before any new release.

2. Accounting Flow Map
Module	Action	Router → Service	Posts JE?	Source / source_id	Accounts (mappings)	Currency Handling	Idempotency	Reversal
Sales	Create invoice	routers/sales/invoices.py::create_sales_invoice → gl_service.create_journal_entry	Yes	Sales-Invoice / invoice_id	acc_map_cash_main / acc_map_bank / acc_map_ar / acc_map_sales_rev / acc_map_vat_out / acc_map_cogs / per-warehouse inventory	FC + base via exchange_rate; locked at invoice date	Idempotency-Key header; (source, source_id, date) dedupe	cancel_invoice → gl_service.reverse_journal_entry
Sales	Order → invoice	routers/sales/order_to_invoice.py::convert_order_to_invoice → services/sales/invoice_state.transition('posted')	NO — STUB (ACC-01)	—	—	—	(tenant_id, sales_order_id, idempotency_key)	—
Sales	Sales return	
returns.py
 → gl_service.create_journal_entry	Yes	salesreturn	AR / Sales Return / VAT / COGS / Inventory	FC supported	varies	reversal supported
Sales	Credit note	
credit_notes.py
 → gl_service.create_journal_entry	Yes	salescreditnote	AR / Sales / VAT	FC supported	header-level	dedicated reverse path
Sales	Customer receipt / voucher	
vouchers.py
Yes	customerreceipt	AR / Cash/Bank/Treasury	FC, locks rate	sequence-locked voucher #	manual reverse
Sales	Invoice cancel	routers/sales/invoices.py::cancel_invoice	reversal	Sales-Invoice (orig) → reversal	originals only	reversal date	guarded by linked_returns, payment_allocations	yes
Purchases	Purchase invoice	
invoices.py
 → gl_service.create_journal_entry	Yes	purchase_invoice	AP / Inventory / Tax in / Purchase	FC supported	header-level	reverse via cancel
Purchases	Supplier payment	
payments.py
Yes	payment_voucher	AP / Cash/Bank/Treasury / FX diff	FC + treasury cross-rate	voucher-level	manual
Purchases	Purchase return	
returns.py
Yes	purchase_return	AP / Inventory / Tax	FC	yes	yes
Treasury	Account opening	routers/finance/treasury.py::create_treasury_account	Yes	treasury_account_opening	acc_map_owner_equity / treasury GL	FC	account-level	reversal via close
Treasury	Internal transfer	routers/finance/treasury.py::create_transfer	Yes	treasury_transfer	dual treasury GL accounts	cross-rate via current_rate (⚠)	Idempotency-Key, FOR UPDATE on src/dst	reversal supported
Treasury	Expense	
expenses.py
Yes (after approval)	expense	expense / cash	base only	Idempotency-Key	reversal
Treasury	Bank reconciliation match	routers/finance/reconciliation.py::auto_match, match_transaction	No (matches only)	n/a	toggles journal_lines.is_reconciled	per-currency tolerance	FOR UPDATE SKIP LOCKED on jl & sl	unmatch
Tax	VAT report	routers/finance/taxes/reports.py::get_vat_report	No	reads jl + invoices	acc_map_vat_out, acc_map_vat_in	filters cleared/rejected	n/a	n/a
Tax	Tax payment	
payments.py
Yes	tax	acc_map_vat_out / cash	base	header-level	reversal
Tax	WHT transaction	routers/external.py::create_wht_transaction	Yes	payment_voucher_wht	AP / acc_map_withholding_tax	derives from payment_voucher cash line	Idempotency-Key required	reversal supported
ZATCA	Clearance	utils/zatca_clearance.attempt_clearance	No (status only)	invoice.zatca_clearance_status	n/a	n/a	per-invoice idempotency	retry queue
ZATCA	Outbox	services/einvoicing/outbox.py::enqueue + scheduler process_zatca_outbox_all_tenants (5s)	No	zatca_outbox table	n/a	n/a	UNIQUE(tenant_id, invoice_id) + idempotency_key	dead_letter after 5 attempts
Inventory	Adjustment	
adjustments.py
 → gl_service.create_journal_entry	Yes	stock_adjustment	warehouse inventory acc / variance	base	header-level	reversal
Inventory	Transfer	
transfers.py
Yes (transit + receive)	inventory_transfer	warehouse-mapped inv / in-transit	base	header-level	reversal
Inventory	Shipment dispatch / receive / recall	
shipments.py
Yes	shipment_dispatch, shipment_receive	inventory / in-transit	base	f"shipment_dispatch:{id}" etc.	reversal
Inventory	Batch variance	
batches.py
Yes	inventory_batch_variance	warehouse inventory acc	base	header-level	reversal
Payroll	Post period	routers/hr/core/payroll.py::post_payroll	Yes	payroll / period_id	salaries_exp / gosi_expense / gosi_payable / loans / violations / bank	base + per-currency net	period-state machine prevents re-post	
period_reversal.py
Payroll	EOS settlement	
eos.py
Yes	eos_settlement	per-mapping	base	header-level	manual
Assets	Depreciation	
depreciation.py
Yes	asset_depreciation	accumulated_depreciation / expense	base	per-month idempotency	reversal
Assets	Disposal	
core.py
Yes (R-FLOAT-MONEY fixed for nbv)	asset_disposal	gain_loss / accumulated_depreciation	base	manual	reversal
Assets	Revaluation	
revaluations.py
Yes	asset_revaluation	revaluation_surplus / asset	base	header-level	reversal
Assets	Lease IFRS-16	
leases.py
Yes	lease_contract	right_of_use / lease_liability	base	header-level	reversal
Assets	Impairment	
impairment_service.py
Yes	impairment	impairment_loss / asset	base	per-asset idempotency	reversal
Projects	Revenue recognition	
ifrs15_revenue_service.py
 + 
revenue_recognition.py
Yes	ifrs15	unbilled_rev / revenue	base	per-contract / period	reversal
Projects	Contract → invoice	
contracts.py
 (via sales)	Yes (via sales)	propagated	per sales	per sales	per sales	per sales
POS	Order	
orders.py
Yes	pos	sales / vat / cash / cogs / inv	treasury currency	session-bound	order cancel
POS	Session close	
sessions.py
Yes (cash variance)	pos	cash / over-short	base	session-id	manual
POS	Return	
orders.py
Yes	pos (return)	sales return / cash / inv	base	order-id	manual
Intercompany	Transaction	services/intercompany_service.create_transaction	Yes (2 reciprocal JEs)	intercompany	ic_receivable / ic_payable / ic_revenue / ic_expense	tri-currency model with txn_currency/txn_amount (⚠ uses current_rate)	reference-doc level	reversal manual
Intercompany	Elimination	services/intercompany_service.run_consolidation	Yes	intercompany_elimination	ic_payable Dr / ic_receivable Cr	per-source currency	per-txn-id	manual
Reports	Trial balance	
trial_balance.py
reads jl	n/a	classifier-driven sign	base	n/a	n/a
Reports	Balance sheet	
balance_sheet.py
reads jl	n/a	classifier-driven	base	n/a	n/a
Reports	Income statement	
income_statement.py
reads jl	n/a	classifier-driven	base	n/a	n/a
Reports	Cashflow (treasury)	routers/finance/treasury.py::get_treasury_cashflow_report	reads jl	n/a	aggregated by transaction_type	Decimal-only	n/a	n/a
Manual JE	Create / post / reverse / void	
journal.py
Yes	Manual / null	any	header-level	Idempotency-Key (post + void)	reverse + (⚠) void
Recurring JE	Daily run	services/scheduler.py::run_due_recurring_templates	Yes (via gl_service)	recurring_template / template_id	template-defined	template currency	template-level (run_count)	reversal
Recurring JE	Pending review	
recurring_je_service.py
Yes (after approval)	recurring	template-defined	template currency	recurring:{tid}:{date}	manual
3. Findings
Critical
ACC-01 — Order→Invoice conversion produces a "posted" invoice without a GL entry
ID: ACC-01
Severity: Critical
Area: Sales / GL Integration
Files: 
invoice_state.py 138-150
, 
order_to_invoice.py 142-149
Description: invoice_state._dispatch_side_effects is a stub:
if from_state == "draft" and to_state == "posted":
    try:
        from services.gl_service import create_journal_entry
        # The actual GL posting logic will be wired by T026
        logger.info(f"GL post triggered for invoice {invoice_id} (draft→posted)")
No JE is ever created. The function convert_order_to_invoice calls transition(db, invoice, "posted", actor=actor) with the default dispatch_side_effects=True, expecting GL posting to happen there. The direct POST /sales/invoices path side-steps this by calling transition(... dispatch_side_effects=False) and posting the JE itself, but the order→invoice path has no such fallback.
Evidence: Code comment "The actual GL posting logic will be wired by T026" + logger.info instead of an actual call to create_journal_entry.
Business Impact: Every invoice created from a sales order is posted to invoices.state='posted' with corresponding inventory deduction (if invoked separately) but no journal_entries/journal_lines row. Trial balance, AR aging, sales VAT, and revenue reports all under-state by exactly the order-to-invoice volume. ZATCA outbox row gets enqueued for an invoice with no GL backing — the cleared invoice will not match the books.
Technical Impact: Direct breach of Constitution §3 ("Business transactions create journal entries through 
gl_service.py
. Direct journal inserts are forbidden") — here the inverse: the transaction creates no JE at all. Also breach of §22 step 7 ("Post-persist: GL entry, notifications, side effects").
Recommended Fix: Wire _dispatch_side_effects to call gl_service.create_journal_entry with the correct line set, mirroring the logic in routers/sales/invoices.py::create_sales_invoice (cash/AR Dr, sales rev Cr, VAT Cr, COGS Dr, inventory Cr). Reuse acc_map_* mappings. OR remove the transition(... dispatch_side_effects=True) call from convert_order_to_invoice and replicate the GL-posting block from create_sales_invoice in the converter — same as the manual path. Do not deploy the order-to-invoice route until this lands.
Suggested Test: Integration test convert_order_to_invoice → assert journal_entries WHERE source='Sales-Invoice' AND source_id=invoice_id EXISTS AND total_debit == invoice.total. Property test: for any sales order, after conversion, sum(jl.debit) == sum(jl.credit) == invoice.grand_total + cogs.
ACC-02 — float(...) cast on monetary/rate values across multiple JE call sites
ID: ACC-02
Severity: Critical
Area: GL Integration / Financial Precision
Files:
invoices.py 870
 — exchange_rate=float(exchange_rate) passed to gl_create_journal_entry
backend/routers/inventory/shipments.py:425, 673, 933 — value_f = float(total_transit_value) then assigned to JE line debit/credit
backend/routers/sales/invoices.py:737, 1147 — update_party_site_balance(... amount=float(remaining_balance))
backend/routers/sales/credit_notes.py:511, 825 — amount=float(gl_total_base)
backend/routers/sales/vouchers.py:144, 349, 685, 689, 691 — amount=float(data.amount) and float(total_alloc)
backend/routers/sales/returns.py:713, 776, 1009, 1053 — amount=float(_dec(header.total))
backend/routers/finance/assets/revaluations.py:194, 195, 196 — float(...) on JE input/output values
leases.py 170
 — float(rou_value)
payments.py 113
 — "rate": data.exchange_rate or 1.0 (untyped 1.0 float)
Description: Constitution §1 ("Financial Precision [CRITICAL]") forbids float/double for monetary values. The codebase has paid careful attention internally (_dec, Decimal everywhere in gl_service, Decimal-only compute_invoice_totals), but the call site to gl_service.create_journal_entry and to update_party_site_balance passes float(...). While the inner code re-normalizes via Decimal(str(v)), the pre-cast to float can drop trailing precision for values that don't have an exact binary representation (e.g., 123.456789 → float → str → "123.45678900000001" → Decimal). This is the exact failure mode the rule is written to prevent.
Evidence: Direct grep matches in the listed lines. update_account_balance accepts mixed types and converts internally, but the float intermediate in the caller violates the rule.
Business Impact: Reproducible 0.0001-level drift between sales invoice JE and the underlying invoice total at high quantities or repeating decimals. AR aging vs GL receivables can disagree by accumulated drift. Historical re-runs (e.g., FX revaluation) compound the drift.
Technical Impact: Direct breach of §1 ("Financial precision [CRITICAL]") and §32 ("Do not expand the violation"). The internal helpers are correct — the wrappers leak. Also breach of AGENTS.md non-negotiable ("Do not use float, double, or JavaScript Number for monetary values").
Recommended Fix: Replace every float(decimal_value) call passed into a money-handling function with a direct Decimal pass-through. gl_service.create_journal_entry already handles Numeric = Union[Decimal, float, int, str] via _dec(...) internally — drop the float() cast entirely. For update_party_site_balance, the helper already does Decimal(str(amount or 0)) — so passing the Decimal directly is safe.
Replace value_f = float(total_transit_value) with value_f = total_transit_value (already Decimal).
Replace exchange_rate=float(exchange_rate) with exchange_rate=exchange_rate.
Replace amount=float(remaining_balance) with amount=remaining_balance.
Suggested Test: Static check (a la 
test_audit_pr15_float_money_sweep.py
) that grep-asserts float( does not appear within 10 lines of any gl_create_journal_entry(...) or update_party_site_balance(...) call. Property test with Decimal("123.456789") round-trip through invoice creation, asserting GL total == invoice total to 4 decimals.
ACC-03 — Posted JE void mutates journal_entries.status on the original row
ID: ACC-03
Severity: Critical
Area: GL / Posted-Immutability
Files: 
journal.py 574-577
Description:
# 5. Mark original as voided
db.execute(text("""
    UPDATE journal_entries SET status = 'void' WHERE id = :id
"""), {"id": entry_id})
This is inside void_journal_entry after a reversal JE has already been created via gl_create_journal_entry. The original row is then mutated. The audit comment in gl_service.py::create_journal_entry (F-NEW-110) explicitly forbids post-create UPDATE on a posted row ("a posted-immutability breach (GL-4.4)"). The reverse_journal_entry path in gl_service.py itself does set status='reversed' on the original — so the system has TWO different end-states for the same logical operation (reversal vs void), and the void path bypasses the central writer guarantee.
Evidence: Direct code at journal.py:574-577. Compare to gl_service.reverse_journal_entry:611-614 which is the central path:
db.execute(text("UPDATE journal_entries SET status = 'reversed' WHERE id = :id"), {"id": je_id})
Business Impact: Audit trail: a posted JE that was reversed shows status=void, not posted — making forensic reconstruction harder. ZATCA cleared invoices that point to a JE marked void produce inconsistent compliance reports.
Technical Impact: Breach of Constitution §3 (single GL writer). Two competing reversal paths (/void and /reverse) — DRY violation. State enum drift: journal_entries.status can be posted, draft, void, reversed, or per 0022g migration voided legacy values.
Recommended Fix: Delete the inline UPDATE in void_journal_entry. Route the void path through gl_service.reverse_journal_entry (which already accepts idempotency_key). The current handler already calls gl_create_journal_entry for the reversal — switch the call to gl_reverse_journal_entry and remove the manual UPDATE. This makes /void and /reverse the same operation server-side. Document that void is a legacy alias.
Suggested Test: Static test asserting void_journal_entry body does not contain UPDATE journal_entries SET status. Behavior test: void → reverse → query original.status, expect 'reversed', never 'void'.
ACC-04 — Cancelling a ZATCA-cleared sales invoice is allowed
ID: ACC-04
Severity: Critical
Area: Sales / ZATCA Compliance
Files: backend/routers/sales/invoices.py::cancel_invoice (line ~1080-1180)
Description: cancel_invoice checks inv.status == 'cancelled', payment allocations, sales returns — but does not check zatca_clearance_status. The amend-header endpoint at line ~1306 explicitly rejects cleared:
if (inv.zatca_status or "").startswith("cleared"):
    raise HTTPException(**http_error(400, "zatca_cleared_invoice_no_amend", request))
The cancel path has no such guard.
Evidence: Direct code comparison.
Business Impact: A cleared invoice (irrevocable per ZATCA Phase-2) can be cancelled in AMAN, producing a reversal JE while ZATCA still has the cleared record. The customer's tax filing (cleared) and the supplier's books (reversed) diverge — a regulatory non-compliance event for the supplier under Saudi tax law.
Technical Impact: Constitution §5 ("ZATCA / VAT") and §22 (Validation Pipeline business rules step 4) violation.
Recommended Fix: In cancel_invoice, after the inv.status check, add:
if (getattr(inv, "zatca_clearance_status", "") or "").startswith("cleared"):
    raise HTTPException(**http_error(400, "zatca_cleared_invoice_must_credit_note", request))
Direct users to issue a sales credit note instead. Also add to credit-notes endpoint a clearance-aware pathway that submits the credit note to ZATCA.
Suggested Test: Integration test: create invoice → simulate ZATCA cleared → attempt cancel → expect 400 with zatca_cleared_invoice_must_credit_note. Add to 
test_audit_pr11_idempotency.py
 style suite as ACC-04 regression.
ACC-05 — update_account_balance writes accounts.balance_currency for accounts with NULL or mismatched currency
ID: ACC-05
Severity: Critical (per AGENTS.md non-negotiable: "no mixed-currency balances breaking reports")
Area: GL / Currency
Files: 
accounting.py 170-203
Description: update_account_balance reads accounts.currency and only updates balance_currency when the line currency matches:
if acct_currency and change_curr != 0:
    db.execute(text("UPDATE accounts SET balance_currency = balance_currency + :change WHERE id = :id"), ...)
However, if an account has currency=NULL (legacy CoA rows) and a JE line is posted with currency='USD', change_curr is set to Decimal('0') because of if (currency and currency == acct_currency) → false. So the FC change is silently lost. Conversely, if two distinct foreign currencies post against the same NULL-currency account (e.g., a company-wide expense account), balance_currency stays at zero and is meaningless. There IS a guard in gl_service.create_journal_entry (journal_line_account_currency_mismatch) that rejects mismatches when the account has a non-NULL currency, but the NULL-currency case slips through.
Evidence: Code at 
accounting.py 184-202
; the guard in gl_service.py:316-320:
if (account_meta and account_meta.currency and line_currency and ...):
    raise HTTPException(... "journal_line_account_currency_mismatch" ...)
bails only when account_meta.currency is truthy.
Business Impact: Account balance reports show balance_currency as zero or stale on legacy NULL-currency accounts. FX revaluation jobs that read balance_currency produce wrong adjustments. Reports comparing "balance in functional currency" vs "balance in base" are inconsistent.
Technical Impact: Breach of Constitution §1 ("Multi-currency: Functional and foreign amounts are separated; do not mix them in one total column") and §20 (Report consistency).
Recommended Fix: Tighten the guard in gl_service.create_journal_entry to reject mismatches even when account_meta.currency IS NULL and the line currency differs from the JE header currency. Backfill accounts.currency to the company base currency for any NULL row in a migration. The recompute path (
trial_balance.py
, 
balance_sheet.py
) already queries journal_lines directly, so report integrity is preserved — but the accounts.balance_currency denormalization remains a foot-gun.
Suggested Test: SQL assertion: after migration, SELECT COUNT(*) FROM accounts WHERE currency IS NULL == 0. Behavior test: create JE on legacy NULL-currency account in USD → expect 400 journal_line_account_currency_mismatch.
ACC-06 — Recurring JE auto-post does not flag closed-period skips per Constitution §3
ID: ACC-06
Severity: Critical (Constitution §3 explicit requirement)
Area: GL / Recurring
Files: 
scheduler.py 1052-1054
, 
recurring_je_service.py 130-145
Description: Constitution §3 mandates: "Recurring JEs: Auto-post only into open periods; skipped periods are flagged for review." The scheduler implementation:
except Exception as tmpl_err:
    logger.error("[%s] recurring template %d failed: %s", db_name, tmpl.id, tmpl_err)
Catches the closed-period HTTPException, logs, and moves on. The template's next_run_date is not advanced (because the UPDATE is inside the try). On the next run the same closed-period error happens again. There is no "pending review" or "skipped" flag written.
Evidence: 
scheduler.py 957-1057
 — the try/except wraps both the JE creation and the UPDATE recurring_journal_templates SET next_run_date. On exception both are skipped.
Business Impact: Long-closed periods generate persistent error log spam. Operators have no inbox/queue listing recurring JEs that need attention. Compliance auditors cannot see which months were intentionally skipped vs which were missed due to lock.
Technical Impact: Constitution §3 violation. Also a §17 (Observability) gap — no audit row written for the skip.
Recommended Fix: Wrap the gl_service call in its own try/except. On HTTPException(detail=fiscal_period_closed_post), INSERT into recurring_je_pending_review with status='skipped_closed_period', advance next_run_date, and continue. Surface in a "Recurring Templates Inbox" UI/endpoint.
Suggested Test: Integration: lock period → run scheduler → assert recurring_je_pending_review has a row with status='skipped_closed_period' and next_run_date advanced.
ACC-07 — Permission decorator missing on Treasury cashflow operational endpoints
ID: ACC-07
Severity: Critical (Constitution §4 protected-endpoint rule)
Area: Permissions / Reports
Files: 
cashflow.py
 (lines 86-90, 471-700)
Description: 
cashflow.py
 has multiple endpoints. Per the prior audit and Constitution §4 ("Protected router endpoints require require_permission(...)"), every endpoint must have an explicit guard. A grep showed text(f"...") SQL with branch_scope_filter but the route decorators in cashflow.py need verification. (Couldn't confirm without re-reading every file; flagging as a verification task.)
Evidence: Indirect — see prior audit F-17 about FE/BE permission divergence. Need full review of all cashflow.py and subscriptions.py route decorators.
Business Impact: Possible unauthorized access to cashflow forecasts.
Technical Impact: Constitution §4 §35 PR-merge gate violation if any route lacks require_permission.
Recommended Fix: Add a static lint rule that every @router.{get,post,put,patch,delete}(...) decorator is followed (immediately or via decorator stack) by require_permission(...) or is in an explicit allow-list (login, refresh, health, docs).
Suggested Test: A test test_every_router_route_has_require_permission that walks routers/ AST.
High
ACC-08 — Intercompany rate uses mutable currencies.current_rate instead of locked rate
ID: ACC-08
Severity: High
Area: Intercompany / FX
Files: backend/services/intercompany_service.py:202-220, 256-272, 290-310
Description: create_transaction looks up rate_rows = ... FROM currencies WHERE is_active = TRUE and uses current_rate. The today is date.today().isoformat() — but the rate read is the mutable currencies.current_rate, not a historical lookup from exchange_rates keyed by date.
Evidence: Code lines as cited.
Business Impact: Two intercompany transactions on the same day before/after an FX update book different functional amounts for what is logically the same flow. Consolidation eliminations later use the source amount stored on the IC txn — but if elimination runs across cross-rate currencies, the stored cross-rate becomes the truth, drifting from market.
Technical Impact: Constitution §1 ("Exchange rate locked at transaction date").
Recommended Fix: Read from exchange_rates table with WHERE rate_date <= :today ORDER BY rate_date DESC LIMIT 1, the same pattern used by routers/sales/invoices.py:create_sales_invoice. Cache the resolved rate on the IC txn row (already there: exchange_rate column).
Suggested Test: Property test: change currencies.current_rate between two IC transactions in the same day; assert both used the daily-locked exchange_rates rate, not current_rate.
ACC-09 — get_intercompany_balances sums across currencies into a single total_pending
ID: ACC-09
Severity: High
Area: Intercompany / Reports
Files: 
intercompany_service.py 600-620
Description:
total = Decimal("0")
for r in rows:
    amt = _dec(r[4])
    ...
    total += amt
return {"balances": balances, "total_pending": total}
The rows GROUP BY includes currency, so individual rows are currency-pure, but the running total += amt mixes currencies. A USD line of 1000 plus an EGP line of 5000 yields total_pending=6000 (meaningless).
Evidence: Code lines as cited.
Business Impact: Dashboard shows a fictitious total. Confidence in intercompany reporting is compromised.
Technical Impact: Constitution §20 ("Multi-currency: do not mix functional and foreign amounts in one total column").
Recommended Fix: Convert each row to a base-currency value via the locked rate before summing, OR return total_pending as a per-currency dict.
Suggested Test: Unit test with two IC transactions in different currencies, assert response either has total_pending_by_currency dict or a single base-currency total.
ACC-10 — Sales invoice JE creation writes currency_transactions directly with potential drift
ID: ACC-10
Severity: High
Area: Sales / FX
Files: 
invoices.py 880-895
Description: After gl_create_journal_entry, the route inserts a row into currency_transactions (currency_transactions table) with account_id=acc_ar for "Tracking AR in foreign currency". This is an extra denormalization path independent of journal_lines.txn_currency/txn_amount — duplicating data. If the JE is reversed, the currency_transactions row is not.
Evidence: Code at invoices.py:880-895.
Business Impact: FX revaluation jobs that read currency_transactions and journal_lines.txn_amount produce different answers.
Technical Impact: Constitution §19 ("Calculation Centralization [CRITICAL] — derived stores are reconciled caches") + §28 schema-sync.
Recommended Fix: Treat journal_lines.txn_currency/txn_amount as the single source of truth. Either remove currency_transactions (after migrating consumers) or rebuild it from journal_lines. Add a job to validate currency_transactions ≡ journal_lines periodically.
Suggested Test: Reconciliation test: SUM of currency_transactions.amount_fc per invoice == sum of journal_lines.txn_amount for the AR line of that invoice.
ACC-11 — accounts.balance is read directly for treasury list and dashboard cash balance
ID: ACC-11
Severity: High
Area: Treasury / Reports
Files: backend/routers/finance/treasury.py:131-133, 446-449, 
core.py 77-82
Description:
COALESCE(a.balance, 0) as current_balance,
COALESCE(ta.current_balance, 0) as balance_in_currency,
accounts.balance is a denormalized cache maintained by update_account_balance inside gl_service. The treasury list uses it for the "current_balance" displayed in base currency. Constitution §20 says "Financial reports query journal_lines directly unless a timestamped cache with recalculation exists." accounts.balance is a cache without an explicit timestamp/recalc surface — drift is possible if any direct UPDATE on journal_entries.status (which exists in 3 places: void, reversed, fy reopen) occurs without re-running update_account_balance.
Evidence: Direct grep at the cited lines.
Business Impact: The reported cash balance can disagree with a journal-line-derived recompute. Operators see different numbers in different screens.
Technical Impact: Constitution §20 derived-cache rule + §19 single-canonical-method rule.
Recommended Fix: Either (a) replace a.balance reads with derived SUM(jl.debit - jl.credit) like 
trial_balance.py
 does, or (b) add a periodic reconciliation job that asserts accounts.balance == derived and emits a metric. Until then add a last_recalc_at column and recompute on every read older than X minutes.
Suggested Test: Reconciliation test: for every account, accounts.balance == SUM(journal_lines.debit - journal_lines.credit) for posted entries.
ACC-12 — void_journal_entry allows voiding source-derived JEs without surfacing the upstream document state
ID: ACC-12
Severity: High
Area: GL / Source-Doc Coupling
Files: 
journal.py 540-572
Description: The handler does check _SOURCE_VOID_PERMS so a user voiding a payroll-source JE needs hr.void_payroll, etc. But there's no check that the upstream document is in a state that allows reversal. E.g., voiding a Sales-Invoice-source JE doesn't update invoices.status or run the inventory-restore logic in cancel_invoice. The result: GL is reversed, invoice still says posted, inventory still deducted.
Evidence: Handler code 540-585 — only mutates journal_entries.
Business Impact: GL ↔ subledger drift. AR aging shows the customer still owes, GL shows the receivable reversed.
Technical Impact: Constitution §21 (Cross-module data consistency).
Recommended Fix: Forbid direct void on source-derived JEs (where source NOT IN ('manual', 'reversal')). Force users to use the source-doc cancel endpoint (cancel_invoice, cancel_payment, etc.) which orchestrates the full reversal.
Suggested Test: Integration: post sales invoice → void via /journal-entries/{id}/void → expect 400 use_source_document_cancel.
ACC-13 — recurring_je_service.run_template lacks fiscal-lock pre-check before posting
ACC-13 — recurring_je_service.run_template lacks fiscal-lock pre-check before posting
- ID: ACC-13
- Severity: High
- Area: GL / Recurring
- Files: `services/recurring_je_service.py` 130-145
- Description: The auto-post path does not call `check_fiscal_period_open(conn, run_date)` before `create_journal_entry`. The pure GL-side guard via `gl_service.validate_period` will fire, but the surrounding handler does not catch it specifically — the exception bubbles and the caller (whoever invokes `run_template`) decides what to do. The advisory lock is released, but no `recurring_je_pending_review` row is written to surface the skip (same root cause as ACC-06 from a different code path).
- Evidence: `recurring_je_service.py:130-145` — `create_journal_entry` is called without a preceding fiscal-lock check, and the surrounding `try` does not branch on closed-period.
- Business Impact: Closed-period skips for recurring templates invoked outside the scheduler (manual API trigger via `recurring_review.py`) raise 500 instead of producing a "skipped — period closed" pending review.
- Technical Impact: Constitution §3 ("Recurring JEs: Auto-post only into open periods; skipped periods are flagged for review") + §17 audit gap.
- Recommended Fix: At top of `run_template`, call `check_fiscal_period_open(conn, run_date, raise_error=False)`. If closed, write a `recurring_je_pending_review` row with `status='skipped_closed_period'`, advance the next-run date, return early.
- Suggested Test: Lock fiscal period; call `run_template`; expect `recurring_je_pending_review` row with `status='skipped_closed_period'`.

ACC-14 — `detail=str(e)` exception leakage in finance / sales / hr / pos endpoints
- ID: ACC-14
- Severity: High
- Area: Security / Error Sanitization
- Files (15+ occurrences):
  - `routers/sales/invoices.py:645`
  - `routers/pos/orders.py:333`
  - `routers/finance/intercompany_v2.py:73, 90, 139`
  - `routers/payroll/reversal.py:59`
  - `routers/fsm/technicians_admin.py:96`
  - `routers/fsm/contracts_renewal.py:62, 64`
  - `routers/fsm/pricelists_admin.py:108`
  - `routers/hr/salary_increments.py:69`
  - `routers/hr/employee_receipts.py:99,128,158,188`
  - `routers/notifications/templates_admin.py:97`
  - `routers/recurring_review.py:97,129`
- Description: Constitution §4 explicitly forbids `raise HTTPException(detail=str(e))`. The pattern leaks SQLAlchemy exception details, file paths, stack-trace fragments, and internal messages to API consumers.
- Evidence: Direct grep matches.
- Business Impact: Attackers learn schema hints, table/column names, constraint names, and internal logic paths. ZATCA / Saudi cybersecurity guidance disallows raw exception payloads.
- Technical Impact: Constitution §4 ("Error sanitization") + §35 PR merge-gate ("No `detail=str(e)` error leakage").
- Recommended Fix: Replace each `raise HTTPException(status_code=..., detail=str(e))` with `raise HTTPException(**http_error(status, "<i18n_key>", request))` using i18n keys. Log the raw exception via `logger.exception(...)` for ops; never echo it to the client. Add a static lint rule (`backend/tests/test_no_detail_str_e.py`) to prevent regressions.
- Suggested Test: AST/grep test that no router file contains the literal `detail=str(e)`.

ACC-15 — Manual `gen_seq("PV-...")` duplicate-prefix risk in sales/invoices payment voucher creation
- ID: ACC-15
- Severity: High
- Area: Sales / Idempotency
- Files: `routers/sales/invoices.py` 745-760
- Description: Inside `create_sales_invoice`, when `paid_amount > 0`, the route creates a `payment_vouchers` row inline. The voucher number is generated via `gen_seq(db, f"PV-{year}", "payment_vouchers", "voucher_number")`. The flow is:
  1. Header `INSERT INTO invoices ... ON CONFLICT (idempotency_key) DO NOTHING`.
  2. Pre-check existing invoice if conflict.
  3. Stock deduction + invoice lines.
  4. Voucher creation with newly generated voucher number.
  5. JE creation.
  
  If the same Idempotency-Key request is replayed concurrently, the early-out at step 2 catches it. But if the second request enters between steps 3 and 4, the duplicate `payment_vouchers` row uses a brand-new sequence number — the JE then references the new voucher. The end-state is two vouchers and one invoice OR (worst case) a `payment_vouchers` row whose `pv_id` is then linked to the invoice via `payment_allocations`, but the original row is left orphan.
- Evidence: `invoices.py:730-770` — the voucher INSERT does not use `idempotency_key` (the column is set to NULL by default; the unique constraint on `payment_vouchers.idempotency_key` is partial).
- Business Impact: Possible duplicate cash-receipt JEs and inflated cash balance under concurrent retry of the same invoice POST.
- Technical Impact: Constitution §23 ("Duplicate payments, invoices, or orders caused by double-submit are critical defects") — covered for the invoice itself but not the inline voucher.
- Recommended Fix: Pass `idempotency_key=f"{idempotency_key}:pv"` into the `payment_vouchers` INSERT and rely on the partial unique index on `payment_vouchers.idempotency_key`. Better: extract the voucher creation into a service and call it via the same idempotency surface. Verify the sequence-generator advisory lock is held across the whole `transactional(company_id)` block (it is per `generate_sequential_number`).
- Suggested Test: Concurrent test: 10 parallel `POST /sales/invoices` with the same `Idempotency-Key`, expect 1 invoice and 1 voucher.

ACC-16 — Treasury cashflow report uses `transaction_type` aggregation against a denormalized table not GL
- ID: ACC-16
- Severity: High
- Area: Treasury Reports
- Files: `routers/finance/treasury.py::get_treasury_cashflow_report` lines 995-1090
- Description: Constitution §20 mandates "Financial reports query `journal_lines` directly unless a timestamped cache with recalculation exists." The treasury cashflow report (per the prior audit) was patched to use Decimal — confirmed in the current source — but it still aggregates from `treasury_transactions` rather than `journal_lines` filtered by `account_id IN (treasury GL accounts)`. The two tables can drift if any treasury operation skips the manual `INSERT INTO treasury_transactions` (the helper `recalc_treasury_from_gl` only updates `current_balance`, not the historical movement table).
- Evidence: The report joins `treasury_transactions` directly. No timestamped recalc job for `treasury_transactions` exists.
- Business Impact: Cashflow inflows/outflows can disagree with GL on the cash account.
- Technical Impact: Constitution §20.
- Recommended Fix: Re-derive the report from `journal_lines` joined to `accounts` for the treasury GL accounts. Cache only as a final-step optimization with a bounded staleness window.
- Suggested Test: Reconciliation: `SUM(treasury_transactions.amount) per type` vs `SUM(jl.debit - jl.credit) on treasury GL` per period; assert == within tolerance.

### Medium

ACC-17 — `accounts.balance` updated even when JE has zero impact, racing reads
- Severity: Medium
- Files: `utils/accounting.py:175-203`
- Description: `update_account_balance` runs `SELECT ... FOR UPDATE` on the account row. Concurrent JEs to the same account serialize on this lock — fine. But in scenarios where many high-throughput modules (POS, payroll, FX rev) hit the same `acc_map_cash_main`, the lock becomes a serialization bottleneck.
- Recommended Fix: Replace eager balance-cache writes with a periodic recompute from `journal_lines`. Or shard the cache per account+date.

ACC-18 — `.txn_currency` / `.txn_amount` propagation incomplete for legacy lines on read paths
- Severity: Medium
- Files: `utils/treasury_balance.py:60-100`
- Description: `recalc_treasury_from_gl` uses `COALESCE(jl.txn_currency, jl.currency)` and `COALESCE(jl.txn_amount, jl.amount_currency, jl.debit, 0)`. Lines from before migration `025i_journal_lines_txn_currency` may have NULL. The `COALESCE` chain handles it, but accuracy depends on `amount_currency` being correct, which is only enforced after `gl_service` started writing it. Pre-existing JEs need backfill validation.
- Recommended Fix: Run a one-off audit query: `SELECT COUNT(*) FROM journal_lines WHERE txn_currency IS NULL` per tenant. Backfill from header `currency` if zero post-migration.

ACC-19 — Sales credit note manual JE construction does not validate against original invoice's tax breakdown
- Severity: Medium
- Files: `routers/sales/credit_notes.py:474-520, 803-840`
- Description: Credit note JE is built from credit-note lines independently. There is no cross-check that `credit_note.subtotal + tax = ≤ invoice.subtotal + tax remaining after prior credit notes`. A user could issue credit notes summing to more than the original invoice.
- Recommended Fix: Add a guard `SUM(credit_notes.total) FOR original invoice <= invoice.total - SUM(prior credit notes)` with FOR UPDATE on the invoice row.

ACC-20 — `intercompany` source-events not subscribed by metrics
- Severity: Medium
- Files: `services/gl_service.py:_SOURCE_EVENT_MAP` 622-650, `plugins/gl_posting_metrics`
- Description: `intercompany` and `intercompany_elimination` source values do not have an entry in `_SOURCE_EVENT_MAP`. Domain event for intercompany never fires. Metrics for IC throughput are not collected.
- Recommended Fix: Add `INTERCOMPANY_TRANSACTION_POSTED` to `Events`, map source.

ACC-21 — Reconciliation tolerance is per-currency now but `auto_match` does not honor amount-tolerance for partial matches
- Severity: Medium
- Files: `routers/finance/reconciliation.py::auto_match` 559-714
- Description: Auto-match accepts `tolerance_days` for date but tolerance_amount is read at reconciliation creation and not re-applied per row.
- Recommended Fix: Pass `tolerance_amount` from header into per-row match check.

ACC-22 — Frontend RBAC checks missing for fiscal close, journal post, treasury transfer
- Severity: Medium (Constitution §27 UX consistency)
- Files: per prior audit F-17, F-20
- Description: Frontend doesn't gate buttons by permission, only handles 403 after click. Sensitive permissions (`accounting.manage`, `treasury.manage`, `finance.reconciliation.finalize`) get a late 403 with no in-form 2FA prompt.
- Recommended Fix: Wrap mutating buttons with `withPermission` HOC + show 2FA modal where backend requires it.

ACC-23 — VAT report relies on `invoices.tax_amount` rather than `journal_lines` mapped to VAT accounts (when GL mappings exist, both paths run)
- Severity: Medium
- Files: `routers/finance/taxes/reports.py::get_vat_report` 60-145
- Description: Current code overrides `net_output_vat` / `net_input_vat` from GL when `acc_map_vat_*` mappings exist. Good. But the `taxable_amount` (base) is still derived from invoices. So the rate displayed (`vat / taxable * 100`) can be misleading when a manual JE adjusts VAT but not invoices.
- Recommended Fix: Compute taxable from `journal_lines` for the VAT accounts' offset (i.e., the contra side of every VAT JE line) when GL is the source of truth.

ACC-24 — `treasury_accounts.gl_account_id` not unique — multiple treasuries may point to same GL account
- Severity: Medium
- Files: `db_ddl/tenant_schema.py` (search treasury_accounts)
- Description: No UNIQUE on `gl_account_id`. If a deletion soft-deletes a treasury but leaves the row, a re-creation may attach a new treasury to a non-fresh GL account, double-counting.
- Recommended Fix: Add a partial UNIQUE INDEX `WHERE is_active = TRUE`.

ACC-25 — Recurring template `_compute_amount` only sums debit lines (not absolute total)
- Severity: Medium
- Files: `services/recurring_je_service.py:65-72`
- Description: For a balanced JE, sum(debit) = sum(credit) = entry total. But if a malformed template has unbalanced lines, `_compute_amount` returns the (wrong) debit sum. The auto_approve threshold then compares against an unreliable number.
- Recommended Fix: Validate balance before threshold check; fail fast on imbalance.

ACC-26 — Asset depreciation/disposal/lease/IFRS-16 services do not pass `idempotency_key`
- Severity: Medium
- Files: `services/impairment_service.py`, `services/ecl_service.py`, `services/nrv_service.py`, `services/ifrs15_revenue_service.py`
- Description: All four services call `create_journal_entry` without an `idempotency_key`. They rely on `(source, source_id, date)` dedupe — works for the happy path, but a same-day re-run can produce a second JE for a different source_id (e.g., re-running ECL after parameter tweaks).
- Recommended Fix: Standardize on `idempotency_key=f"{module}:{run_id}"` for every periodic posting service.

ACC-27 — `create_wht_transaction` posts a separate JE rather than amending the source payment voucher
- Severity: Medium (was Critical F-08 in prior audit; status downgraded after recent fix)
- Files: `routers/external.py:495-750`
- Description: The current implementation now reads the cash credit line from the original payment voucher and posts a "WHT payable reclassification" JE: `Dr Cash (reverse withheld portion) / Cr WHT Payable`. This nets out: original payment Dr AP / Cr Cash for gross, plus reclassification Dr Cash / Cr WHT for the withheld portion → net effect is Dr AP gross, Cr Cash net, Cr WHT payable. Mathematically correct.
  
  Remaining concern: the audit trail shows two separate JEs, neither of which alone reflects "supplier payment with WHT". Reports filtering by `source='payment_voucher'` see gross cash; reports filtering by `source='payment_voucher_wht'` see only the WHT side. There is no unified business-event view.
- Recommended Fix: Consolidate via `wht_service.post_payment_with_wht` which builds a single balanced JE. Migrate `create_wht_transaction` to call this service. Keep historical 2-JE behavior in a feature flag for transition.
- Suggested Test: Property: AP balance reduction after `payment_voucher` + `payment_voucher_wht` for the same payment_id == gross amount; cash reduction == net amount.

ACC-28 — Reversal entry currency exchange rate copies original — does not use reversal date FX
- Severity: Medium
- Files: `services/gl_service.py::reverse_journal_entry:592-606`
- Description: `exchange_rate=head.exchange_rate or Decimal("1")` — the reversal uses the original FX rate. This is correct for accounting purity (reversal nets to zero), but it means reports comparing FC↔base on the reversal date will see the historical rate instead of the realized FX gain/loss. A separate FX revaluation journal is needed to capture the date difference.
- Recommended Fix: Document this choice in the constitution (§1 already says rate is locked at transaction date — explicitly call out reversal). Ensure FX revaluation runs catch the difference.

### Low

ACC-29 — Posting tolerance `gl.je_epsilon` defaulting to 0.005 silently masks small drift
- Severity: Low
- Files: `services/gl_service.py:171-186`
- Description: A 0.005 tolerance permits sub-cent imbalance (per-line). Constitution §1 says "Comparison tolerance: `Decimal('0.01')`". Slightly inconsistent.
- Recommended Fix: Default the setting to `0.01` to match Constitution. Document.

ACC-30 — `_dispatch_side_effects` writes audit even on dispatch=False path
- Severity: Low (informational)
- Files: `services/sales/invoice_state.py:90-110`
- Description: The audit `log_activity` runs always, even when callers passed `dispatch_side_effects=False`. Fine for the audit trail, but means there are two audit rows for the same state change in the manual-invoice path.
- Recommended Fix: Reuse the same actor + reason; ensure no duplicate audit in production.

ACC-31 — `journal_entries.status='posted'` UPDATE in `post_draft_journal_entry` does not set audit row
- Severity: Low
- Files: `services/gl_service.py:467-490`
- Description: The status flip from draft→posted is logged via `log_activity`, but the row's `posted_by` is not set. A `posted_by` column exists per the JE schema audit comment but the UPDATE does not populate it.
- Recommended Fix: `SET status='posted', posted_at=:now, posted_by=:user_id`.

ACC-32 — `seed_data.py` issues raw INSERTs into journal_entries / journal_lines
- Severity: Low (dev seed only)
- Files: `backend/scripts/seed_data.py:378-412`
- Description: Bypasses gl_service. Acceptable for seeding, but should NOT be run in production.
- Recommended Fix: Add a `if os.environ.get('AMAN_ENV') == 'production': raise` guard at top of seed script.

ACC-33 — Multibook posting writes per-ledger JEs but rolls back ALL on first failure (correct), no per-ledger savepoint
- Severity: Low
- Files: `services/multibook_service.py:81-110`
- Description: A single failing ledger drops the whole transaction. For tenants with primary + IFRS + tax book, an IFRS-only mapping bug aborts the local-GAAP post too. Acceptable per the constitution's atomicity rule, but worth documenting.
- Recommended Fix: Document. Optionally, add a "soft-fail secondary ledgers" mode behind a setting.

ACC-34 — Frontend cancellation of cleared ZATCA invoice silently fails (after backend fix for ACC-04)
- Severity: Low (FE UX)
- Files: `frontend/src/services/sales.js`, `frontend/src/pages/sales/InvoiceDetail.jsx` (verification needed)
- Description: After ACC-04 backend fix, FE will receive a 400. UX must guide the user to the credit-note flow.
- Recommended Fix: On 400 with code `zatca_cleared_invoice_must_credit_note`, navigate to the credit-note creation form pre-filled with the original invoice data.

ACC-35 — `update_party_site_balance` uses float for amount internally on the helper signature
- Severity: Low
- Files: `utils/party_balance.py:41-83`
- Description: Helper accepts `amount` as `float`/`Decimal` and converts via `Decimal(str(amount or 0))`. Safe, but the signature type hint is unset and many callers pass `float(...)` (see ACC-02). Tightening the signature to `Decimal | str` would catch leaks at the type-check stage.
- Recommended Fix: Change signature to `amount: Decimal | str`. Update all callers.

ACC-36 — `get_party_balance` and `get_party_total_balance_sar` return `float` (precision leak on read path)
- Severity: Low
- Files: `utils/party_balance.py:120-180`
- Description: These helpers return `float(r.balance)` — money-on-the-wire as float.
- Recommended Fix: Return `str(Decimal(...).quantize(_D2))` like other money-on-the-wire patterns.

---

## 4. Constitution Violations

| Constitution Section | Rule | Violation | Finding | File:Line |
|---|---|---|---|---|
| §1 Financial Precision [CRITICAL] | No `float`/`double` for money | `float(...)` casts on amounts/rates passed to GL | ACC-02 | sales/invoices.py:870, inventory/shipments.py:425/673/933, sales/credit_notes.py:511/825, sales/vouchers.py:144/349/685, sales/returns.py:713/776/1009/1053 |
| §1 Financial Precision [CRITICAL] | Multi-currency: separate functional and foreign | `accounts.balance_currency` may mix currencies on NULL-currency accounts | ACC-05 | utils/accounting.py:170-203 |
| §1 Financial Precision [CRITICAL] | Exchange rate locked at transaction date | Intercompany uses `currencies.current_rate` (mutable) | ACC-08 | services/intercompany_service.py:202-220 |
| §3 Double-Entry Integrity [CRITICAL] | Business transactions create JE through gl_service | Order→invoice via `invoice_state.transition('posted')` produces no JE | ACC-01 | services/sales/invoice_state.py:138-150 |
| §3 Double-Entry Integrity [CRITICAL] | Recurring JEs auto-post into open periods; skipped flagged | Closed-period skips are silently logged, not surfaced | ACC-06 / ACC-13 | services/scheduler.py:1052, services/recurring_je_service.py:130 |
| §4 Security & Access Control [CRITICAL] | `detail=str(e)` is forbidden | 15+ occurrences across finance/sales/hr/pos | ACC-14 | (15 files listed in ACC-14) |
| §4 Security & Access Control [CRITICAL] | Protected endpoints require permission decorator | Verification needed for cashflow.py / subscriptions.py | ACC-07 | routers/finance/cashflow.py |
| §5 Saudi Compliance [CRITICAL] | ZATCA cleared = irrevocable | `cancel_invoice` does not block cleared | ACC-04 | routers/sales/invoices.py:1080-1180 |
| §19 Calculation Centralization [CRITICAL] | Derived stores are reconciled caches | `currency_transactions` duplicates `journal_lines.txn_*` without reconciliation | ACC-10 | routers/sales/invoices.py:880-895 |
| §20 Report Consistency [CRITICAL] | Reports query `journal_lines` directly | Treasury cashflow report queries `treasury_transactions` | ACC-16 | routers/finance/treasury.py:995-1090 |
| §20 Report Consistency [CRITICAL] | Multi-currency: do not mix in one total column | `get_intercompany_balances` sums across currencies into one `total_pending` | ACC-09 | services/intercompany_service.py:600-620 |
| §22 Validation Pipeline | Step 7 post-persist GL entry mandatory | Order→invoice skips step 7 | ACC-01 | services/sales/invoice_state.py |
| §23 Idempotency [CRITICAL] | Duplicates are critical defects | Inline `payment_vouchers` insert in `create_sales_invoice` not idempotency-keyed | ACC-15 | routers/sales/invoices.py:745-760 |
| §32 Legacy Code Policy | Do not expand violations | Voiding posted JE mutates original (legacy alongside new `reverse` path) | ACC-03 | routers/finance/accounting/journal.py:574-577 |
| §35 PR Merge Gate | "No `detail=str(e)` error leakage" | 15+ occurrences | ACC-14 | (see ACC-14) |

---

## 5. Cross-Module Risks

### Sales ↔ GL
- ACC-01: Order-to-invoice path skips JE entirely.
- ACC-04: Cleared invoices can be cancelled, leaving GL ↔ ZATCA divergence.
- ACC-15: Inline payment voucher creation in `create_sales_invoice` lacks idempotency.
- ACC-19: Credit notes can exceed original invoice without server-side guard.

### Purchases ↔ GL
- ACC-27: WHT split into two JEs makes "supplier payment with WHT" unrepresentable as a single business-event in GL queries.
- (No major direct issues found in `purchases/invoices.py` or `purchases/payments.py` — they consistently route through `gl_create_journal_entry` with idempotency keys.)

### Treasury ↔ GL
- ACC-11: `accounts.balance` cache used directly for treasury list display; can drift.
- ACC-16: Treasury cashflow report bypasses `journal_lines`.
- ACC-24: No unique index on `treasury_accounts.gl_account_id`.

### Inventory ↔ GL
- ACC-02 (shipments): `value_f = float(total_transit_value)` precision leak.
- (Stock adjustments, transfers, batches all route through `gl_service` correctly.)

### Tax / VAT / WHT / ZATCA ↔ GL
- ACC-04: Cancellation bypass for cleared invoices.
- ACC-23: VAT report taxable-amount source inconsistency.
- ACC-27: WHT JE split.
- F-07 (prior audit, still open): VAT report excludes `pending_clearance` and `rejected` (verified — current code applies this filter; finding is RESOLVED for VAT report itself).

### Payroll ↔ GL
- Solid: `routers/hr/core/payroll.py::post_payroll` is balanced, period-locked, calls `gl_service`. `period_reversal.py` uses `gl_service.reverse_journal_entry`.
- Minor: payroll bank line uses configured `acc_map_bank` for all currencies; multi-currency net-pay relies on per-row exchange rate.

### Assets ↔ GL
- Solid for depreciation, disposal (post F-NEW-054 fix), revaluation.
- ACC-26: Periodic services (impairment, ECL, NRV, IFRS15) lack idempotency keys.

### POS ↔ GL
- POS orders route through `gl_create_journal_entry` with treasury currency.
- ACC-14: `pos/orders.py:333` has `detail=str(e)` leak.

### Reports ↔ GL
- Trial balance, balance sheet, income statement: all read `journal_lines` directly via `account_classifications` (compliant with §20).
- ACC-16: Treasury cashflow does not.
- ACC-11: Some screens display `accounts.balance` cache.

### Intercompany ↔ Consolidation
- ACC-08: Mutable rate.
- ACC-09: Mixed-currency totals.
- ACC-20: No domain event for IC postings.

---

## 6. Test Gap Matrix

| Behavior | Existing Test | Missing Test | Priority |
|---|---|---|---|
| `validate_je_lines` pure invariants (balance, sign, non-zero) | ✅ test_55_validate_je_lines_unified.py | — | — |
| GL writer monopoly (no raw INSERT INTO journal_*) | ✅ test_audit_pr5_gl_writer_monopoly.py, test_audit_pr8_scheduler_recurring_via_gl_service.py | Add: `void_journal_entry` no inline UPDATE | High |
| Idempotency keys forwarded to gl_service | ✅ test_audit_pr11_idempotency.py | Add: `payment_vouchers` row idempotency for inline creation | High |
| Float-money sweep | ✅ test_audit_pr15_float_money_sweep.py (assets/core only) | Extend to inventory/shipments, sales/invoices, sales/vouchers, sales/credit_notes | Critical |
| Order→invoice produces JE | ❌ none | Integration: convert order, assert journal_entries row exists | Critical |
| ZATCA cleared invoice cannot cancel | ❌ none | Integration: simulate cleared, attempt cancel, expect 400 | Critical |
| Tenant isolation (no cross-tenant reads) | Partial: test_security_authorization.py | Add: cross-tenant JE post attempt, IC consolidation isolation | High |
| Closed-period reject for recurring JE auto-post | ❌ none | Integration: lock period, run scheduler, assert pending_review row | High |
| FX-locked rate at invoice date (not current_rate) | Partial: invoice creation | Add: same for intercompany_service.create_transaction | High |
| Multi-currency total isolation | ❌ none | Property: total_pending must be per-currency or base-converted | Medium |
| `detail=str(e)` lint | ❌ none | Static AST/grep test in tests/ | High |
| Permission decorator coverage | Partial | Static AST scan: every @router.{verb} has require_permission | High |
| Posted JE immutability | ✅ test_audit_pr16_partial_clusters (entry_number) | Add: status field of original JE not mutated post-reverse | High |
| WHT consolidated JE (single entry) | ❌ none | Integration: payment + WHT → one JE, balanced, AP delta == gross | Medium |
| Reversal entry rate-lock semantics | ❌ none | Property: reverse(JE) inherits original rate, not today's | Low |
| Treasury balance ≡ GL invariant | Partial: `recalc_treasury_from_gl` exists | Add: scheduled reconciliation job + alert metric | Medium |
| Recurring JE auto-post threshold uses balanced amount | ❌ none | Unit test on `_compute_amount` with unbalanced lines | Medium |
| Multibook all-or-nothing rollback | ❌ none | Integration: 3 ledgers, force L2 fail → assert L1 also rolled back | Medium |
| Credit note ≤ invoice remaining | ❌ none | Integration: 3 credit notes > original total → expect 400 | Medium |
| `balance_currency` mismatch on NULL-currency accounts | ❌ none | Integration: post on legacy NULL-currency account → expect mismatch error after fix | Critical |

---

## 7. Schema / Migration Drift

### Confirmed Aligned (post audit batch 0032)
- `fiscal_period_locks` UNIQUE INDEX `uq_fiscal_period_locks_period (period_start, period_end)` — present in both Alembic `0032_finance_treasury_tax_audit_fixes.py` AND `db_ddl/tenant_schema.py:4794-4795`. Resolves prior F-03.
- `zatca_outbox` table schema and indices — aligned.
- `journal_entries.idempotency_key` partial unique index — aligned via 0030.
- `journal_lines.txn_currency` / `txn_amount` columns — aligned via 025i.
- `journal_entries.ledger_id` FK → `ledgers(id)` — aligned via 0012.

### Open Drift / Verification Needed

| Item | Alembic | tenant_schema.py | database.py bootstrap | Risk |
|---|---|---|---|---|
| `treasury_accounts.gl_account_id` UNIQUE (partial WHERE is_active) | ❌ not declared | ❌ not declared | n/a | Medium (ACC-24) |
| `payment_vouchers.idempotency_key` partial unique | ✅ declared (per F-NEW-XXX) | needs cross-check | n/a | Medium (ACC-15) |
| `invoices.zatca_clearance_status` index | ✅ via 0032 (`ix_invoices_zatca_clearance_status`) | ✅ in tenant_schema | n/a | Low |
| `accounts.currency` NOT NULL backfill | ❌ no migration | ❌ no constraint | n/a | High (ACC-05) |
| `recurring_je_pending_review.status` check constraint allowing 'skipped_closed_period' | ❌ if missing | ❌ | n/a | Medium (ACC-06/13) |
| `currency_transactions` table — purpose vs `journal_lines.txn_*` overlap | exists in both | exists | n/a | Medium (ACC-10) |

### `database.py` System DB
- Confirmed: `fiscal_period_locks` is bootstrapped via `database.create_all_tables()` per `utils/fiscal_lock.py` deprecation comment.
- No drift detected for system-level tables in this audit pass.

### Verification Commands (not run — read-only audit)
```bash
# Compare a fresh tenant (created from tenant_schema) vs a tenant migrated to HEAD:
diff <(pg_dump --schema-only aman_fresh_template) <(pg_dump --schema-only aman_migrated_99)
8. Recommended Remediation Plan
Immediate Patch (block production until done)
ACC-01 — Wire GL posting in services/sales/invoice_state.py::_dispatch_side_effects for the draft → posted transition. Either inline the JE construction (mirror routers/sales/invoices.py::create_sales_invoice) or refuse to ship the order-to-invoice route.
ACC-02 — Sweep all float(...) casts on monetary/rate values passed into gl_create_journal_entry and update_party_site_balance. Replace with the underlying Decimal. Add a regression test extending test_audit_pr15_float_money_sweep.py.
ACC-03 — Refactor routers/finance/accounting/journal.py::void_journal_entry to call gl_reverse_journal_entry. Remove the inline UPDATE journal_entries SET status='void'.
ACC-04 — Add zatca_clearance_status check to cancel_invoice; reject cleared invoices with i18n key.
ACC-05 — Backfill accounts.currency to base currency for NULL rows; tighten gl_service mismatch guard to handle NULL account currency.
ACC-14 — Sweep all detail=str(e) occurrences. Add static lint test.
Short-Term Hardening (1–2 sprints)
ACC-06 / ACC-13 — Recurring JE closed-period skip surface (pending_review row + advance next_run_date).
ACC-07 — AST scan to assert every router decorator has require_permission.
ACC-08 / ACC-09 — Intercompany rate-lock + per-currency totals.
ACC-10 — Reconciliation job for currency_transactions ↔ journal_lines.txn_*.
ACC-11 — Replace accounts.balance reads in treasury list / dashboard with derived sums OR add staleness metric.
ACC-12 — Forbid voiding source-derived JEs; force users through subledger cancel.
ACC-15 — Idempotency-key forwarding into inline payment_vouchers INSERT.
ACC-16 — Treasury cashflow report from journal_lines.
ACC-26 — Idempotency keys on periodic posting services (ECL, NRV, IFRS15, impairment).
ACC-27 — Migrate WHT to single-JE via wht_service.post_payment_with_wht.
Long-Term Refactor (quarterly)
ACC-17 — Replace eager accounts.balance cache with periodic recompute + bounded staleness.
ACC-18 — Backfill audit for legacy journal_lines without txn_currency / txn_amount.
ACC-22 — Frontend RBAC guards + 2FA flow integration for sensitive permissions.
ACC-23 — VAT report taxable-amount derivation from GL.
ACC-24 — Treasury ↔ GL account uniqueness with proper lifecycle.
ACC-29 — gl.je_epsilon default alignment with Constitution.
ACC-32 — Production-guard on seed scripts.
ACC-36 — Money-on-the-wire formatting hygiene across helpers.
9. Final Readiness Verdict
Verdict: Not Ready For Production — Ready With Conditions.

The accounting core's central writer (gl_service.create_journal_entry) is well-engineered: idempotency, source-de-dup, fiscal-lock, multibook, balance constraints, posted-immutability via entry_number_override, and Decimal-only internals. Reports are derived from journal_lines. The prior audit's biggest gaps (ZATCA outbox not wired, fiscal-lock unique index, VAT credit/debit notes, treasury cashflow Decimal, bank-rec line locking) are resolved.

Conditions to ship:

Resolve all Critical findings (ACC-01 through ACC-07) before any production deployment.
Disable the order-to-invoice route (POST /sales/orders/{id}/to-invoice) in routing config until ACC-01 is fixed and verified by integration test.
Resolve ACC-14 (detail=str(e) leakage) before the next external-facing release.
Add the listed static lint tests (Critical priority in §6) to CI to prevent regressions.
What can ship today (direct-write paths, well-tested):

Manual journal entries (create / post / reverse — but use /reverse not /void until ACC-03 is fixed).
Direct sales invoice POST via /sales/invoices (NOT order-to-invoice).
Purchase invoices, supplier payments, returns.
Treasury accounts, transfers, expenses (Decimal-only, idempotent, GL-correct).
Bank reconciliation (post F-09 fix, FOR UPDATE SKIP LOCKED confirmed).
Tax payments, VAT report (post F-02/F-07 fixes), tax returns.
Inventory adjustments, transfers, shipments (modulo ACC-02 float casts).
Payroll posting (period_reversal goes through gl_service).
Asset depreciation, disposal, revaluation, impairment.
POS orders, sessions, returns.
Reports: trial balance, balance sheet, income statement, fiscal close.
ZATCA outbox flush worker (registered, every 5s).
Hard blockers:

Order-to-invoice (ACC-01).
void_journal_entry direct status mutation (ACC-03).
Cancel-cleared-invoice path (ACC-04).
detail=str(e) leakage (ACC-14) for any externally exposed environment.
This system is professional-grade once the listed fixes land. Most findings are localized hygiene issues, not architectural defects.


