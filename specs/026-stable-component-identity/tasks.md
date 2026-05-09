# Tasks: Stable Component Identity

**Input**: Design documents from `/specs/026-stable-component-identity/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/ui-pattern.md

**Tests**: Not requested - omitted per specification.

**Organization**: Tasks grouped by priority phase based on plan.md implementation approach.

## Format: `[ID] [P?] [Priority?] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Priority]**: Priority label (P1=High Traffic, P2=HR/Reports, P3=Settings/Other, P4=Components)
- Include exact file paths in descriptions

## Path Conventions

- **Frontend**: `frontend/src/`
- **Pages**: `frontend/src/pages/`
- **Components**: `frontend/src/components/`

---

## Phase 1: Setup (Reusable Hook)

**Purpose**: Create shared debounce hook for branch switching

- [X] T001 Create useDebounceBranch hook in frontend/src/hooks/useDebounceBranch.js

---

## Phase 2: Foundational (Already Complete)

**Purpose**: Core infrastructure already implemented

**Status**: COMPLETE - These were fixed in earlier conversation

- [x] T002 Remove key={branchRouteKey} from Routes in frontend/src/App.jsx
- [x] T003 Apply initialLoad pattern to Taxes page in frontend/src/pages/Taxes/TaxHome.jsx
- [x] T004 Fix listRates to support all_branches in backend/routers/finance/taxes/rates.py

**Checkpoint**: Foundation ready - pattern application can now begin

---

## Phase 3: Priority 1 - High Traffic Pages (Accounting)

**Goal**: Apply Stable Component Identity to all Accounting pages

**Independent Validation**: Navigate to any Accounting page, switch branches, verify tab/form/filter state preserved

### Implementation for Accounting Pages

- [X] T005 [P] [P1] Apply pattern to AccountingHome in frontend/src/pages/Accounting/AccountingHome.jsx
- [X] T006 [P] [P1] Apply pattern to ChartOfAccounts in frontend/src/pages/Accounting/ChartOfAccounts.jsx
- [X] T007 [P] [P1] Apply pattern to JournalEntryList in frontend/src/pages/Accounting/JournalEntryList.jsx
- [X] T008 [P] [P1] Apply pattern to JournalEntryForm in frontend/src/pages/Accounting/JournalEntryForm.jsx
- [X] T009 [P] [P1] Apply pattern to GeneralLedger in frontend/src/pages/Accounting/GeneralLedger.jsx
- [X] T010 [P] [P1] Apply pattern to TrialBalance in frontend/src/pages/Accounting/TrialBalance.jsx
- [X] T011 [P] [P1] Apply pattern to BalanceSheet in frontend/src/pages/Accounting/BalanceSheet.jsx
- [X] T012 [P] [P1] Apply pattern to IncomeStatement in frontend/src/pages/Accounting/IncomeStatement.jsx
- [X] T013 [P] [P1] Apply pattern to CashFlowReport in frontend/src/pages/Accounting/CashFlowReport.jsx
- [X] T014 [P] [P1] Apply pattern to FiscalYears in frontend/src/pages/Accounting/FiscalYears.jsx
- [X] T015 [P] [P1] Apply pattern to Budgets in frontend/src/pages/Accounting/Budgets.jsx
- [X] T016 [P] [P1] Apply pattern to BudgetItems in frontend/src/pages/Accounting/BudgetItems.jsx
- [X] T017 [P] [P1] Apply pattern to BudgetReport in frontend/src/pages/Accounting/BudgetReport.jsx
- [X] T018 [P] [P1] Apply pattern to CostCenters in frontend/src/pages/Accounting/CostCenters/CostCenterList.jsx
- [X] T019 [P] [P1] Apply pattern to OpeningBalances in frontend/src/pages/Accounting/OpeningBalances.jsx
- [X] T020 [P] [P1] Apply pattern to ClosingEntries in frontend/src/pages/Accounting/ClosingEntries.jsx
- [X] T021 [P] [P1] Apply pattern to RecurringTemplates in frontend/src/pages/Accounting/RecurringTemplates.jsx
- [X] T022 [P] [P1] Apply pattern to PeriodComparison in frontend/src/pages/Accounting/PeriodComparison.jsx
- [X] T023 [P] [P1] Apply pattern to VATReport in frontend/src/pages/Accounting/VATReport.jsx
- [X] T024 [P] [P1] Apply pattern to TaxAudit in frontend/src/pages/Accounting/TaxAudit.jsx
- [X] T025 [P] [P1] Apply pattern to ZakatCalculator in frontend/src/pages/Accounting/ZakatCalculator.jsx
- [X] T026 [P] [P1] Apply pattern to RevenueRecognition in frontend/src/pages/Accounting/RevenueRecognition.jsx
- [X] T027 [P] [P1] Apply pattern to IntercompanyTransactions in frontend/src/pages/Accounting/IntercompanyTransactions.jsx

