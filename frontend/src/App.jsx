import React, { useEffect, useState, Suspense } from 'react'
import { Routes, Route, Navigate, useLocation } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { useToast } from './context/ToastContext'
import { useBranch } from './context/BranchContext'
import { isAuthenticated, hasPermission, getUser, bootstrapAuth } from './utils/auth'
import { hasIndustryTypeSet } from './hooks/useIndustryType'
import { requestManager } from './utils/requestManager'
import { PageLoading } from './components/common/LoadingStates'
import Layout from './components/Layout'
import FloatingThemeToggle from './components/common/FloatingThemeToggle'
import ErrorBoundary from './components/ErrorBoundary'

// Suspense fallback uses unified PageLoading (auto-translated)
const PageLoader = () => <PageLoading />

// Pages
const Login = React.lazy(() => import('./pages/Login'))
const Register = React.lazy(() => import('./pages/Register'))
const Dashboard = React.lazy(() => import('./pages/Dashboard'))
const UserProfile = React.lazy(() => import('./pages/UserProfile'))

// Forgot/Reset Password
const ForgotPassword = React.lazy(() => import('./pages/ForgotPassword'))
const ResetPassword = React.lazy(() => import('./pages/ResetPassword'))

// 404 Page
const NotFound = React.lazy(() => import('./pages/NotFound'))

// POS
const POSHome = React.lazy(() => import('./pages/POS/POSHome'))
const POSInterface = React.lazy(() => import('./pages/POS/POSInterface'))
const Promotions = React.lazy(() => import('./pages/POS/Promotions'))
const LoyaltyPrograms = React.lazy(() => import('./pages/POS/LoyaltyPrograms'))
const TableManagement = React.lazy(() => import('./pages/POS/TableManagement'))
const KitchenDisplay = React.lazy(() => import('./pages/POS/KitchenDisplay'))
const POSOfflineManager = React.lazy(() => import('./pages/POS/POSOfflineManager'))
const ThermalPrintSettings = React.lazy(() => import('./pages/POS/ThermalPrintSettings'))
const CustomerDisplay = React.lazy(() => import('./pages/POS/CustomerDisplay'))

// Manufacturing
const ManufacturingHome = React.lazy(() => import('./pages/Manufacturing/ManufacturingHome'))
const WorkCenters = React.lazy(() => import('./pages/Manufacturing/WorkCenters'))
const Routings = React.lazy(() => import('./pages/Manufacturing/Routings'))
const BOMs = React.lazy(() => import('./pages/Manufacturing/BOMs'))
const ProductionOrders = React.lazy(() => import('./pages/Manufacturing/ProductionOrders'))
const ProductionOrderDetails = React.lazy(() => import('./pages/Manufacturing/ProductionOrderDetails'))
const JobCards = React.lazy(() => import('./pages/Manufacturing/JobCards'))
const MRPView = React.lazy(() => import('./pages/Manufacturing/MRPView'))
const MRPPlanning = React.lazy(() => import('./pages/Manufacturing/MRPPlanning'))
const EquipmentMaintenance = React.lazy(() => import('./pages/Manufacturing/EquipmentMaintenance'))
const ProductionSchedule = React.lazy(() => import('./pages/Manufacturing/ProductionSchedule'))
const DirectLaborReport = React.lazy(() => import('./pages/Manufacturing/DirectLaborReport'))
const ProductionAnalytics = React.lazy(() => import('./pages/Manufacturing/ProductionAnalytics'))
const WorkOrderStatusReport = React.lazy(() => import('./pages/Manufacturing/WorkOrderStatusReport'))

// Manufacturing Costing
const ManufacturingCosting = React.lazy(() => import('./pages/Manufacturing/ManufacturingCosting'))
const CapacityPlanning = React.lazy(() => import('./pages/Manufacturing/CapacityPlanning'))

// Shop Floor Control
const ShopFloorDashboard = React.lazy(() => import('./pages/ShopFloor/ShopFloorDashboard'))
const OperationEntry = React.lazy(() => import('./pages/ShopFloor/OperationEntry'))

// Routing Management
const RoutingList = React.lazy(() => import('./pages/Routing/RoutingList'))
const RoutingForm = React.lazy(() => import('./pages/Routing/RoutingForm'))

// Time Tracking
const TimesheetWeek = React.lazy(() => import('./pages/TimeTracking/TimesheetWeek'))
const TeamTimesheets = React.lazy(() => import('./pages/TimeTracking/TeamTimesheets'))
const ProjectProfitability = React.lazy(() => import('./pages/TimeTracking/ProjectProfitability'))

// Resource Planning
const AvailabilityCalendar = React.lazy(() => import('./pages/ResourcePlanning/AvailabilityCalendar'))
const AllocationForm = React.lazy(() => import('./pages/ResourcePlanning/AllocationForm'))
const ProjectResources = React.lazy(() => import('./pages/ResourcePlanning/ProjectResources'))

// Accounting
const AccountingHome = React.lazy(() => import('./pages/Accounting/AccountingHome'))
const ChartOfAccounts = React.lazy(() => import('./pages/Accounting/ChartOfAccounts'))
const JournalEntryForm = React.lazy(() => import('./pages/Accounting/JournalEntryForm'))
const JournalEntryList = React.lazy(() => import('./pages/Accounting/JournalEntryList'))
const FiscalYears = React.lazy(() => import('./pages/Accounting/FiscalYears'))
const RecurringTemplates = React.lazy(() => import('./pages/Accounting/RecurringTemplates'))
const PeriodComparison = React.lazy(() => import('./pages/Accounting/PeriodComparison'))
const OpeningBalances = React.lazy(() => import('./pages/Accounting/OpeningBalances'))
const ClosingEntries = React.lazy(() => import('./pages/Accounting/ClosingEntries'))
const CostCenterList = React.lazy(() => import('./pages/Accounting/CostCenters/CostCenterList'))
const Budgets = React.lazy(() => import('./pages/Accounting/Budgets'))
const BudgetItems = React.lazy(() => import('./pages/Accounting/BudgetItems'))
const BudgetReport = React.lazy(() => import('./pages/Accounting/BudgetReport'))
const VATReport = React.lazy(() => import('./pages/Accounting/VATReport'))
const TaxAudit = React.lazy(() => import('./pages/Accounting/TaxAudit'))
const CashFlowReport = React.lazy(() => import('./pages/Accounting/CashFlowReport'))
const InventoryValuation = React.lazy(() => import('./pages/Stock/InventoryValuation'))
const TrialBalance = React.lazy(() => import('./pages/Accounting/TrialBalance'))
const GeneralLedger = React.lazy(() => import('./pages/Accounting/GeneralLedger'))
const IncomeStatement = React.lazy(() => import('./pages/Accounting/IncomeStatement'))
const BalanceSheet = React.lazy(() => import('./pages/Accounting/BalanceSheet'))
const CurrencyList = React.lazy(() => import('./pages/Accounting/CurrencyList'))

// Zakat & Fiscal Locks
const ZakatCalculator = React.lazy(() => import('./pages/Accounting/ZakatCalculator'))
const FiscalPeriodLocks = React.lazy(() => import('./pages/Accounting/FiscalPeriodLocks'))
const IntercompanyTransactions = React.lazy(() => import('./pages/Accounting/IntercompanyTransactions'))
const RevenueRecognition = React.lazy(() => import('./pages/Accounting/RevenueRecognition'))

// Intercompany v2 (Entity Groups, Consolidation, Mappings)
const EntityGroupTree = React.lazy(() => import('./pages/Intercompany/EntityGroupTree'))
const IntercompanyTransactionList = React.lazy(() => import('./pages/Intercompany/TransactionList'))
const IntercompanyTransactionForm = React.lazy(() => import('./pages/Intercompany/TransactionForm'))
const ConsolidationView = React.lazy(() => import('./pages/Intercompany/ConsolidationView'))
const IntercompanyAccountMappings = React.lazy(() => import('./pages/Intercompany/AccountMappings'))

// Admin
const CompanyList = React.lazy(() => import('./pages/Admin/CompanyList'))
const AuditLogs = React.lazy(() => import('./pages/Admin/AuditLogs'))
const RoleManagement = React.lazy(() => import('./pages/Admin/RoleManagement'))
const SecurityEvents = React.lazy(() => import('./pages/Admin/SecurityEvents'))

// Backup Management
const BackupManagement = React.lazy(() => import('./pages/Admin/BackupManagement'))

// Approvals
const ApprovalsPage = React.lazy(() => import('./pages/Approvals/ApprovalsPage'))
const WorkflowEditor = React.lazy(() => import('./pages/Approvals/WorkflowEditor'))

// Data Import
const DataImportPage = React.lazy(() => import('./pages/DataImport/DataImportPage'))

// Sales
const SalesHome = React.lazy(() => import('./pages/Sales/SalesHome'))
const CustomerList = React.lazy(() => import('./pages/Sales/CustomerList'))
const CustomerForm = React.lazy(() => import('./pages/Sales/CustomerForm'))
const CustomerDetails = React.lazy(() => import('./pages/Sales/CustomerDetails'))
const InvoiceList = React.lazy(() => import('./pages/Sales/InvoiceList'))
const InvoiceForm = React.lazy(() => import('./pages/Sales/InvoiceForm'))
const InvoiceDetails = React.lazy(() => import('./pages/Sales/InvoiceDetails'))
const SalesOrders = React.lazy(() => import('./pages/Sales/SalesOrders'))
const SalesOrderForm = React.lazy(() => import('./pages/Sales/SalesOrderForm'))
const SalesOrderDetails = React.lazy(() => import('./pages/Sales/SalesOrderDetails'))
const SalesQuotations = React.lazy(() => import('./pages/Sales/SalesQuotations'))
const SalesQuotationForm = React.lazy(() => import('./pages/Sales/SalesQuotationForm'))
const SalesQuotationDetails = React.lazy(() => import('./pages/Sales/SalesQuotationDetails'))
const CustomerGroups = React.lazy(() => import('./pages/Sales/CustomerGroups'))
const SalesReturns = React.lazy(() => import('./pages/Sales/SalesReturns'))
const SalesReturnForm = React.lazy(() => import('./pages/Sales/SalesReturnForm'))
const SalesReturnDetails = React.lazy(() => import('./pages/Sales/SalesReturnDetails'))
const CustomerReceipts = React.lazy(() => import('./pages/Sales/CustomerReceipts'))
const ReceiptForm = React.lazy(() => import('./pages/Sales/ReceiptForm'))
const ReceiptDetails = React.lazy(() => import('./pages/Sales/ReceiptDetails'))
const SalesReports = React.lazy(() => import('./pages/Sales/SalesReports'))
const CustomerStatement = React.lazy(() => import('./pages/Sales/CustomerStatement'))
const AgingReport = React.lazy(() => import('./pages/Sales/AgingReport'))
const ContractList = React.lazy(() => import('./pages/Sales/ContractList'))
const ContractForm = React.lazy(() => import('./pages/Sales/ContractForm'))
const ContractDetails = React.lazy(() => import('./pages/Sales/ContractDetails'))
const SalesCreditNotes = React.lazy(() => import('./pages/Sales/SalesCreditNotes'))
const SalesDebitNotes = React.lazy(() => import('./pages/Sales/SalesDebitNotes'))
const SalesCommissions = React.lazy(() => import('./pages/Sales/SalesCommissions'))

