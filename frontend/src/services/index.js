/**
 * Service layer barrel export.
 * All API services are grouped by domain in separate files.
 *
 * Usage (direct):
 *   import { salesAPI } from '@/services'
 *
 * Usage (via legacy path, backward-compatible):
 *   import { salesAPI } from '../utils/api'
 */

// Core axios instance
export { default as api, default, cleanParams } from './apiClient'

// Auth & Companies
export { authAPI } from './auth'
export { companiesAPI } from './companies'

// Accounting & Finance
export { accountingAPI, costCentersAPI, budgetsAPI, currenciesAPI, zakatAPI, fiscalLocksAPI, consolidationAPI } from './accounting'

// Reports
export { reportsAPI, customReportsAPI, scheduledReportsAPI } from './reports'

// Sales & Purchases
export { salesAPI, deliveryOrdersAPI, cpqAPI } from './sales'
export { purchasesAPI, landedCostsAPI } from './purchases'

// Inventory & Costing
export { inventoryAPI, costingPolicyAPI, demandForecastAPI } from './inventory'

// HR
export { hrAPI, hrAdvancedAPI, hrImprovementsAPI, attendanceAPI, wpsAPI } from './hr'

// Assets
export { assetsAPI } from './assets'

// Treasury & Reconciliation
export { treasuryAPI, reconciliationAPI } from './treasury'

// Manufacturing
export { manufacturingAPI, shopFloorAPI, routingAPI } from './manufacturing'

// Contracts
export { contractsAPI } from './contracts'

// Taxes
export { taxesAPI } from './taxes'

// Projects
export { projectsAPI, timesheetAPI, resourceAPI } from './projects'

// Notifications
export { notificationsAPI } from './notifications'

// Expenses
export { expensesAPI } from './expenses'

// Checks & Notes
export { checksAPI, notesAPI } from './checks'

// POS
export { posAPI } from './pos'

// Settings, Roles & Branches
export { settingsAPI, rolesAPI, branchesAPI } from './settings'

// CRM
export { crmAPI } from './crm'

// External Integrations
export { externalAPI } from './external'

// Approvals
export { approvalsAPI } from './approvals'

// Security
export { securityAPI } from './security'

// Data Import
export { dataImportAPI } from './dataImport'

// Dashboard
export { dashboardAPI } from './dashboard'

// Services
export { servicesAPI } from './services'

// Audit
export { auditAPI } from './audit'

// Parties
export { partiesAPI } from './parties'

// System Completion Features
export { backupAPI, printTemplatesAPI, duplicateDetectionAPI, passwordResetAPI, manufacturingCostingAPI } from './systemCompletion'