**Checkpoint**: All Accounting pages preserve UI state on branch switch

---

## Phase 4: Priority 1 - High Traffic Pages (Sales)

**Goal**: Apply Stable Component Identity to all Sales pages

**Independent Validation**: Navigate to any Sales page, switch branches, verify tab/form/filter state preserved

### Implementation for Sales Pages

- [X] T028 [P] [P1] Apply pattern to SalesHome in frontend/src/pages/Sales/SalesHome.jsx
- [X] T029 [P] [P1] Apply pattern to SalesQuotations in frontend/src/pages/Sales/SalesQuotations.jsx
- [X] T030 [P] [P1] Apply pattern to SalesQuotationForm in frontend/src/pages/Sales/SalesQuotationForm.jsx
- [X] T031 [P] [P1] Apply pattern to SalesOrders in frontend/src/pages/Sales/SalesOrders.jsx
- [X] T032 [P] [P1] Apply pattern to SalesOrderForm in frontend/src/pages/Sales/SalesOrderForm.jsx
- [X] T033 [P] [P1] Apply pattern to InvoiceList in frontend/src/pages/Sales/InvoiceList.jsx
- [X] T034 [P] [P1] Apply pattern to InvoiceForm in frontend/src/pages/Sales/InvoiceForm.jsx
- [X] T035 [P] [P1] Apply pattern to DeliveryOrders in frontend/src/pages/Sales/DeliveryOrders.jsx
- [X] T036 [P] [P1] Apply pattern to DeliveryOrderForm in frontend/src/pages/Sales/DeliveryOrderForm.jsx
- [X] T037 [P] [P1] Apply pattern to CustomerList in frontend/src/pages/Sales/CustomerList.jsx
- [X] T038 [P] [P1] Apply pattern to CustomerDetails in frontend/src/pages/Sales/CustomerDetails.jsx
- [X] T039 [P] [P1] Apply pattern to CustomerForm in frontend/src/pages/Sales/CustomerForm.jsx
- [X] T040 [P] [P1] Apply pattern to CustomerGroups in frontend/src/pages/Sales/CustomerGroups.jsx
- [X] T041 [P] [P1] Apply pattern to CustomerReceipts in frontend/src/pages/Sales/CustomerReceipts.jsx
- [X] T042 [P] [P1] Apply pattern to CustomerStatement in frontend/src/pages/Sales/CustomerStatement.jsx
- [X] T043 [P] [P1] Apply pattern to SalesReturns in frontend/src/pages/Sales/SalesReturns.jsx
- [X] T044 [P] [P1] Apply pattern to SalesReturnForm in frontend/src/pages/Sales/SalesReturnForm.jsx
- [X] T045 [P] [P1] Apply pattern to SalesCreditNotes in frontend/src/pages/Sales/SalesCreditNotes.jsx
- [X] T046 [P] [P1] Apply pattern to SalesDebitNotes in frontend/src/pages/Sales/SalesDebitNotes.jsx
- [X] T047 [P] [P1] Apply pattern to SalesCommissions in frontend/src/pages/Sales/SalesCommissions.jsx
- [X] T048 [P] [P1] Apply pattern to SalesReports in frontend/src/pages/Sales/SalesReports.jsx
- [X] T049 [P] [P1] Apply pattern to AgingReport in frontend/src/pages/Sales/AgingReport.jsx
- [X] T050 [P] [P1] Apply pattern to ContractList in frontend/src/pages/Sales/ContractList.jsx
- [X] T051 [P] [P1] Apply pattern to ContractForm in frontend/src/pages/Sales/ContractForm.jsx
- [X] T052 [P] [P1] Apply pattern to ContractAmendments in frontend/src/pages/Sales/ContractAmendments.jsx

**Checkpoint**: All Sales pages preserve UI state on branch switch

---

## Phase 5: Priority 1 - High Traffic Pages (Stock)