// Contract Amendments
const ContractAmendments = React.lazy(() => import('./pages/Sales/ContractAmendments'))

// Delivery Orders
const DeliveryOrders = React.lazy(() => import('./pages/Sales/DeliveryOrders'))
const DeliveryOrderForm = React.lazy(() => import('./pages/Sales/DeliveryOrderForm'))
const DeliveryOrderDetails = React.lazy(() => import('./pages/Sales/DeliveryOrderDetails'))
const ConfigurableProducts = React.lazy(() => import('./pages/CPQ/ConfigurableProducts'))
const Configurator = React.lazy(() => import('./pages/CPQ/Configurator'))
const QuoteList = React.lazy(() => import('./pages/CPQ/QuoteList'))
const QuoteDetail = React.lazy(() => import('./pages/CPQ/QuoteDetail'))

// Demand Forecast
const DemandForecastList = React.lazy(() => import('./pages/Forecast/ForecastList'))
const DemandForecastGenerate = React.lazy(() => import('./pages/Forecast/ForecastGenerate'))
const DemandForecastDetail = React.lazy(() => import('./pages/Forecast/ForecastDetail'))

// Stock
const StockHome = React.lazy(() => import('./pages/Stock/StockHome'))
const ProductList = React.lazy(() => import('./pages/Stock/ProductList'))
const ProductForm = React.lazy(() => import('./pages/Stock/ProductForm'))
const CategoryList = React.lazy(() => import('./pages/Stock/CategoryList'))
const WarehouseList = React.lazy(() => import('./pages/Stock/WarehouseList'))
const WarehouseDetails = React.lazy(() => import('./pages/Stock/WarehouseDetails'))
const StockTransferForm = React.lazy(() => import('./pages/Stock/StockTransferForm'))
const StockShipmentForm = React.lazy(() => import('./pages/Stock/StockShipmentForm'))
const ShipmentList = React.lazy(() => import('./pages/Stock/ShipmentList'))
const IncomingShipments = React.lazy(() => import('./pages/Stock/IncomingShipments'))
const ShipmentDetails = React.lazy(() => import('./pages/Stock/ShipmentDetails'))
const PriceLists = React.lazy(() => import('./pages/Stock/PriceLists'))
const PriceListItems = React.lazy(() => import('./pages/Stock/PriceListItems'))
 const StockReports = React.lazy(() => import('./pages/Stock/StockReports'))
 const StockMovements = React.lazy(() => import('./pages/Stock/StockMovements'))
 const ProfitabilityReport = React.lazy(() => import('./pages/Stock/ProfitabilityReport'))
 const StockAdjustments = React.lazy(() => import('./pages/Stock/StockAdjustments'))
 const StockAdjustmentForm = React.lazy(() => import('./pages/Stock/StockAdjustmentForm'))
 const BatchList = React.lazy(() => import('./pages/Stock/BatchList'))
const SerialList = React.lazy(() => import('./pages/Stock/SerialList'))
const QualityInspections = React.lazy(() => import('./pages/Stock/QualityInspections'))
const CycleCounts = React.lazy(() => import('./pages/Stock/CycleCounts'))

// Buying
const BuyingHome = React.lazy(() => import('./pages/Buying/BuyingHome'))
const SupplierList = React.lazy(() => import('./pages/Buying/SupplierList'))
const SupplierForm = React.lazy(() => import('./pages/Buying/SupplierForm'))
const SupplierDetails = React.lazy(() => import('./pages/Buying/SupplierDetails'))
const PurchaseInvoiceList = React.lazy(() => import('./pages/Buying/PurchaseInvoiceList'))
const PurchaseInvoiceForm = React.lazy(() => import('./pages/Buying/PurchaseInvoiceForm'))
const PurchaseInvoiceDetails = React.lazy(() => import('./pages/Buying/PurchaseInvoiceDetails'))
const BuyingReports = React.lazy(() => import('./pages/Buying/BuyingReports'))
const SupplierStatement = React.lazy(() => import('./pages/Buying/SupplierStatement'))
const SupplierGroups = React.lazy(() => import('./pages/Buying/SupplierGroups'))
const BuyingReturns = React.lazy(() => import('./pages/Buying/BuyingReturns'))
const BuyingReturnForm = React.lazy(() => import('./pages/Buying/BuyingReturnForm'))
const BuyingReturnDetails = React.lazy(() => import('./pages/Buying/BuyingReturnDetails'))
const BuyingOrders = React.lazy(() => import('./pages/Buying/BuyingOrders'))
const BuyingOrderForm = React.lazy(() => import('./pages/Buying/BuyingOrderForm'))
const BuyingOrderDetails = React.lazy(() => import('./pages/Buying/PurchaseOrderDetails'))
const PurchaseOrderReceive = React.lazy(() => import('./pages/Buying/PurchaseOrderReceive'))
const SupplierPayments = React.lazy(() => import('./pages/Buying/SupplierPayments'))
const PurchaseCreditNotes = React.lazy(() => import('./pages/Buying/PurchaseCreditNotes'))
const PurchaseDebitNotes = React.lazy(() => import('./pages/Buying/PurchaseDebitNotes'))
const RFQList = React.lazy(() => import('./pages/Buying/RFQList'))
const SupplierRatings = React.lazy(() => import('./pages/Buying/SupplierRatings'))
const PurchaseAgreements = React.lazy(() => import('./pages/Buying/PurchaseAgreements'))

// Blanket Purchase Orders
const BlanketPOList = React.lazy(() => import('./pages/BlanketPO/BlanketPOList'))
const BlanketPOForm = React.lazy(() => import('./pages/BlanketPO/BlanketPOForm'))
const BlanketPODetail = React.lazy(() => import('./pages/BlanketPO/BlanketPODetail'))

// Landed Costs
const LandedCosts = React.lazy(() => import('./pages/Buying/LandedCosts'))
const LandedCostDetails = React.lazy(() => import('./pages/Buying/LandedCostDetails'))

// Treasury
const TreasuryHome = React.lazy(() => import('./pages/Treasury/TreasuryHome'))
const TreasuryAccountList = React.lazy(() => import('./pages/Treasury/TreasuryAccountList'))
const TreasuryExpenseForm = React.lazy(() => import('./pages/Treasury/ExpenseForm'))
const TransferForm = React.lazy(() => import('./pages/Treasury/TransferForm'))
const ReconciliationList = React.lazy(() => import('./pages/Treasury/ReconciliationList'))
const ReconciliationForm = React.lazy(() => import('./pages/Treasury/ReconciliationForm'))
const TreasuryBalancesReport = React.lazy(() => import('./pages/Treasury/TreasuryBalancesReport'))
const TreasuryCashflowReport = React.lazy(() => import('./pages/Treasury/TreasuryCashflowReport'))
const ChecksReceivable = React.lazy(() => import('./pages/Treasury/ChecksReceivable'))
const ChecksPayable = React.lazy(() => import('./pages/Treasury/ChecksPayable'))
const NotesReceivable = React.lazy(() => import('./pages/Treasury/NotesReceivable'))
const NotesPayable = React.lazy(() => import('./pages/Treasury/NotesPayable'))

// Bank Import
const BankImport = React.lazy(() => import('./pages/Treasury/BankImport'))

// Cash Flow Forecast
const ForecastList = React.lazy(() => import('./pages/CashFlow/ForecastList'))
const ForecastGenerate = React.lazy(() => import('./pages/CashFlow/ForecastGenerate'))
const ForecastDetail = React.lazy(() => import('./pages/CashFlow/ForecastDetail'))

// Subscription Billing
const SubscriptionHome = React.lazy(() => import('./pages/Subscription/SubscriptionHome'))
const SubscriptionPlanList = React.lazy(() => import('./pages/Subscription/PlanList'))
const SubscriptionPlanForm = React.lazy(() => import('./pages/Subscription/PlanForm'))
const SubscriptionEnrollmentList = React.lazy(() => import('./pages/Subscription/EnrollmentList'))
const SubscriptionEnrollmentDetail = React.lazy(() => import('./pages/Subscription/EnrollmentDetail'))
const SubscriptionEnrollmentForm = React.lazy(() => import('./pages/Subscription/EnrollmentForm'))

// HR
const HRHome = React.lazy(() => import('./pages/HR/HRHome'))
const Employees = React.lazy(() => import('./pages/HR/Employees'))
const PayrollList = React.lazy(() => import('./pages/HR/PayrollList'))
const PayrollDetails = React.lazy(() => import('./pages/HR/PayrollDetails'))
const DepartmentList = React.lazy(() => import('./pages/HR/DepartmentList'))
const PositionList = React.lazy(() => import('./pages/HR/PositionList'))
const LoanList = React.lazy(() => import('./pages/HR/LoanList'))
const LeaveList = React.lazy(() => import('./pages/HR/LeaveList'))
const Attendance = React.lazy(() => import('./pages/HR/Attendance'))
const HRReports = React.lazy(() => import('./pages/HR/Reports/HRReports'))
const LeaveReport = React.lazy(() => import('./pages/HR/Reports/LeaveReport'))
const PayrollReport = React.lazy(() => import('./pages/HR/Reports/PayrollReport'))

