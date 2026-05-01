/**
 * API barrel — backward-compatible re-export layer.
 *
 * All API services have been moved to /src/services/ (one file per domain).
 * This file re-exports everything so existing imports like:
 *   import { salesAPI } from '../utils/api'
 *   import api from '../../utils/api'
 * continue to work with zero changes across 205+ consumer files.
 *
 * For new code, prefer importing directly from services:
 *   import { salesAPI } from '@/services/sales'
 */

// Core axios instance (default + named export)
export { default, api } from '../services/apiClient'

// Auth & Companies
export { authAPI } from '../services/auth'
export { companiesAPI } from '../services/companies'

// Accounting & Finance
export { accountingAPI, costCentersAPI, budgetsAPI, budgetImprovementsAPI, currenciesAPI, zakatAPI, fiscalLocksAPI, consolidationAPI, fxReportAPI } from '../services/accounting'

// Reports
export { reportsAPI, customReportsAPI, scheduledReportsAPI, detailedReportsAPI, reportSharingAPI } from '../services/reports'

// Sales & Purchases
export { salesAPI, deliveryOrdersAPI, cpqAPI } from '../services/sales'
export { purchasesAPI, landedCostsAPI } from '../services/purchases'

// Inventory & Costing
export { inventoryAPI, costingPolicyAPI, demandForecastAPI } from '../services/inventory'
export { costingLayerAPI } from '../services/costing'

// HR
export { hrAPI, hrAdvancedAPI, hrImprovementsAPI, attendanceAPI, wpsAPI, selfServiceAPI } from '../services/hr'

// Assets
export { assetsAPI } from '../services/assets'

// Treasury & Reconciliation
export { treasuryAPI, reconciliationAPI } from '../services/treasury'

// Manufacturing
export { manufacturingAPI, shopFloorAPI, routingAPI } from '../services/manufacturing'

// Contracts
export { contractsAPI } from '../services/contracts'

// Taxes
export { taxesAPI, taxComplianceAPI } from '../services/taxes'

// Projects
export { projectsAPI, timesheetAPI, resourceAPI } from '../services/projects'

// Notifications
export { notificationsAPI } from '../services/notifications'

// Expenses
export { expensesAPI } from '../services/expenses'

// Checks & Notes
export { checksAPI, notesAPI } from '../services/checks'

// POS
export { posAPI } from '../services/pos'

// Settings, Roles & Branches
export { settingsAPI, rolesAPI, branchesAPI } from '../services/settings'

// CRM
export { crmAPI } from '../services/crm'

// Services
export { servicesAPI } from '../services/services'

// External Integrations
export { externalAPI } from '../services/external'

// Integration Keys Vault & Circuit Breakers (T5.3)
export { integrationKeysAPI } from '../services/integrationKeys'

// Smart Alerts (T4.3)
export { smartAlertsAPI } from '../services/smartAlerts'

// Email Templates (T4.11)
export { emailTemplatesAPI } from '../services/emailTemplates'

// Integration Retry Queues & DLQ (T5.4)
export { integrationQueuesAPI } from '../services/integrationQueues'

// System Completion (Backup, Print Templates, Password Reset, etc.)
export { backupAPI, printTemplatesAPI, duplicateDetectionAPI, passwordResetAPI, manufacturingCostingAPI } from '../services/systemCompletion'

// Security
export { securityAPI } from '../services/security'

// Approvals
export { approvalsAPI } from '../services/approvals'

// Audit
export { auditAPI } from '../services/audit'

// Dashboard
export { dashboardAPI } from '../services/dashboard'

// Data Import
export { dataImportAPI } from '../services/dataImport'

// Parties
export { partiesAPI } from '../services/parties'

// Cash Flow Forecast
export { cashflowAPI } from '../services/cashflow'