**Goal**: Apply Stable Component Identity to all Stock pages

**Independent Validation**: Navigate to any Stock page, switch branches, verify tab/form/filter state preserved

### Implementation for Stock Pages

- [X] T053 [P] [P1] Apply pattern to StockHome in frontend/src/pages/Stock/StockHome.jsx
- [X] T054 [P] [P1] Apply pattern to ProductList in frontend/src/pages/Stock/ProductList.jsx
- [X] T055 [P] [P1] Apply pattern to ProductForm in frontend/src/pages/Stock/ProductForm.jsx
- [X] T056 [P] [P1] Apply pattern to CategoryList in frontend/src/pages/Stock/CategoryList.jsx
- [X] T057 [P] [P1] Apply pattern to WarehouseList in frontend/src/pages/Stock/WarehouseList.jsx
- [X] T058 [P] [P1] Apply pattern to StockMovements in frontend/src/pages/Stock/StockMovements.jsx
- [X] T059 [P] [P1] Apply pattern to StockAdjustments in frontend/src/pages/Stock/StockAdjustments.jsx
- [X] T060 [P] [P1] Apply pattern to StockAdjustmentForm in frontend/src/pages/Stock/StockAdjustmentForm.jsx
- [X] T061 [P] [P1] Apply pattern to StockTransferForm in frontend/src/pages/Stock/StockTransferForm.jsx
- [X] T062 [P] [P1] Apply pattern to IncomingShipments in frontend/src/pages/Stock/IncomingShipments.jsx
- [X] T063 [P] [P1] Apply pattern to ShipmentList in frontend/src/pages/Stock/ShipmentList.jsx
- [X] T064 [P] [P1] Apply pattern to InventoryValuation in frontend/src/pages/Stock/InventoryValuation.jsx
- [X] T065 [P] [P1] Apply pattern to PriceLists in frontend/src/pages/Stock/PriceLists.jsx
- [X] T066 [P] [P1] Apply pattern to BatchList in frontend/src/pages/Stock/BatchList.jsx
- [X] T067 [P] [P1] Apply pattern to SerialList in frontend/src/pages/Stock/SerialList.jsx
- [X] T068 [P] [P1] Apply pattern to CycleCounts in frontend/src/pages/Stock/CycleCounts.jsx
- [X] T069 [P] [P1] Apply pattern to QualityInspections in frontend/src/pages/Stock/QualityInspections.jsx
- [X] T070 [P] [P1] Apply pattern to ProfitabilityReport in frontend/src/pages/Stock/ProfitabilityReport.jsx
- [X] T071 [P] [P1] Apply pattern to StockReports in frontend/src/pages/Stock/StockReports.jsx

**Checkpoint**: All Stock pages preserve UI state on branch switch

---

## Phase 6: Priority 1 - High Traffic Pages (Buying)

**Goal**: Apply Stable Component Identity to all Buying pages

**Independent Validation**: Navigate to any Buying page, switch branches, verify tab/form/filter state preserved

### Implementation for Buying Pages

- [X] T072 [P] [P1] Apply pattern to BuyingHome in frontend/src/pages/Buying/BuyingHome.jsx
- [X] T073 [P] [P1] Apply pattern to SupplierList in frontend/src/pages/Buying/SupplierList.jsx
- [X] T074 [P] [P1] Apply pattern to SupplierDetails in frontend/src/pages/Buying/SupplierDetails.jsx
- [X] T075 [P] [P1] Apply pattern to SupplierForm in frontend/src/pages/Buying/SupplierForm.jsx
- [X] T076 [P] [P1] Apply pattern to SupplierGroups in frontend/src/pages/Buying/SupplierGroups.jsx
- [X] T077 [P] [P1] Apply pattern to SupplierPayments in frontend/src/pages/Buying/SupplierPayments.jsx
- [X] T078 [P] [P1] Apply pattern to SupplierStatement in frontend/src/pages/Buying/SupplierStatement.jsx
- [X] T079 [P] [P1] Apply pattern to BuyingOrders in frontend/src/pages/Buying/BuyingOrders.jsx
- [X] T080 [P] [P1] Apply pattern to BuyingOrderForm in frontend/src/pages/Buying/BuyingOrderForm.jsx
- [X] T081 [P] [P1] Apply pattern to PurchaseInvoiceList in frontend/src/pages/Buying/PurchaseInvoiceList.jsx
- [X] T082 [P] [P1] Apply pattern to PurchaseInvoiceForm in frontend/src/pages/Buying/PurchaseInvoiceForm.jsx
- [X] T083 [P] [P1] Apply pattern to PurchaseOrderReceive in frontend/src/pages/Buying/PurchaseOrderReceive.jsx
- [X] T084 [P] [P1] Apply pattern to BuyingReturns in frontend/src/pages/Buying/BuyingReturns.jsx
- [X] T085 [P] [P1] Apply pattern to BuyingReturnForm in frontend/src/pages/Buying/BuyingReturnForm.jsx
- [X] T086 [P] [P1] Apply pattern to PurchaseCreditNotes in frontend/src/pages/Buying/PurchaseCreditNotes.jsx
- [X] T087 [P] [P1] Apply pattern to PurchaseDebitNotes in frontend/src/pages/Buying/PurchaseDebitNotes.jsx
- [X] T088 [P] [P1] Apply pattern to BuyingReports in frontend/src/pages/Buying/BuyingReports.jsx
- [X] T089 [P] [P1] Apply pattern to PurchasesAgingReport in frontend/src/pages/Buying/PurchasesAgingReport.jsx