// HR Advanced (Phase 4)
const SalaryStructures = React.lazy(() => import('./pages/HR/SalaryStructures'))
const OvertimeRequests = React.lazy(() => import('./pages/HR/OvertimeRequests'))
const GOSISettings = React.lazy(() => import('./pages/HR/GOSISettings'))
const EmployeeDocuments = React.lazy(() => import('./pages/HR/EmployeeDocuments'))
const PerformanceReviews = React.lazy(() => import('./pages/HR/PerformanceReviews'))
const CycleList = React.lazy(() => import('./pages/Performance/CycleList'))
const CycleForm = React.lazy(() => import('./pages/Performance/CycleForm'))
const MyReviews = React.lazy(() => import('./pages/Performance/MyReviews'))
const TeamReviews = React.lazy(() => import('./pages/Performance/TeamReviews'))
const SelfAssessment = React.lazy(() => import('./pages/Performance/SelfAssessment'))
const ManagerReview = React.lazy(() => import('./pages/Performance/ManagerReview'))
const ReviewResult = React.lazy(() => import('./pages/Performance/ReviewResult'))
const TrainingPrograms = React.lazy(() => import('./pages/HR/TrainingPrograms'))
const Violations = React.lazy(() => import('./pages/HR/Violations'))
const CustodyManagement = React.lazy(() => import('./pages/HR/CustodyManagement'))
const Payslips = React.lazy(() => import('./pages/HR/Payslips'))
const LeaveCarryover = React.lazy(() => import('./pages/HR/LeaveCarryover'))
const Recruitment = React.lazy(() => import('./pages/HR/Recruitment'))

// WPS & Saudization (SA-specific)
const WPSExport = React.lazy(() => import('./pages/HR/WPSExport'))
const SaudizationDashboard = React.lazy(() => import('./pages/HR/SaudizationDashboard'))
const EOSSettlement = React.lazy(() => import('./pages/HR/EOSSettlement'))

// Employee Self-Service (US6)
const SelfServiceDashboard = React.lazy(() => import('./pages/SelfService/EmployeeDashboard'))
const SelfServiceLeaveForm = React.lazy(() => import('./pages/SelfService/LeaveRequestForm'))
const SelfServicePayslips = React.lazy(() => import('./pages/SelfService/PayslipList'))
const SelfServicePayslipDetail = React.lazy(() => import('./pages/SelfService/PayslipDetail'))
const SelfServiceProfile = React.lazy(() => import('./pages/SelfService/ProfileEdit'))
const SelfServiceTeamRequests = React.lazy(() => import('./pages/SelfService/TeamRequests'))

// Assets
const AssetList = React.lazy(() => import('./pages/Assets/AssetList'))
const AssetForm = React.lazy(() => import('./pages/Assets/AssetForm'))
const AssetDetails = React.lazy(() => import('./pages/Assets/AssetDetails'))
const AssetManagement = React.lazy(() => import('./pages/Assets/AssetManagement'))
const LeaseContracts = React.lazy(() => import('./pages/Assets/LeaseContracts'))
const ImpairmentTest = React.lazy(() => import('./pages/Assets/ImpairmentTest'))

// Projects
const ProjectList = React.lazy(() => import('./pages/Projects/ProjectList'))
const ProjectForm = React.lazy(() => import('./pages/Projects/ProjectForm'))
const ProjectDetails = React.lazy(() => import('./pages/Projects/ProjectDetails'))
const ResourceManagement = React.lazy(() => import('./pages/Projects/ResourceManagement'))
const ProjectFinancialsReport = React.lazy(() => import('./pages/Projects/ProjectFinancialsReport'))
const ResourceUtilizationReport = React.lazy(() => import('./pages/Projects/ResourceUtilizationReport'))
const ProjectRisks = React.lazy(() => import('./pages/Projects/ProjectRisks'))
const GanttChart = React.lazy(() => import('./pages/Projects/GanttChart'))
const Timesheets = React.lazy(() => import('./pages/Projects/Timesheets'))

// Expenses
const ExpenseList = React.lazy(() => import('./pages/Expenses/ExpenseList'))
const ExpenseForm = React.lazy(() => import('./pages/Expenses/ExpenseForm'))
const ExpenseDetails = React.lazy(() => import('./pages/Expenses/ExpenseDetails'))
const ExpensePolicies = React.lazy(() => import('./pages/Expenses/ExpensePolicies'))

// Taxes
const TaxHome = React.lazy(() => import('./pages/Taxes/TaxHome'))
const TaxReturnForm = React.lazy(() => import('./pages/Taxes/TaxReturnForm'))
const TaxReturnDetails = React.lazy(() => import('./pages/Taxes/TaxReturnDetails'))
const WithholdingTax = React.lazy(() => import('./pages/Taxes/WithholdingTax'))
const TaxCompliance = React.lazy(() => import('./pages/Taxes/TaxCompliance'))
const TaxCalendar = React.lazy(() => import('./pages/Taxes/TaxCalendar'))

// CRM
const CRMHome = React.lazy(() => import('./pages/CRM/CRMHome'))
const Opportunities = React.lazy(() => import('./pages/CRM/Opportunities'))
const SupportTickets = React.lazy(() => import('./pages/CRM/SupportTickets'))
const MarketingCampaigns = React.lazy(() => import('./pages/CRM/MarketingCampaigns'))
const CampaignList = React.lazy(() => import('./pages/Campaign/CampaignList'))
const CampaignForm = React.lazy(() => import('./pages/Campaign/CampaignForm'))
const CampaignReport = React.lazy(() => import('./pages/Campaign/CampaignReport'))
const KnowledgeBase = React.lazy(() => import('./pages/CRM/KnowledgeBase'))
const LeadScoring = React.lazy(() => import('./pages/CRM/LeadScoring'))
const CustomerSegments = React.lazy(() => import('./pages/CRM/CustomerSegments'))
const PipelineAnalytics = React.lazy(() => import('./pages/CRM/PipelineAnalytics'))
const CRMContacts = React.lazy(() => import('./pages/CRM/CRMContacts'))
const SalesForecasts = React.lazy(() => import('./pages/CRM/SalesForecasts'))

// Services
const ServicesHome = React.lazy(() => import('./pages/Services/ServicesHome'))
const ServiceRequests = React.lazy(() => import('./pages/Services/ServiceRequests'))
const DocumentManagement = React.lazy(() => import('./pages/Services/DocumentManagement'))

// Setup Wizard
const IndustrySetup = React.lazy(() => import('./pages/Setup/IndustrySetup'))
const ModuleCustomization = React.lazy(() => import('./pages/Setup/ModuleCustomization'))

// Common & Settings
const CompanySettings = React.lazy(() => import('./pages/Settings/CompanySettings'))
const CompanyProfile = React.lazy(() => import('./pages/Settings/CompanyProfile'))
const Branches = React.lazy(() => import('./pages/Settings/Branches'))
const CostingPolicy = React.lazy(() => import('./pages/Settings/CostingPolicy'))
const ApiKeys = React.lazy(() => import('./pages/Settings/ApiKeys'))
const WebhooksPage = React.lazy(() => import('./pages/Settings/Webhooks'))

// Print Templates
const PrintTemplates = React.lazy(() => import('./pages/Settings/PrintTemplates'))

// Smart Alerts (T4.3)
const SmartAlerts = React.lazy(() => import('./pages/Settings/SmartAlerts'))

// Email Templates (T4.11)
const EmailTemplates = React.lazy(() => import('./pages/Settings/EmailTemplates'))

// Integration Retry Queues & DLQ (T5.4)
const IntegrationDLQ = React.lazy(() => import('./pages/Settings/IntegrationDLQ'))
const ReportCenter = React.lazy(() => import('./pages/Reports/ReportCenter'))
const ScheduledReports = React.lazy(() => import('./pages/Reports/ScheduledReports'))
const ReportBuilder = React.lazy(() => import('./pages/Reports/ReportBuilder'))
const DetailedProfitLoss = React.lazy(() => import('./pages/Reports/DetailedProfitLoss'))
const SharedReports = React.lazy(() => import('./pages/Reports/SharedReports'))
const IndustryReport = React.lazy(() => import('./pages/Reports/IndustryReport'))

// Consolidation Reports
const ConsolidationReports = React.lazy(() => import('./pages/Reports/ConsolidationReports'))
const KPIDashboard = React.lazy(() => import('./pages/Reports/KPIDashboard'))
const KpiAdmin = React.lazy(() => import('./pages/Reports/KpiAdmin'))

// Ops
const OpsScheduler = React.lazy(() => import('./pages/Ops/Scheduler'))
const HealthDetailed = React.lazy(() => import('./pages/Ops/HealthDetailed'))

// BI Analytics Dashboards (US9)
const AnalyticsDashboardList = React.lazy(() => import('./pages/Analytics/DashboardList'))
const AnalyticsDashboardView = React.lazy(() => import('./pages/Analytics/DashboardView'))
const AnalyticsDashboardEditor = React.lazy(() => import('./pages/Analytics/DashboardEditor'))

// Role-Based KPI Dashboards
const KPIHub = React.lazy(() => import('./pages/KPI/KPIHub'))
const RoleDashboard = React.lazy(() => import('./pages/KPI/RoleDashboard'))

// New Report Pages
const PurchasesAgingReport = React.lazy(() => import('./pages/Buying/PurchasesAgingReport'))
const ChecksAgingReport = React.lazy(() => import('./pages/Treasury/ChecksAgingReport'))
const FXGainLossReport = React.lazy(() => import('./pages/Reports/FXGainLossReport'))
const AssetReports = React.lazy(() => import('./pages/Assets/AssetReports'))
const CashFlowIAS7 = React.lazy(() => import('./pages/Reports/CashFlowIAS7'))

const PaymentForm = React.lazy(() => import('./pages/Purchases/PaymentForm'))
const PaymentDetails = React.lazy(() => import('./pages/Purchases/PaymentDetails'))

// SSO Configuration
const SsoConfigList = React.lazy(() => import('./pages/SSO/SsoConfigList'))
const SsoConfigForm = React.lazy(() => import('./pages/SSO/SsoConfigForm'))

// 3-Way Matching
const MatchList = React.lazy(() => import('./pages/Matching/MatchList'))
const MatchDetail = React.lazy(() => import('./pages/Matching/MatchDetail'))
const ToleranceConfig = React.lazy(() => import('./pages/Matching/ToleranceConfig'))

// Costing (FIFO/LIFO)
const CostLayerList = React.lazy(() => import('./pages/Costing/CostLayerList'))
const CostingMethodForm = React.lazy(() => import('./pages/Costing/CostingMethodForm'))
const ValuationReport = React.lazy(() => import('./pages/Costing/ValuationReport'))