**Checkpoint**: All Buying pages preserve UI state on branch switch

---

## Phase 7: Priority 2 - HR Pages

**Goal**: Apply Stable Component Identity to all HR pages

**Independent Validation**: Navigate to any HR page, switch branches, verify tab/form/filter state preserved

### Implementation for HR Pages

- [X] T090 [P] [P2] Apply pattern to Employees in frontend/src/pages/HR/Employees.jsx
- [X] T091 [P] [P2] Apply pattern to Payslips in frontend/src/pages/HR/Payslips.jsx
- [X] T092 [P] [P2] Apply pattern to PayrollDetails in frontend/src/pages/HR/PayrollDetails.jsx
- [X] T093 [P] [P2] Apply pattern to LeaveList in frontend/src/pages/HR/LeaveList.jsx
- [X] T094 [P] [P2] Apply pattern to LeaveCarryover in frontend/src/pages/HR/LeaveCarryover.jsx
- [X] T095 [P] [P2] Apply pattern to LoanList in frontend/src/pages/HR/LoanList.jsx
- [X] T096 [P] [P2] Apply pattern to Recruitment in frontend/src/pages/HR/Recruitment.jsx

**Checkpoint**: All HR pages preserve UI state on branch switch

---

## Phase 8: Priority 2 - Treasury Pages

**Goal**: Apply Stable Component Identity to all Treasury pages

**Independent Validation**: Navigate to any Treasury page, switch branches, verify tab/form/filter state preserved

### Implementation for Treasury Pages

- [X] T097 [P] [P2] Apply pattern to TreasuryHome in frontend/src/pages/Treasury/TreasuryHome.jsx
- [X] T098 [P] [P2] Apply pattern to TreasuryAccountList in frontend/src/pages/Treasury/TreasuryAccountList.jsx
- [X] T099 [P] [P2] Apply pattern to TreasuryBalancesReport in frontend/src/pages/Treasury/TreasuryBalancesReport.jsx
- [X] T100 [P] [P2] Apply pattern to TreasuryCashflowReport in frontend/src/pages/Treasury/TreasuryCashflowReport.jsx
- [X] T101 [P] [P2] Apply pattern to ReconciliationList in frontend/src/pages/Treasury/ReconciliationList.jsx
- [X] T102 [P] [P2] Apply pattern to ReconciliationForm in frontend/src/pages/Treasury/ReconciliationForm.jsx
- [X] T103 [P] [P2] Apply pattern to TransferForm in frontend/src/pages/Treasury/TransferForm.jsx
- [X] T104 [P] [P2] Apply pattern to BankImport in frontend/src/pages/Treasury/BankImport.jsx
- [X] T105 [P] [P2] Apply pattern to ChecksReceivable in frontend/src/pages/Treasury/ChecksReceivable.jsx
- [X] T106 [P] [P2] Apply pattern to ChecksPayable in frontend/src/pages/Treasury/ChecksPayable.jsx
- [X] T107 [P] [P2] Apply pattern to ChecksAgingReport in frontend/src/pages/Treasury/ChecksAgingReport.jsx
- [X] T108 [P] [P2] Apply pattern to NotesReceivable in frontend/src/pages/Treasury/NotesReceivable.jsx
- [X] T109 [P] [P2] Apply pattern to NotesPayable in frontend/src/pages/Treasury/NotesPayable.jsx
- [X] T110 [P] [P2] Apply pattern to ExpenseForm in frontend/src/pages/Treasury/ExpenseForm.jsx

**Checkpoint**: All Treasury pages preserve UI state on branch switch

---

## Phase 9: Priority 2 - Reports Pages

**Goal**: Apply Stable Component Identity to all Reports pages

**Independent Validation**: Navigate to any Reports page, switch branches, verify tab/form/filter state preserved

### Implementation for Reports Pages

- [X] T111 [P] [P2] Apply pattern to ScheduledReports in frontend/src/pages/Reports/ScheduledReports.jsx
- [X] T112 [P] [P2] Apply pattern to CashFlowIAS7 in frontend/src/pages/Reports/CashFlowIAS7.jsx
- [X] T113 [P] [P2] Apply pattern to DetailedProfitLoss in frontend/src/pages/Reports/DetailedProfitLoss.jsx
- [X] T114 [P] [P2] Apply pattern to FXGainLossReport in frontend/src/pages/Reports/FXGainLossReport.jsx

**Checkpoint**: All Reports pages preserve UI state on branch switch

---

## Phase 10: Priority 3 - Assets Pages

**Goal**: Apply Stable Component Identity to all Assets pages

**Independent Validation**: Navigate to any Assets page, switch branches, verify tab/form/filter state preserved

### Implementation for Assets Pages

- [X] T115 [P] [P3] Apply pattern to AssetList in frontend/src/pages/Assets/AssetList.jsx
- [X] T116 [P] [P3] Apply pattern to AssetManagement in frontend/src/pages/Assets/AssetManagement.jsx
- [X] T117 [P] [P3] Apply pattern to AssetDetails in frontend/src/pages/Assets/AssetDetails.jsx
- [X] T118 [P] [P3] Apply pattern to AssetReports in frontend/src/pages/Assets/AssetReports.jsx
- [X] T119 [P] [P3] Apply pattern to ImpairmentTest in frontend/src/pages/Assets/ImpairmentTest.jsx
- [X] T120 [P] [P3] Apply pattern to LeaseContracts in frontend/src/pages/Assets/LeaseContracts.jsx

**Checkpoint**: All Assets pages preserve UI state on branch switch

---

## Phase 11: Priority 3 - Other Pages

**Goal**: Apply Stable Component Identity to remaining pages

**Independent Validation**: Navigate to any remaining page, switch branches, verify tab/form/filter state preserved

### Implementation for Other Pages

- [X] T121 [P] [P3] Apply pattern to Dashboard in frontend/src/pages/Dashboard.jsx
- [X] T122 [P] [P3] Apply pattern to RoleDashboard in frontend/src/pages/KPI/RoleDashboard.jsx
- [X] T123 [P] [P3] Apply pattern to POSHome in frontend/src/pages/POS/POSHome.jsx
- [X] T124 [P] [P3] Apply pattern to ProjectList in frontend/src/pages/Projects/ProjectList.jsx
- [X] T125 [P] [P3] Apply pattern to ProjectDetails in frontend/src/pages/Projects/ProjectDetails.jsx
- [X] T126 [P] [P3] Apply pattern to Branches in frontend/src/pages/Settings/Branches.jsx
- [X] T127 [P] [P3] Apply pattern to ExpenseForm in frontend/src/pages/Expenses/ExpenseForm.jsx
- [X] T128 [P] [P3] Apply pattern to ExpenseList in frontend/src/pages/Expenses/ExpenseList.jsx
- [X] T129 [P] [P3] Apply pattern to PaymentForm in frontend/src/pages/Purchases/PaymentForm.jsx
- [X] T130 [P] [P3] Apply pattern to SupplierPayments in frontend/src/pages/Purchases/SupplierPayments.jsx

**Checkpoint**: All remaining pages preserve UI state on branch switch

---

## Phase 12: Priority 4 - Components

**Goal**: Apply Stable Component Identity to shared components

**Independent Validation**: Use any component that uses useBranch, switch branches, verify state preserved

### Implementation for Components

- [X] T131 [P] [P4] Apply pattern to ProductTaxSelector in frontend/src/components/Tax/ProductTaxSelector.jsx
- [X] T132 [P] [P4] Apply pattern to ModuleKPISection in frontend/src/components/kpi/ModuleKPISection.jsx