function PrivateRoute({ children, permission, role, skipIndustryCheck = false }) {
    const isAuth = isAuthenticated()
    const user = getUser()

    if (!isAuth) {
        return <Navigate to="/login" replace />
    }

    // توجيه لصفحة إعداد النشاط إذا لم يُختر بعد (مرة واحدة فقط)
    if (!skipIndustryCheck && user?.role !== 'system_admin' && !hasIndustryTypeSet()) {
        return <Navigate to="/setup/industry" replace />
    }

    if (permission && !hasPermission(permission)) {
        return <PermissionDeniedRedirect />
    }

    if (role && user?.role !== role) {
        return <PermissionDeniedRedirect />
    }

    return <Layout>{children}</Layout>
}

function PermissionDeniedRedirect() {
    const { showToast } = useToast()
    const { t } = useTranslation()
    const [redirected, setRedirected] = useState(false);

    useEffect(() => {
        if (!redirected) {
            showToast(t('common.no_permission'), 'error');
            setRedirected(true);
        }
    }, [showToast, t, redirected]);

    if (window.location.pathname === '/dashboard') {
        return <Layout><Dashboard /></Layout>;
    }

    return <Navigate to="/dashboard" replace />;
}

function App() {
    const { t, i18n } = useTranslation();
    const location = useLocation();
    const { currentBranch } = useBranch();
    const branchRouteKey = currentBranch?.id ? `branch-${currentBranch.id}` : 'branch-all';
    // SEC-T2.8: on first render the in-memory access token is empty after a full
    // page reload. We silently refresh against the HttpOnly cookie before rendering
    // any route so authenticated users don't bounce through /login.
    const [authReady, setAuthReady] = useState(false);
    useEffect(() => {
        let cancelled = false;
        bootstrapAuth().finally(() => {
            if (!cancelled) {
                setAuthReady(true);
                window.dispatchEvent(new CustomEvent('auth:ready'));
            }
        });
        return () => { cancelled = true; };
    }, []);
    const showFloatingThemeToggle = (
        location.pathname === '/login' ||
        location.pathname === '/register' ||
        location.pathname === '/forgot-password' ||
        location.pathname === '/reset-password' ||
        location.pathname.startsWith('/setup/')
    )

    useEffect(() => {
        document.documentElement.dir = i18n.language === 'ar' ? 'rtl' : 'ltr';
        document.documentElement.lang = i18n.language;
    }, [i18n.language]);

    // Abort all pending API requests when route changes
    useEffect(() => {
        return () => {
            requestManager.abortAll();
        };
    }, [location.pathname]);

    // SEC-T2.8: hold off rendering routes until silent refresh has resolved.
    if (!authReady) {
        return <PageLoader />;
    }

    return (
        <Suspense fallback={<PageLoader />}>
            {/* T8.2 a11y: Skip-link must be the very first interactive element so
                keyboard / screen-reader users can bypass the navbar/sidebar. */}
            <a href="#main-content" className="skip-link">
                {t('a11y.skip_to_main', 'تخطّي إلى المحتوى الرئيسي')}
            </a>
            {showFloatingThemeToggle && <FloatingThemeToggle />}
            <ErrorBoundary>
            <Routes key={branchRouteKey}>
                <Route path="/login" element={isAuthenticated() ? <Navigate to="/dashboard" /> : <Login />} />
                <Route path="/register" element={<Register />} />
                <Route path="/forgot-password" element={<ForgotPassword />} />
                <Route path="/reset-password" element={<ResetPassword />} />
                <Route path="/setup/industry" element={isAuthenticated() ? <IndustrySetup /> : <Navigate to="/login" />} />
                <Route path="/setup/modules" element={isAuthenticated() ? <ModuleCustomization /> : <Navigate to="/login" />} />
                <Route path="/dashboard" element={<PrivateRoute permission="dashboard.view"><Dashboard /></PrivateRoute>} />
                <Route path="/kpi" element={<PrivateRoute permission="dashboard.view"><KPIHub /></PrivateRoute>} />
                <Route path="/kpi/:roleKey" element={<PrivateRoute permission="dashboard.view"><RoleDashboard /></PrivateRoute>} />
                <Route path="/accounting/kpi" element={<PrivateRoute permission="accounting.view"><RoleDashboard fixedRoleKey="financial" backPath="/accounting" /></PrivateRoute>} />
                <Route path="/accounting" element={<PrivateRoute permission="accounting.view"><AccountingHome /></PrivateRoute>} />
                <Route path="/accounting/coa" element={<PrivateRoute permission="accounting.view"><ChartOfAccounts /></PrivateRoute>} />
                <Route path="/accounting/cost-centers" element={<PrivateRoute permission="accounting.view"><CostCenterList /></PrivateRoute>} />
                <Route path="/accounting/journal-entries" element={<PrivateRoute permission="accounting.view"><JournalEntryList /></PrivateRoute>} />
                <Route path="/accounting/journal-entries/new" element={<PrivateRoute permission="accounting.edit"><JournalEntryForm /></PrivateRoute>} />
                <Route path="/accounting/fiscal-years" element={<PrivateRoute permission="accounting.view"><FiscalYears /></PrivateRoute>} />
                <Route path="/accounting/recurring-templates" element={<PrivateRoute permission="accounting.view"><RecurringTemplates /></PrivateRoute>} />
                <Route path="/accounting/period-comparison" element={<PrivateRoute permission="accounting.view"><PeriodComparison /></PrivateRoute>} />
                <Route path="/accounting/opening-balances" element={<PrivateRoute permission="accounting.manage"><OpeningBalances /></PrivateRoute>} />
                <Route path="/accounting/closing-entries" element={<PrivateRoute permission="accounting.manage"><ClosingEntries /></PrivateRoute>} />
                <Route path="/accounting/budgets" element={<PrivateRoute permission="accounting.view"><Budgets /></PrivateRoute>} />
                <Route path="/accounting/budgets/:id/items" element={<PrivateRoute permission="accounting.view"><BudgetItems /></PrivateRoute>} />
                <Route path="/accounting/budgets/:id/report" element={<PrivateRoute permission="accounting.view"><BudgetReport /></PrivateRoute>} />
                <Route path="/accounting/vat-report" element={<PrivateRoute permission="accounting.view"><VATReport /></PrivateRoute>} />
                <Route path="/accounting/tax-audit" element={<PrivateRoute permission="accounting.view"><TaxAudit /></PrivateRoute>} />
                <Route path="/accounting/cashflow" element={<PrivateRoute permission="accounting.view"><CashFlowReport /></PrivateRoute>} />
                <Route path="/accounting/general-ledger" element={<PrivateRoute permission="accounting.view"><GeneralLedger /></PrivateRoute>} />
                <Route path="/accounting/trial-balance" element={<PrivateRoute permission="accounting.view"><TrialBalance /></PrivateRoute>} />
                <Route path="/accounting/income-statement" element={<PrivateRoute permission="accounting.view"><IncomeStatement /></PrivateRoute>} />
                <Route path="/accounting/balance-sheet" element={<PrivateRoute permission="accounting.view"><BalanceSheet /></PrivateRoute>} />
                <Route path="/accounting/currencies" element={<PrivateRoute permission="currencies.view"><CurrencyList /></PrivateRoute>} />

                {/* Zakat & Fiscal Locks */}
                <Route path="/accounting/zakat" element={<PrivateRoute permission="accounting.view"><ZakatCalculator /></PrivateRoute>} />
                <Route path="/accounting/fiscal-locks" element={<PrivateRoute permission="accounting.manage"><FiscalPeriodLocks /></PrivateRoute>} />
                <Route path="/accounting/intercompany" element={<PrivateRoute permission="accounting.view"><IntercompanyTransactions /></PrivateRoute>} />
                <Route path="/accounting/revenue-recognition" element={<PrivateRoute permission="accounting.view"><RevenueRecognition /></PrivateRoute>} />

                {/* Intercompany v2 */}
                <Route path="/accounting/intercompany/entities" element={<PrivateRoute permission="accounting.view"><EntityGroupTree /></PrivateRoute>} />
                <Route path="/accounting/intercompany/transactions" element={<PrivateRoute permission="accounting.view"><IntercompanyTransactionList /></PrivateRoute>} />
                <Route path="/accounting/intercompany/transactions/new" element={<PrivateRoute permission="accounting.edit"><IntercompanyTransactionForm /></PrivateRoute>} />
                <Route path="/accounting/intercompany/consolidation" element={<PrivateRoute permission="accounting.view"><ConsolidationView /></PrivateRoute>} />
                <Route path="/accounting/intercompany/mappings" element={<PrivateRoute permission="accounting.view"><IntercompanyAccountMappings /></PrivateRoute>} />

                {/* Legacy intercompany aliases */}
                <Route path="/intercompany/transactions" element={<Navigate to="/accounting/intercompany/transactions" replace />} />
                <Route path="/intercompany/transactions/new" element={<Navigate to="/accounting/intercompany/transactions/new" replace />} />
                <Route path="/intercompany/entities" element={<Navigate to="/accounting/intercompany/entities" replace />} />
                <Route path="/intercompany/consolidation" element={<Navigate to="/accounting/intercompany/consolidation" replace />} />
                <Route path="/intercompany/mappings" element={<Navigate to="/accounting/intercompany/mappings" replace />} />
                <Route path="/stock/valuation-report" element={<PrivateRoute permission="reports.view"><InventoryValuation /></PrivateRoute>} />
                <Route path="/admin/companies" element={<PrivateRoute role="system_admin"><CompanyList /></PrivateRoute>} />
                <Route path="/admin/audit-logs" element={<PrivateRoute permission="audit.view"><AuditLogs /></PrivateRoute>} />
                <Route path="/admin/roles" element={<PrivateRoute permission="admin.roles"><RoleManagement /></PrivateRoute>} />
                <Route path="/admin/backups" element={<PrivateRoute role="system_admin"><BackupManagement /></PrivateRoute>} />
                <Route path="/admin/security-events" element={<PrivateRoute permission="admin.security"><SecurityEvents /></PrivateRoute>} />
                <Route path="/admin/ops/scheduler" element={<PrivateRoute role="system_admin"><OpsScheduler /></PrivateRoute>} />
                <Route path="/health/detailed" element={<PrivateRoute><HealthDetailed /></PrivateRoute>} />

                {/* Approvals */}
                <Route path="/approvals" element={<PrivateRoute permission="approvals.view"><ApprovalsPage /></PrivateRoute>} />
                <Route path="/approvals/new" element={<PrivateRoute permission="approvals.create"><WorkflowEditor /></PrivateRoute>} />
                <Route path="/approvals/:id/edit" element={<PrivateRoute permission="approvals.manage"><WorkflowEditor /></PrivateRoute>} />

                <Route path="/data-import" element={<PrivateRoute permission="data_import.view"><DataImportPage /></PrivateRoute>} />

                <Route path="/profile" element={<PrivateRoute><UserProfile /></PrivateRoute>} />

                {/* Sales Routes */}
                <Route path="/sales" element={<PrivateRoute permission="sales.view"><SalesHome /></PrivateRoute>} />
                <Route path="/sales/customers" element={<PrivateRoute permission="sales.view"><CustomerList /></PrivateRoute>} />
                <Route path="/sales/customers/new" element={<PrivateRoute permission="sales.create"><CustomerForm /></PrivateRoute>} />
                <Route path="/sales/customers/:id/edit" element={<PrivateRoute permission="sales.edit"><CustomerForm /></PrivateRoute>} />
                <Route path="/sales/customers/:id" element={<PrivateRoute permission="sales.view"><CustomerDetails /></PrivateRoute>} />
                <Route path="/sales/invoices" element={<PrivateRoute permission="sales.view"><InvoiceList /></PrivateRoute>} />
                <Route path="/sales/invoices/new" element={<PrivateRoute permission="sales.create"><InvoiceForm /></PrivateRoute>} />
                <Route path="/sales/invoices/:id" element={<PrivateRoute permission="sales.view"><InvoiceDetails /></PrivateRoute>} />
                <Route path="/sales/orders" element={<PrivateRoute permission="sales.view"><SalesOrders /></PrivateRoute>} />
                <Route path="/sales/orders/new" element={<PrivateRoute permission="sales.create"><SalesOrderForm /></PrivateRoute>} />
                <Route path="/sales/orders/:id" element={<PrivateRoute permission="sales.view"><SalesOrderDetails /></PrivateRoute>} />
                <Route path="/sales/quotations" element={<PrivateRoute permission="sales.view"><SalesQuotations /></PrivateRoute>} />
                <Route path="/sales/quotations/new" element={<PrivateRoute permission="sales.create"><SalesQuotationForm /></PrivateRoute>} />
                <Route path="/sales/quotations/:id" element={<PrivateRoute permission="sales.view"><SalesQuotationDetails /></PrivateRoute>} />
                <Route path="/sales/customer-groups" element={<PrivateRoute permission="sales.view"><CustomerGroups /></PrivateRoute>} />
                <Route path="/sales/returns" element={<PrivateRoute permission="sales.view"><SalesReturns /></PrivateRoute>} />
                <Route path="/sales/returns/new" element={<PrivateRoute permission="sales.create"><SalesReturnForm /></PrivateRoute>} />
                <Route path="/sales/returns/:id" element={<PrivateRoute permission="sales.view"><SalesReturnDetails /></PrivateRoute>} />
                <Route path="/sales/receipts" element={<PrivateRoute permission="sales.view"><CustomerReceipts /></PrivateRoute>} />
                <Route path="/sales/receipts/new" element={<PrivateRoute permission="sales.create"><ReceiptForm /></PrivateRoute>} />
                <Route path="/sales/receipts/:id" element={<PrivateRoute permission="sales.view"><ReceiptDetails /></PrivateRoute>} />
                <Route path="/sales/payments" element={<PrivateRoute permission="sales.view"><CustomerReceipts /></PrivateRoute>} />
                <Route path="/sales/payments/new" element={<PrivateRoute permission="sales.create"><ReceiptForm /></PrivateRoute>} />
                <Route path="/sales/payments/:id" element={<PrivateRoute permission="sales.view"><ReceiptDetails /></PrivateRoute>} />
                <Route path="/sales/price-lists" element={<PrivateRoute permission="sales.view"><PriceLists /></PrivateRoute>} />
                <Route path="/sales/reports/analytics" element={<PrivateRoute permission="sales.reports"><SalesReports /></PrivateRoute>} />
                <Route path="/sales/reports/customer-statement" element={<PrivateRoute permission="sales.reports"><CustomerStatement /></PrivateRoute>} />
                <Route path="/sales/reports/aging" element={<PrivateRoute permission="sales.reports"><AgingReport /></PrivateRoute>} />
                <Route path="/sales/contracts" element={<PrivateRoute permission="sales.view"><ContractList /></PrivateRoute>} />
                <Route path="/sales/contracts/new" element={<PrivateRoute permission="contracts.create"><ContractForm /></PrivateRoute>} />
                <Route path="/sales/contracts/:id" element={<PrivateRoute permission="sales.view"><ContractDetails /></PrivateRoute>} />
                <Route path="/sales/contracts/:id/edit" element={<PrivateRoute permission="contracts.edit"><ContractForm /></PrivateRoute>} />
                <Route path="/sales/contracts/:id/amendments" element={<PrivateRoute permission="sales.view"><ContractAmendments /></PrivateRoute>} />
                <Route path="/sales/contract-amendments" element={<PrivateRoute permission="sales.view"><ContractAmendments /></PrivateRoute>} />
                <Route path="/sales/credit-notes" element={<PrivateRoute permission="sales.view"><SalesCreditNotes /></PrivateRoute>} />
                <Route path="/sales/debit-notes" element={<PrivateRoute permission="sales.view"><SalesDebitNotes /></PrivateRoute>} />
                <Route path="/sales/commissions" element={<PrivateRoute permission="sales.view"><SalesCommissions /></PrivateRoute>} />

                {/* Delivery Orders */}
                <Route path="/sales/delivery-orders" element={<PrivateRoute permission="sales.view"><DeliveryOrders /></PrivateRoute>} />
                <Route path="/sales/delivery-orders/new" element={<PrivateRoute permission="sales.create"><DeliveryOrderForm /></PrivateRoute>} />
                <Route path="/sales/delivery-orders/:id" element={<PrivateRoute permission="sales.view"><DeliveryOrderDetails /></PrivateRoute>} />

                {/* CPQ */}
                <Route path="/sales/cpq/products" element={<PrivateRoute permission="sales.view"><ConfigurableProducts /></PrivateRoute>} />
                <Route path="/sales/cpq/configure/:configId" element={<PrivateRoute permission="sales.view"><Configurator /></PrivateRoute>} />
                <Route path="/sales/cpq/quotes" element={<PrivateRoute permission="sales.view"><QuoteList /></PrivateRoute>} />
                <Route path="/sales/cpq/quotes/:quoteId" element={<PrivateRoute permission="sales.view"><QuoteDetail /></PrivateRoute>} />

                {/* Manufacturing Routes */}
                <Route path="/manufacturing" element={<PrivateRoute permission="manufacturing.view"><ManufacturingHome /></PrivateRoute>} />
                <Route path="/manufacturing/work-centers" element={<PrivateRoute permission="manufacturing.view"><WorkCenters /></PrivateRoute>} />
                <Route path="/manufacturing/routes" element={<PrivateRoute permission="manufacturing.view"><Routings /></PrivateRoute>} />
                <Route path="/manufacturing/boms" element={<PrivateRoute permission="manufacturing.view"><BOMs /></PrivateRoute>} />
                <Route path="/manufacturing/orders" element={<PrivateRoute permission="manufacturing.view"><ProductionOrders /></PrivateRoute>} />
                <Route path="/manufacturing/orders/:id" element={<PrivateRoute permission="manufacturing.view"><ProductionOrderDetails /></PrivateRoute>} />
                <Route path="/manufacturing/job-cards" element={<PrivateRoute permission="manufacturing.view"><JobCards /></PrivateRoute>} />
                <Route path="/manufacturing/mrp" element={<PrivateRoute permission="manufacturing.view"><MRPPlanning /></PrivateRoute>} />
                <Route path="/manufacturing/mrp/:id" element={<PrivateRoute permission="manufacturing.view"><MRPView /></PrivateRoute>} />
                <Route path="/manufacturing/equipment" element={<PrivateRoute permission="manufacturing.view"><EquipmentMaintenance /></PrivateRoute>} />
                <Route path="/manufacturing/schedule" element={<PrivateRoute permission="manufacturing.view"><ProductionSchedule /></PrivateRoute>} />
                <Route path="/manufacturing/reports/direct-labor" element={<PrivateRoute permission="manufacturing.view"><DirectLaborReport /></PrivateRoute>} />
                <Route path="/manufacturing/reports/analytics" element={<PrivateRoute permission="manufacturing.view"><ProductionAnalytics /></PrivateRoute>} />
                <Route path="/manufacturing/reports/work-orders" element={<PrivateRoute permission="manufacturing.view"><WorkOrderStatusReport /></PrivateRoute>} />
                <Route path="/manufacturing/costing" element={<PrivateRoute permission="manufacturing.view"><ManufacturingCosting /></PrivateRoute>} />
                <Route path="/manufacturing/capacity" element={<PrivateRoute permission="manufacturing.view"><CapacityPlanning /></PrivateRoute>} />
                <Route path="/manufacturing/shopfloor" element={<PrivateRoute permission="manufacturing.view"><ShopFloorDashboard /></PrivateRoute>} />
                <Route path="/manufacturing/shopfloor/work-order/:id" element={<PrivateRoute permission="manufacturing.view"><OperationEntry /></PrivateRoute>} />
                <Route path="/manufacturing/routing" element={<PrivateRoute permission="manufacturing.view"><RoutingList /></PrivateRoute>} />
                <Route path="/manufacturing/routing/new" element={<PrivateRoute permission="manufacturing.view"><RoutingForm /></PrivateRoute>} />
                <Route path="/manufacturing/routing/:id" element={<PrivateRoute permission="manufacturing.view"><RoutingForm /></PrivateRoute>} />
                <Route path="/manufacturing/routing/:id/edit" element={<PrivateRoute permission="manufacturing.view"><RoutingForm /></PrivateRoute>} />

                {/* Time Tracking Routes */}
                <Route path="/projects/timetracking" element={<PrivateRoute permission="projects.time_view"><TimesheetWeek /></PrivateRoute>} />
                <Route path="/projects/timetracking/team" element={<PrivateRoute permission="projects.time_approve"><TeamTimesheets /></PrivateRoute>} />
                <Route path="/projects/timetracking/profitability" element={<PrivateRoute permission="projects.time_view"><ProjectProfitability /></PrivateRoute>} />

                {/* Resource Planning Routes */}
                <Route path="/projects/resources/availability" element={<PrivateRoute permission="projects.resource_view"><AvailabilityCalendar /></PrivateRoute>} />
                <Route path="/projects/resources/allocate" element={<PrivateRoute permission="projects.resource_manage"><AllocationForm /></PrivateRoute>} />
                <Route path="/projects/resources/allocate/:id" element={<PrivateRoute permission="projects.resource_manage"><AllocationForm /></PrivateRoute>} />
                <Route path="/projects/resources/project/:projectId" element={<PrivateRoute permission="projects.resource_view"><ProjectResources /></PrivateRoute>} />

                {/* Stock Routes */}
                <Route path="/stock" element={<PrivateRoute permission="stock.view"><StockHome /></PrivateRoute>} />
                <Route path="/stock/products" element={<PrivateRoute permission="stock.view"><ProductList /></PrivateRoute>} />
                <Route path="/stock/products/new" element={<PrivateRoute permission="products.create"><ProductForm /></PrivateRoute>} />
                <Route path="/stock/products/:id" element={<PrivateRoute permission="stock.view"><ProductForm /></PrivateRoute>} />
                <Route path="/stock/categories" element={<PrivateRoute permission="stock.view"><CategoryList /></PrivateRoute>} />
                <Route path="/stock/warehouses" element={<PrivateRoute permission="stock.view"><WarehouseList /></PrivateRoute>} />
                <Route path="/stock/warehouses/:id" element={<PrivateRoute permission="stock.view"><WarehouseDetails /></PrivateRoute>} />
                <Route path="/stock/transfer" element={<PrivateRoute permission="stock.transfer"><StockTransferForm /></PrivateRoute>} />
                <Route path="/stock/adjustments" element={<PrivateRoute permission="stock.view"><StockAdjustments /></PrivateRoute>} />
                <Route path="/stock/adjustments/new" element={<PrivateRoute permission="stock.adjustment"><StockAdjustmentForm /></PrivateRoute>} />

                <Route path="/stock/shipments" element={<PrivateRoute permission="stock.view"><ShipmentList /></PrivateRoute>} />
                <Route path="/stock/shipments/new" element={<PrivateRoute permission="stock.view"><StockShipmentForm /></PrivateRoute>} />
                <Route path="/stock/shipments/incoming" element={<PrivateRoute permission="stock.view"><IncomingShipments /></PrivateRoute>} />
                <Route path="/stock/shipments/:id" element={<PrivateRoute permission="stock.view"><ShipmentDetails /></PrivateRoute>} />

                 <Route path="/stock/price-lists" element={<PrivateRoute permission="stock.view"><PriceLists /></PrivateRoute>} />
                 <Route path="/stock/price-lists/:id" element={<PrivateRoute permission="stock.view"><PriceListItems /></PrivateRoute>} />
                 <Route path="/stock/reports/balance" element={<PrivateRoute permission="stock.reports"><StockReports /></PrivateRoute>} />
                 <Route path="/stock/reports/movements" element={<PrivateRoute permission="stock.reports"><StockMovements /></PrivateRoute>} />
                 <Route path="/stock/reports/profitability" element={<PrivateRoute permission="stock.reports"><ProfitabilityReport /></PrivateRoute>} />
                 <Route path="/stock/reports/*" element={<PrivateRoute permission="stock.reports"><StockReports /></PrivateRoute>} />

                {/* Advanced Inventory */}
                <Route path="/stock/batches" element={<PrivateRoute permission="stock.view"><BatchList /></PrivateRoute>} />
                <Route path="/stock/serials" element={<PrivateRoute permission="stock.view"><SerialList /></PrivateRoute>} />
                <Route path="/stock/quality" element={<PrivateRoute permission="stock.view"><QualityInspections /></PrivateRoute>} />
                <Route path="/stock/cycle-counts" element={<PrivateRoute permission="stock.view"><CycleCounts /></PrivateRoute>} />

                {/* Costing (FIFO/LIFO) */}
                <Route path="/stock/cost-layers" element={<PrivateRoute permission="stock.view"><CostLayerList /></PrivateRoute>} />
                <Route path="/stock/costing-method" element={<PrivateRoute permission="stock.view"><CostingMethodForm /></PrivateRoute>} />
                <Route path="/stock/costing-valuation" element={<PrivateRoute permission="stock.reports"><ValuationReport /></PrivateRoute>} />

                {/* Demand Forecasting */}
                <Route path="/inventory/forecast" element={<PrivateRoute permission="inventory.forecast_view"><DemandForecastList /></PrivateRoute>} />
                <Route path="/inventory/forecast/generate" element={<PrivateRoute permission="inventory.forecast_generate"><DemandForecastGenerate /></PrivateRoute>} />
                <Route path="/inventory/forecast/:id" element={<PrivateRoute permission="inventory.forecast_view"><DemandForecastDetail /></PrivateRoute>} />

                {/* Buying Routes */}
                <Route path="/buying" element={<PrivateRoute permission="buying.view"><BuyingHome /></PrivateRoute>} />
                <Route path="/buying/suppliers" element={<PrivateRoute permission="buying.view"><SupplierList /></PrivateRoute>} />
                <Route path="/buying/suppliers/new" element={<PrivateRoute permission="buying.create"><SupplierForm /></PrivateRoute>} />
                <Route path="/buying/suppliers/:id/edit" element={<PrivateRoute permission="buying.edit"><SupplierForm /></PrivateRoute>} />
                <Route path="/buying/suppliers/:id" element={<PrivateRoute permission="buying.view"><SupplierDetails /></PrivateRoute>} />
                <Route path="/buying/invoices" element={<PrivateRoute permission="buying.view"><PurchaseInvoiceList /></PrivateRoute>} />
                <Route path="/buying/invoices/new" element={<PrivateRoute permission="buying.create"><PurchaseInvoiceForm /></PrivateRoute>} />
                <Route path="/buying/invoices/:id" element={<PrivateRoute permission="buying.view"><PurchaseInvoiceDetails /></PrivateRoute>} />

                <Route path="/buying/returns" element={<PrivateRoute permission="buying.view"><BuyingReturns /></PrivateRoute>} />
                <Route path="/buying/returns/new" element={<PrivateRoute permission="buying.create"><BuyingReturnForm /></PrivateRoute>} />
                <Route path="/buying/returns/:id" element={<PrivateRoute permission="buying.view"><BuyingReturnDetails /></PrivateRoute>} />
                <Route path="/buying/orders" element={<PrivateRoute permission="buying.view"><BuyingOrders /></PrivateRoute>} />
                <Route path="/buying/orders/new" element={<PrivateRoute permission="buying.create"><BuyingOrderForm /></PrivateRoute>} />
                <Route path="/buying/orders/:id" element={<PrivateRoute permission="buying.view"><BuyingOrderDetails /></PrivateRoute>} />
                <Route path="/buying/orders/:id/receive" element={<PrivateRoute permission="buying.receive"><PurchaseOrderReceive /></PrivateRoute>} />
                <Route path="/buying/payments" element={<PrivateRoute permission="buying.view"><SupplierPayments /></PrivateRoute>} />
                <Route path="/buying/payments/new" element={<PrivateRoute permission="buying.create"><PaymentForm /></PrivateRoute>} />
                <Route path="/buying/payments/:id" element={<PrivateRoute permission="buying.view"><PaymentDetails /></PrivateRoute>} />
                <Route path="/buying/supplier-groups" element={<PrivateRoute permission="buying.view"><SupplierGroups /></PrivateRoute>} />
                <Route path="/buying/reports/analytics" element={<PrivateRoute permission="buying.reports"><BuyingReports /></PrivateRoute>} />
                <Route path="/buying/reports/supplier-statement" element={<PrivateRoute permission="buying.reports"><SupplierStatement /></PrivateRoute>} />
                <Route path="/buying/reports/aging" element={<PrivateRoute permission="buying.reports"><PurchasesAgingReport /></PrivateRoute>} />
                <Route path="/buying/credit-notes" element={<PrivateRoute permission="buying.view"><PurchaseCreditNotes /></PrivateRoute>} />
                <Route path="/buying/debit-notes" element={<PrivateRoute permission="buying.view"><PurchaseDebitNotes /></PrivateRoute>} />
                <Route path="/buying/rfq" element={<PrivateRoute permission="buying.view"><RFQList /></PrivateRoute>} />
                <Route path="/buying/supplier-ratings" element={<PrivateRoute permission="buying.view"><SupplierRatings /></PrivateRoute>} />
                <Route path="/buying/agreements" element={<PrivateRoute permission="buying.view"><PurchaseAgreements /></PrivateRoute>} />

                {/* Blanket Purchase Orders */}
                <Route path="/buying/blanket-po" element={<PrivateRoute permission="buying.view"><BlanketPOList /></PrivateRoute>} />
                <Route path="/buying/blanket-po/new" element={<PrivateRoute permission="buying.create"><BlanketPOForm /></PrivateRoute>} />
                <Route path="/buying/blanket-po/:id" element={<PrivateRoute permission="buying.view"><BlanketPODetail /></PrivateRoute>} />

                {/* Landed Costs */}
                <Route path="/buying/landed-costs" element={<PrivateRoute permission="buying.view"><LandedCosts /></PrivateRoute>} />
                <Route path="/buying/landed-costs/:id" element={<PrivateRoute permission="buying.view"><LandedCostDetails /></PrivateRoute>} />

                {/* 3-Way Matching */}
                <Route path="/buying/matching" element={<PrivateRoute permission="buying.view"><MatchList /></PrivateRoute>} />
                <Route path="/buying/matching/tolerances" element={<PrivateRoute permission="buying.view"><ToleranceConfig /></PrivateRoute>} />
                <Route path="/buying/matching/:id" element={<PrivateRoute permission="buying.view"><MatchDetail /></PrivateRoute>} />

                {/* Treasury Routes */}
                <Route path="/treasury" element={<PrivateRoute permission="treasury.view"><TreasuryHome /></PrivateRoute>} />
                <Route path="/treasury/accounts" element={<PrivateRoute permission="treasury.view"><TreasuryAccountList /></PrivateRoute>} />
                <Route path="/treasury/expense" element={<PrivateRoute permission="treasury.view"><TreasuryExpenseForm /></PrivateRoute>} />
                <Route path="/treasury/transfer" element={<PrivateRoute permission="treasury.view"><TransferForm /></PrivateRoute>} />
                <Route path="/treasury/reconciliation" element={<PrivateRoute permission="reconciliation.view"><ReconciliationList /></PrivateRoute>} />
                <Route path="/treasury/reconciliation/:id" element={<PrivateRoute permission="reconciliation.view"><ReconciliationForm /></PrivateRoute>} />
                <Route path="/treasury/reports/cashflow" element={<PrivateRoute permission="treasury.view"><TreasuryCashflowReport /></PrivateRoute>} />
                <Route path="/treasury/reports/balances" element={<PrivateRoute permission="treasury.view"><TreasuryBalancesReport /></PrivateRoute>} />
                <Route path="/treasury/reports/checks-aging" element={<PrivateRoute permission="treasury.view"><ChecksAgingReport /></PrivateRoute>} />
                <Route path="/treasury/checks-receivable" element={<PrivateRoute permission="treasury.view"><ChecksReceivable /></PrivateRoute>} />
                <Route path="/treasury/checks-payable" element={<PrivateRoute permission="treasury.view"><ChecksPayable /></PrivateRoute>} />
                <Route path="/treasury/notes-receivable" element={<PrivateRoute permission="treasury.view"><NotesReceivable /></PrivateRoute>} />
                <Route path="/treasury/notes-payable" element={<PrivateRoute permission="treasury.view"><NotesPayable /></PrivateRoute>} />

                {/* Bank Import */}
                <Route path="/treasury/bank-import" element={<PrivateRoute permission="treasury.view"><BankImport /></PrivateRoute>} />

                {/* Cash Flow Forecast */}
                <Route path="/finance/cashflow" element={<PrivateRoute permission="finance.cashflow_view"><ForecastList /></PrivateRoute>} />
                <Route path="/finance/cashflow/generate" element={<PrivateRoute permission="finance.cashflow_generate"><ForecastGenerate /></PrivateRoute>} />
                <Route path="/finance/cashflow/:id" element={<PrivateRoute permission="finance.cashflow_view"><ForecastDetail /></PrivateRoute>} />

                {/* Subscription Billing */}
                <Route path="/finance/subscriptions" element={<PrivateRoute permission="finance.subscription_view"><SubscriptionHome /></PrivateRoute>} />
                <Route path="/finance/subscriptions/plans" element={<PrivateRoute permission="finance.subscription_view"><SubscriptionPlanList /></PrivateRoute>} />
                <Route path="/finance/subscriptions/plans/new" element={<PrivateRoute permission="finance.subscription_manage"><SubscriptionPlanForm /></PrivateRoute>} />
                <Route path="/finance/subscriptions/plans/:id/edit" element={<PrivateRoute permission="finance.subscription_manage"><SubscriptionPlanForm /></PrivateRoute>} />
                <Route path="/finance/subscriptions/enrollments" element={<PrivateRoute permission="finance.subscription_view"><SubscriptionEnrollmentList /></PrivateRoute>} />
                <Route path="/finance/subscriptions/enrollments/:id" element={<PrivateRoute permission="finance.subscription_view"><SubscriptionEnrollmentDetail /></PrivateRoute>} />
                <Route path="/finance/subscriptions/enroll" element={<PrivateRoute permission="finance.subscription_manage"><SubscriptionEnrollmentForm /></PrivateRoute>} />

                {/* Other Modules */}
                <Route path="/reports" element={<PrivateRoute permission="reports.view"><ReportCenter /></PrivateRoute>} />
                <Route path="/reports/builder" element={<PrivateRoute permission="reports.create"><ReportBuilder /></PrivateRoute>} />
                <Route path="/reports/scheduled" element={<PrivateRoute permission="reports.view"><ScheduledReports /></PrivateRoute>} />
                <Route path="/reports/detailed-pl" element={<PrivateRoute permission="accounting.view"><DetailedProfitLoss /></PrivateRoute>} />
                <Route path="/reports/shared" element={<PrivateRoute permission="reports.view"><SharedReports /></PrivateRoute>} />
                <Route path="/reports/consolidation" element={<PrivateRoute permission="reports.view"><ConsolidationReports /></PrivateRoute>} />
                <Route path="/reports/kpi" element={<PrivateRoute permission="reports.view"><KPIDashboard /></PrivateRoute>} />
                <Route path="/reports/kpi-admin" element={<PrivateRoute permission="admin.roles"><KpiAdmin /></PrivateRoute>} />
                <Route path="/reports/fx-gain-loss" element={<PrivateRoute permission="reports.view"><FXGainLossReport /></PrivateRoute>} />
                <Route path="/reports/cashflow-ias7" element={<PrivateRoute permission="accounting.view"><CashFlowIAS7 /></PrivateRoute>} />
                <Route path="/reports/industry/:reportType" element={<PrivateRoute permission="reports.view"><IndustryReport /></PrivateRoute>} />

                {/* BI Analytics Dashboards (US9) */}
                <Route path="/analytics" element={<PrivateRoute permission="dashboard.analytics_view"><AnalyticsDashboardList /></PrivateRoute>} />
                <Route path="/analytics/new" element={<PrivateRoute permission="dashboard.analytics_manage"><AnalyticsDashboardEditor /></PrivateRoute>} />
                <Route path="/analytics/:id" element={<PrivateRoute permission="dashboard.analytics_view"><AnalyticsDashboardView /></PrivateRoute>} />

                {/* HR Routes */}
                <Route path="/hr" element={<PrivateRoute permission="hr.view"><HRHome /></PrivateRoute>} />
                <Route path="/hr/employees" element={<PrivateRoute permission="hr.view"><Employees /></PrivateRoute>} />
                <Route path="/hr/departments" element={<PrivateRoute permission="hr.view"><DepartmentList /></PrivateRoute>} />
                <Route path="/hr/positions" element={<PrivateRoute permission="hr.view"><PositionList /></PrivateRoute>} />
                <Route path="/hr/payroll" element={<PrivateRoute permission="hr.view"><PayrollList /></PrivateRoute>} />
                <Route path="/hr/payroll/:id" element={<PrivateRoute permission="hr.view"><PayrollDetails /></PrivateRoute>} />
                <Route path="/hr/loans" element={<PrivateRoute permission="hr.view"><LoanList /></PrivateRoute>} />
                <Route path="/hr/leaves" element={<PrivateRoute permission="hr.view"><LeaveList /></PrivateRoute>} />
                <Route path="/hr/attendance" element={<PrivateRoute permission="hr.view"><Attendance /></PrivateRoute>} />
                <Route path="/hr/reports" element={<PrivateRoute permission="hr.reports"><HRReports /></PrivateRoute>} />
                <Route path="/hr/reports/leave" element={<PrivateRoute permission="hr.reports"><LeaveReport /></PrivateRoute>} />
                <Route path="/hr/reports/payroll" element={<PrivateRoute permission="hr.reports"><PayrollReport /></PrivateRoute>} />

                {/* HR Advanced Routes */}
                <Route path="/hr/salary-structures" element={<PrivateRoute permission="hr.view"><SalaryStructures /></PrivateRoute>} />
                <Route path="/hr/overtime" element={<PrivateRoute permission="hr.view"><OvertimeRequests /></PrivateRoute>} />
                <Route path="/hr/gosi" element={<PrivateRoute permission="hr.view"><GOSISettings /></PrivateRoute>} />
                <Route path="/hr/documents" element={<PrivateRoute permission="hr.view"><EmployeeDocuments /></PrivateRoute>} />
                <Route path="/hr/performance" element={<PrivateRoute permission="hr.performance_view"><PerformanceReviews /></PrivateRoute>} />
                <Route path="/hr/performance/cycles" element={<PrivateRoute permission="hr.performance_view"><CycleList /></PrivateRoute>} />
                <Route path="/hr/performance/cycle-new" element={<PrivateRoute permission="hr.performance_view"><CycleForm /></PrivateRoute>} />
                <Route path="/hr/performance/my-reviews" element={<PrivateRoute permission="hr.performance_view"><MyReviews /></PrivateRoute>} />
                <Route path="/hr/performance/reviews/:id/self" element={<PrivateRoute permission="hr.performance_view"><SelfAssessment /></PrivateRoute>} />
                <Route path="/hr/performance/reviews/:id/manager" element={<PrivateRoute permission="hr.performance_view"><ManagerReview /></PrivateRoute>} />
                <Route path="/hr/performance/reviews/:id/result" element={<PrivateRoute permission="hr.performance_view"><ReviewResult /></PrivateRoute>} />
                <Route path="/hr/performance/team-reviews" element={<PrivateRoute permission="hr.performance_view"><TeamReviews /></PrivateRoute>} />
                <Route path="/hr/training" element={<PrivateRoute permission="hr.view"><TrainingPrograms /></PrivateRoute>} />
                <Route path="/hr/violations" element={<PrivateRoute permission="hr.view"><Violations /></PrivateRoute>} />
                <Route path="/hr/custody" element={<PrivateRoute permission="hr.view"><CustodyManagement /></PrivateRoute>} />
                <Route path="/hr/payslips" element={<PrivateRoute permission="hr.view"><Payslips /></PrivateRoute>} />
                <Route path="/hr/leave-carryover" element={<PrivateRoute permission="hr.view"><LeaveCarryover /></PrivateRoute>} />
                <Route path="/hr/recruitment" element={<PrivateRoute permission="hr.view"><Recruitment /></PrivateRoute>} />

                {/* HR - WPS & Saudization (SA-specific) */}
                <Route path="/hr/wps" element={<PrivateRoute permission="hr.view"><WPSExport /></PrivateRoute>} />
                <Route path="/hr/saudization" element={<PrivateRoute permission="hr.view"><SaudizationDashboard /></PrivateRoute>} />
                <Route path="/hr/end-of-service" element={<PrivateRoute permission="hr.view"><EOSSettlement /></PrivateRoute>} />

                {/* HR Self-Service Routes */}
                <Route path="/hr/self-service" element={<PrivateRoute permission="hr.self_service"><SelfServiceDashboard /></PrivateRoute>} />
                <Route path="/hr/self-service/leave-request" element={<PrivateRoute permission="hr.self_service"><SelfServiceLeaveForm /></PrivateRoute>} />
                <Route path="/hr/self-service/leave-requests" element={<PrivateRoute permission="hr.self_service"><SelfServiceDashboard /></PrivateRoute>} />
                <Route path="/hr/self-service/payslips" element={<PrivateRoute permission="hr.self_service"><SelfServicePayslips /></PrivateRoute>} />
                <Route path="/hr/self-service/payslips/:id" element={<PrivateRoute permission="hr.self_service"><SelfServicePayslipDetail /></PrivateRoute>} />
                <Route path="/hr/self-service/profile" element={<PrivateRoute permission="hr.self_service"><SelfServiceProfile /></PrivateRoute>} />
                <Route path="/hr/self-service/team-requests" element={<PrivateRoute permission="hr.self_service_approve"><SelfServiceTeamRequests /></PrivateRoute>} />

                {/* Assets Routes */}
                <Route path="/assets/reports" element={<PrivateRoute permission="assets.view"><AssetReports /></PrivateRoute>} />
                <Route path="/assets/leases" element={<PrivateRoute permission="assets.view"><LeaseContracts /></PrivateRoute>} />
                <Route path="/assets/impairment" element={<PrivateRoute permission="assets.view"><ImpairmentTest /></PrivateRoute>} />
                <Route path="/assets" element={<PrivateRoute permission="assets.view"><AssetList /></PrivateRoute>} />
                <Route path="/assets/new" element={<PrivateRoute permission="assets.create"><AssetForm /></PrivateRoute>} />
                <Route path="/assets/management" element={<PrivateRoute permission="assets.view"><AssetManagement /></PrivateRoute>} />
                <Route path="/assets/:id" element={<PrivateRoute permission="assets.view"><AssetDetails /></PrivateRoute>} />

                {/* Projects Routes */}
                <Route path="/projects/kpi" element={<PrivateRoute permission="projects.view"><RoleDashboard fixedRoleKey="projects" backPath="/projects" /></PrivateRoute>} />
                <Route path="/projects" element={<PrivateRoute permission="projects.view"><ProjectList /></PrivateRoute>} />
                <Route path="/projects/resources" element={<PrivateRoute permission="projects.view"><ResourceManagement /></PrivateRoute>} />
                <Route path="/projects/new" element={<PrivateRoute permission="projects.create"><ProjectForm /></PrivateRoute>} />
                <Route path="/projects/:id" element={<PrivateRoute permission="projects.view"><ProjectDetails /></PrivateRoute>} />
                <Route path="/projects/:id/edit" element={<PrivateRoute permission="projects.edit"><ProjectForm /></PrivateRoute>} />
                <Route path="/projects/risks" element={<PrivateRoute permission="projects.view"><ProjectRisks /></PrivateRoute>} />
                <Route path="/projects/reports/financials" element={<PrivateRoute permission="projects.view"><ProjectFinancialsReport /></PrivateRoute>} />
                <Route path="/projects/reports/resources" element={<PrivateRoute permission="projects.view"><ResourceUtilizationReport /></PrivateRoute>} />
                <Route path="/projects/gantt" element={<PrivateRoute permission="projects.view"><GanttChart /></PrivateRoute>} />
                <Route path="/projects/timesheets" element={<PrivateRoute permission="projects.view"><Timesheets /></PrivateRoute>} />

                {/* Expenses Routes */}
                <Route path="/expenses/policies" element={<PrivateRoute permission="expenses.view"><ExpensePolicies /></PrivateRoute>} />
                <Route path="/expenses" element={<PrivateRoute permission="expenses.view"><ExpenseList /></PrivateRoute>} />
                <Route path="/expenses/new" element={<PrivateRoute permission="expenses.create"><ExpenseForm /></PrivateRoute>} />
                <Route path="/expenses/:id" element={<PrivateRoute permission="expenses.view"><ExpenseDetails /></PrivateRoute>} />
                <Route path="/expenses/:id/edit" element={<PrivateRoute permission="expenses.edit"><ExpenseForm /></PrivateRoute>} />

                {/* Taxes Routes */}
                <Route path="/taxes" element={<PrivateRoute permission="taxes.view"><TaxHome /></PrivateRoute>} />
                <Route path="/taxes/returns/new" element={<PrivateRoute permission="taxes.manage"><TaxReturnForm /></PrivateRoute>} />
                <Route path="/taxes/returns/:id" element={<PrivateRoute permission="taxes.view"><TaxReturnDetails /></PrivateRoute>} />
                <Route path="/taxes/wht" element={<PrivateRoute permission="taxes.view"><WithholdingTax /></PrivateRoute>} />
                <Route path="/taxes/compliance" element={<PrivateRoute permission="taxes.view"><TaxCompliance /></PrivateRoute>} />
                <Route path="/taxes/calendar" element={<PrivateRoute permission="taxes.view"><TaxCalendar /></PrivateRoute>} />

                {/* CRM Routes */}
                <Route path="/crm" element={<PrivateRoute permission="sales.view"><CRMHome /></PrivateRoute>} />
                <Route path="/crm/opportunities" element={<PrivateRoute permission="sales.view"><Opportunities /></PrivateRoute>} />
                <Route path="/crm/tickets" element={<PrivateRoute permission="sales.view"><SupportTickets /></PrivateRoute>} />
                <Route path="/crm/campaigns" element={<PrivateRoute permission="crm.campaign_view"><CampaignList /></PrivateRoute>} />
                <Route path="/crm/campaign-new" element={<PrivateRoute permission="crm.campaign_manage"><CampaignForm /></PrivateRoute>} />
                <Route path="/crm/campaigns/:id" element={<PrivateRoute permission="crm.campaign_view"><CampaignReport /></PrivateRoute>} />
                <Route path="/crm/campaigns/:id/report" element={<PrivateRoute permission="crm.campaign_view"><CampaignReport /></PrivateRoute>} />
                <Route path="/crm/legacy-campaigns" element={<PrivateRoute permission="sales.view"><MarketingCampaigns /></PrivateRoute>} />
                <Route path="/crm/knowledge-base" element={<PrivateRoute permission="sales.view"><KnowledgeBase /></PrivateRoute>} />
                <Route path="/crm/lead-scoring" element={<PrivateRoute permission="sales.view"><LeadScoring /></PrivateRoute>} />
                <Route path="/crm/segments" element={<PrivateRoute permission="sales.view"><CustomerSegments /></PrivateRoute>} />
                <Route path="/crm/analytics" element={<PrivateRoute permission="sales.view"><PipelineAnalytics /></PrivateRoute>} />
                <Route path="/crm/contacts" element={<PrivateRoute permission="sales.view"><CRMContacts /></PrivateRoute>} />
                <Route path="/crm/forecasts" element={<PrivateRoute permission="sales.view"><SalesForecasts /></PrivateRoute>} />

                {/* Services Routes */}
                <Route path="/services" element={<PrivateRoute permission="services.view"><ServicesHome /></PrivateRoute>} />
                <Route path="/services/requests" element={<PrivateRoute permission="services.view"><ServiceRequests /></PrivateRoute>} />
                <Route path="/services/documents" element={<PrivateRoute permission="services.view"><DocumentManagement /></PrivateRoute>} />

                <Route path="/settings" element={<PrivateRoute permission="settings.view"><CompanySettings /></PrivateRoute>} />
                <Route path="/admin/company-profile" element={<PrivateRoute permission="settings.view"><CompanyProfile /></PrivateRoute>} />
                <Route path="/settings/branches" element={<PrivateRoute permission="branches.view"><Branches /></PrivateRoute>} />
                <Route path="/settings/costing-policy" element={<PrivateRoute permission="settings.view"><CostingPolicy /></PrivateRoute>} />
                <Route path="/settings/api-keys" element={<PrivateRoute permission="settings.view"><ApiKeys /></PrivateRoute>} />
                <Route path="/settings/webhooks" element={<PrivateRoute permission="settings.view"><WebhooksPage /></PrivateRoute>} />
                <Route path="/settings/print-templates" element={<PrivateRoute permission="settings.view"><PrintTemplates /></PrivateRoute>} />
                <Route path="/settings/smart-alerts" element={<PrivateRoute permission="settings.view"><SmartAlerts /></PrivateRoute>} />
                <Route path="/settings/email-templates" element={<PrivateRoute permission="settings.view"><EmailTemplates /></PrivateRoute>} />
                <Route path="/settings/integration-dlq" element={<PrivateRoute permission="admin"><IntegrationDLQ /></PrivateRoute>} />

                {/* SSO Configuration */}
                <Route path="/settings/sso" element={<PrivateRoute permission="settings.view"><SsoConfigList /></PrivateRoute>} />
                <Route path="/settings/sso/new" element={<PrivateRoute permission="settings.manage"><SsoConfigForm /></PrivateRoute>} />
                <Route path="/settings/sso/:id" element={<PrivateRoute permission="settings.view"><SsoConfigForm /></PrivateRoute>} />



                {/* POS Routes */}
                <Route path="/pos/kpi" element={<PrivateRoute permission="pos.view"><RoleDashboard fixedRoleKey="pos" backPath="/pos" /></PrivateRoute>} />
                <Route path="/pos" element={<PrivateRoute permission="pos.view"><POSHome /></PrivateRoute>} />
                <Route path="/pos/interface" element={isAuthenticated() && hasPermission('pos.sessions') ? <POSInterface /> : (!isAuthenticated() ? <Navigate to="/login" /> : <PermissionDeniedRedirect />)} />
                <Route path="/pos/promotions" element={<PrivateRoute permission="pos.view"><Promotions /></PrivateRoute>} />
                <Route path="/pos/loyalty" element={<PrivateRoute permission="pos.view"><LoyaltyPrograms /></PrivateRoute>} />
                <Route path="/pos/tables" element={<PrivateRoute permission="pos.view"><TableManagement /></PrivateRoute>} />
                <Route path="/pos/kitchen" element={<PrivateRoute permission="pos.view"><KitchenDisplay /></PrivateRoute>} />
                <Route path="/pos/offline" element={<PrivateRoute permission="pos.view"><POSOfflineManager /></PrivateRoute>} />
                <Route path="/pos/thermal" element={<PrivateRoute permission="pos.view"><ThermalPrintSettings /></PrivateRoute>} />
                <Route path="/pos/customer-display" element={<PrivateRoute permission="pos.view"><CustomerDisplay /></PrivateRoute>} />


                <Route path="/" element={isAuthenticated() ? <Navigate to="/dashboard" replace /> : <Navigate to="/login" replace />} />
                <Route path="*" element={isAuthenticated() ? <PrivateRoute><NotFound /></PrivateRoute> : <Navigate to="/login" replace />} />
            </Routes>
            </ErrorBoundary>
        </Suspense>
    )
}

export default App