**Checkpoint**: All components preserve UI state on branch switch

---

## Phase 13: Polish & Cross-Cutting Concerns

**Purpose**: Validation and cleanup

- [X] T133 Run quickstart.md validation across all pages
- [X] T134 Verify no key props depend on currentBranch in any component
- [X] T135 Verify all pages use 300ms debounce
- [X] T136 Verify all pages show subtle spinner on branch switch (not full-page loading)
- [X] T137 Verify all pages use showToast for errors (not full-page error states)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: No dependencies - can start immediately
- **Phase 2 (Foundational)**: ALREADY COMPLETE
- **Phases 3-6 (P1 Pages)**: Can start after Phase 1, can run in parallel
- **Phases 7-9 (P2 Pages)**: Can start after Phase 1, can run in parallel
- **Phases 10-11 (P3 Pages)**: Can start after Phase 1, can run in parallel
- **Phase 12 (Components)**: Can start after Phase 1, can run in parallel
- **Phase 13 (Polish)**: Depends on all other phases complete

### Parallel Opportunities

- All tasks marked [P] can run in parallel within their phase
- Different phases (P1, P2, P3, P4) can run in parallel since they touch different files
- Within each phase, all tasks touch different files and can run in parallel

### Within Each Phase

- Each task modifies a single file
- No dependencies between tasks in the same phase
- All tasks follow the same pattern (from plan.md template)

---

## Parallel Example: Accounting Pages

```bash
# Launch all Accounting page tasks together:
Task: "Apply pattern to AccountingHome in frontend/src/pages/Accounting/AccountingHome.jsx"
Task: "Apply pattern to ChartOfAccounts in frontend/src/pages/Accounting/ChartOfAccounts.jsx"
Task: "Apply pattern to JournalEntryList in frontend/src/pages/Accounting/JournalEntryList.jsx"
# ... etc (all 23 Accounting tasks)
```

---

## Implementation Strategy

### MVP First (Phase 1 + Phase 3 Accounting)

1. Complete Phase 1: Setup (create useDebounceBranch hook)
2. Complete Phase 3: Accounting pages (23 files)
3. **STOP and VALIDATE**: Test branch switching on Accounting pages
4. Deploy/demo if ready

### Incremental Delivery

1. Complete Setup -> Hook ready
2. Add Accounting pages -> Validate -> Deploy (MVP)
3. Add Sales pages -> Validate -> Deploy
4. Add Stock pages -> Validate -> Deploy
5. Add Buying pages -> Validate -> Deploy
6. Add HR/Treasury/Reports -> Validate -> Deploy
7. Add Assets/Other -> Validate -> Deploy
8. Add Components -> Validate -> Deploy
9. Polish -> Final validation

### Parallel Team Strategy

With multiple developers:

1. Team completes Setup together (Phase 1)
2. Once hook is ready:
   - Developer A: Accounting pages (Phase 3)
   - Developer B: Sales pages (Phase 4)
   - Developer C: Stock pages (Phase 5)
   - Developer D: Buying pages (Phase 6)
3. Once P1 complete:
   - Developer A: HR pages (Phase 7)
   - Developer B: Treasury pages (Phase 8)
   - Developer C: Reports pages (Phase 9)
4. Phases 10-12 can be distributed among team

---

## Notes

- [P] tasks = different files, no dependencies
- [Priority] label maps task to implementation priority from plan.md
- Each phase should be independently completable and verifiable
- Commit after each task or logical group
- Stop at any checkpoint to validate independently
- Pattern template from plan.md must be applied consistently to all files
- TaxHome.jsx serves as the reference implementation

---

## Summary

| Phase | Priority | Task Count | Files |
|-------|----------|------------|-------|
| Setup | - | 1 | 1 hook |
| Foundational | - | 3 (complete) | 3 files |
| Accounting | P1 | 23 | 23 files |
| Sales | P1 | 25 | 25 files |
| Stock | P1 | 19 | 19 files |
| Buying | P1 | 18 | 18 files |
| HR | P2 | 7 | 7 files |
| Treasury | P2 | 14 | 14 files |
| Reports | P2 | 4 | 4 files |
| Assets | P3 | 6 | 6 files |
| Other | P3 | 10 | 10 files |
| Components | P4 | 2 | 2 files |
| Polish | - | 5 | - |
| **Total** | - | **137** | **129 files** |
