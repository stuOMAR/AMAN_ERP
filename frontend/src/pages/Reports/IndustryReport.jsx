/**
 * IndustryReport — صفحة عامة لتقارير النشاط المتخصصة
 * تعرض تقرير ديناميكي ببيانات حقيقية من backend endpoints مخصصة لكل تقرير
 */
import { useState, useEffect } from 'react'
import { useParams } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import api from '../../services/apiClient'
import BackButton from '../../components/common/BackButton'
import { formatNumber } from '../../utils/format'
import { PageLoading } from '../../components/common/LoadingStates'

// ─── Report type metadata ───
const REPORT_CONFIG = {
  'food-cost': {
    icon: '🍽️', color: '#EF4444',
    titleKey: 'reports.industry.food_cost_title', descKey: 'reports.industry.food_cost_desc',
    endpoint: '/reports/industry/food-cost',
  },
  'production-cost': {
    icon: '🏭', color: '#6366f1',
    titleKey: 'reports.industry.production_cost_title', descKey: 'reports.industry.production_cost_desc',
    endpoint: '/reports/industry/production-cost',
  },
  'progress-billing': {
    icon: '🏗️', color: '#F59E0B',
    titleKey: 'reports.industry.progress_billing_title', descKey: 'reports.industry.progress_billing_desc',
    endpoint: '/reports/industry/progress-billing',
  },
  'utilization': {
    icon: '💼', color: '#8B5CF6',
    titleKey: 'reports.industry.utilization_title', descKey: 'reports.industry.utilization_desc',
    endpoint: '/reports/industry/utilization',
  },
  'drug-expiry': {
    icon: '💊', color: '#10B981',
    titleKey: 'reports.industry.drug_expiry_title', descKey: 'reports.industry.drug_expiry_desc',
    endpoint: '/reports/industry/drug-expiry',
  },
  'workshop-revenue': {
    icon: '🔧', color: '#6B7280',
    titleKey: 'reports.industry.workshop_revenue_title', descKey: 'reports.industry.workshop_revenue_desc',
    endpoint: '/reports/industry/workshop-revenue',
  },
  'ecom-returns': {
    icon: '🛒', color: '#3B82F6',
    titleKey: 'reports.industry.ecom_returns_title', descKey: 'reports.industry.ecom_returns_desc',
    endpoint: '/reports/industry/ecom-returns',
  },
  'agent-performance': {
    icon: '📦', color: '#0EA5E9',
    titleKey: 'reports.industry.agent_performance_title', descKey: 'reports.industry.agent_performance_desc',
    endpoint: '/reports/industry/agent-performance',
  },
  'fleet-tracking': {
    icon: '🚛', color: '#14B8A6',
    titleKey: 'reports.industry.fleet_tracking_title', descKey: 'reports.industry.fleet_tracking_desc',
    endpoint: '/reports/industry/fleet-tracking',
  },
  'crop-yield': {
    icon: '🌾', color: '#65A30D',
    titleKey: 'reports.industry.crop_yield_title', descKey: 'reports.industry.crop_yield_desc',
    endpoint: '/reports/industry/crop-yield',
  },
}

// ─── Formatting helpers ───
// display-only — compares backend report strings for colors and labels.
const compareDecimal = (left, right) => {
  const normalize = (value) => {
    const raw = String(value ?? '0').trim()
    const negative = raw.startsWith('-')
    const unsigned = negative ? raw.slice(1) : raw
    const [whole = '0', fraction = ''] = unsigned.split('.')
    return { negative, whole: whole.replace(/^0+(?=\d)/, '') || '0', fraction }
  }
  const a = normalize(left)
  const b = normalize(right)
  const scale = Math.max(a.fraction.length, b.fraction.length)
  const ai = BigInt(`${a.negative ? '-' : ''}${a.whole}${a.fraction.padEnd(scale, '0')}`)
  const bi = BigInt(`${b.negative ? '-' : ''}${b.whole}${b.fraction.padEnd(scale, '0')}`)
  return ai === bi ? 0 : ai > bi ? 1 : -1
}
const gt = (left, right) => compareDecimal(left, right) > 0
const gte = (left, right) => compareDecimal(left, right) >= 0
const fmtNum  = (n) => formatNumber(n)
const fmtPct  = (n) => `${formatNumber(n, 1)}%`
const fmtDate = (d) => d ? new Date(d).toLocaleDateString('en-CA') : '—'

// ─── Metric card ───
function MetricCard({ label, value, sub, color, alert }) {
  return (
    <div className="metric-card" style={{ borderTop: `3px solid ${color}`, position: 'relative' }}>
      {alert && <span style={{ position: 'absolute', top: 8, insetInlineEnd: 8, fontSize: 18 }}>{alert}</span>}
      <div style={{ fontSize: 12, color: '#64748b', marginBottom: 4 }}>{label}</div>
      <div style={{ fontSize: 22, fontWeight: 700 }}>{value}</div>
      {sub && <div style={{ fontSize: 11, color: '#94a3b8', marginTop: 2 }}>{sub}</div>}
    </div>
  )
}

// ─── Table renderer ───
function DataTable({ columns, rows, color }) {
  if (!rows?.length) return null
  return (
    <div className="table-responsive" style={{ marginTop: 8 }}>
      <table className="data-table" style={{ width: '100%' }}>
        <thead>
          <tr>{columns.map((c, i) => <th key={i} style={c.align ? { textAlign: c.align } : {}}>{c.label}</th>)}</tr>
        </thead>
        <tbody>
          {rows.map((row, ri) => (
            <tr key={ri}>
              {columns.map((c, ci) => (
                <td key={ci} style={c.align ? { textAlign: c.align } : {}}>
                  {c.render ? c.render(row) : (row[c.key] ?? '—')}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ═══════════════════════════════════════════
//   RENDER FUNCTIONS PER REPORT TYPE
// ═══════════════════════════════════════════

function renderFoodCost(data, t, color) {
  const s = data.summary || {}
  return <>
    <div className="metrics-grid">
      <MetricCard color={color} label={t('industry_reports.revenue')} value={fmtNum(s.revenue)} />
      <MetricCard color={color} label={t('industry_reports.cogs')} value={fmtNum(s.cogs)} />
      <MetricCard color="#EF4444" label={t('industry_reports.food_cost_pct')}
        value={fmtPct(s.food_cost_pct)} alert={gt(s.food_cost_pct, '35') ? '⚠️' : '✅'}
        sub={gt(s.food_cost_pct, '35') ? t('industry_reports.above_benchmark') : t('industry_reports.within_benchmark')} />
      <MetricCard color="#10B981" label={t('industry_reports.gross_margin')} value={fmtPct(s.gross_margin_pct)} />
      <MetricCard color={color} label={t('industry_reports.gross_profit')} value={fmtNum(s.gross_profit)} />
      <MetricCard color={color} label={t('industry_reports.net_profit')} value={fmtNum(s.net_profit)} />
    </div>
    {data.top_items?.length > 0 && (
      <div className="card" style={{ padding: 20, marginTop: 16 }}>
        <h3>📊 {t('industry_reports.top_10_items')}</h3>
        <DataTable color={color} rows={data.top_items} columns={[
          { key: 'product_name', label: t('industry_reports.product') },
          { key: 'qty_sold', label: t('industry_reports.qty'), align: 'center', render: r => fmtNum(r.qty_sold) },
          { key: 'total_revenue', label: t('industry_reports.revenue_col'), align: 'right', render: r => fmtNum(r.total_revenue) },
          { key: 'total_cost', label: t('industry_reports.cost'), align: 'right', render: r => fmtNum(r.total_cost) },
          { key: 'cost_pct', label: t('industry_reports.cost_pct'), align: 'center', render: r => <span style={{ color: gt(r.cost_pct, '35') ? '#EF4444' : '#10B981', fontWeight: 600 }}>{fmtPct(r.cost_pct)}</span> },
        ]} />
      </div>
    )}
  </>
}

function renderProductionCost(data, t, color) {
  const s = data.summary || {}
  return <>
    <div className="metrics-grid">
      <MetricCard color={color} label={t('industry_reports.production_orders')} value={s.total_orders} />
      <MetricCard color={color} label={t('industry_reports.produced')} value={fmtNum(s.produced_qty)} sub={`${t('industry_reports.planned')}: ${fmtNum(s.planned_qty)}`} />
      <MetricCard color="#10B981" label={t('industry_reports.efficiency')} value={fmtPct(s.efficiency_pct)} />
      <MetricCard color="#EF4444" label={t('industry_reports.scrap_rate')} value={fmtPct(s.scrap_rate_pct)} alert={gt(s.scrap_rate_pct, '5') ? '⚠️' : ''} />
      <MetricCard color={color} label={t('industry_reports.planned_cost')} value={fmtNum(s.planned_cost)} />
      <MetricCard color={color} label={t('industry_reports.actual_cost')} value={fmtNum(s.total_actual_cost)} />
      <MetricCard color={gt(s.variance, '0') ? '#EF4444' : '#10B981'} label={t('industry_reports.variance')}
        value={fmtNum(s.variance)} sub={`${fmtPct(s.variance_pct)} ${gt(s.variance, '0') ? (t('industry_reports.over')) : (t('industry_reports.under'))}`} />
    </div>
    {data.orders?.length > 0 && (
      <div className="card" style={{ padding: 20, marginTop: 16 }}>
        <h3>🏭 {t('industry_reports.production_orders')}</h3>
        <DataTable color={color} rows={data.orders} columns={[
          { key: 'order_number', label: '#' },
          { key: 'product_name', label: t('industry_reports.product') },
          { key: 'status', label: t('industry_reports.status') },
          { key: 'planned_qty', label: t('industry_reports.planned'), align: 'center', render: r => fmtNum(r.planned_qty) },
          { key: 'produced_quantity', label: t('industry_reports.produced_col'), align: 'center', render: r => fmtNum(r.produced_quantity) },
          { key: 'scrapped_quantity', label: t('industry_reports.scrapped'), align: 'center', render: r => fmtNum(r.scrapped_quantity) },
        ]} />
      </div>
    )}
  </>
}

function renderProgressBilling(data, t, color) {
  const s = data.summary || {}
  return <>
    <div className="metrics-grid">
      <MetricCard color={color} label={t('industry_reports.projects')} value={s.total_projects} sub={`${s.active_projects || 0} ${t('industry_reports.active')}`} />
      <MetricCard color={color} label={t('industry_reports.total_budgets')} value={fmtNum(s.total_budget)} />
      <MetricCard color="#10B981" label={t('industry_reports.total_invoiced')} value={fmtNum(s.total_invoiced)} sub={fmtPct(s.overall_billing_pct)} />
      <MetricCard color={color} label={t('industry_reports.total_costs')} value={fmtNum(s.total_cost)} />
      <MetricCard color={gte(s.overall_profit, '0') ? '#10B981' : '#EF4444'} label={t('industry_reports.overall_profit')} value={fmtNum(s.overall_profit)} />
    </div>
    {data.projects?.length > 0 && (
      <div className="card" style={{ padding: 20, marginTop: 16 }}>
        <h3>📋 {t('industry_reports.project_details')}</h3>
        <DataTable color={color} rows={data.projects} columns={[
          { key: 'project_code', label: '#' },
          { key: 'project_name', label: t('industry_reports.project') },
          { key: 'status', label: t('industry_reports.status') },
          { key: 'progress_percentage', label: t('industry_reports.progress'), align: 'center',
            render: r => (
              <div style={{ display: 'flex', alignItems: 'center', gap: 6 }}>
                <div style={{ flex: 1, height: 6, background: '#e2e8f0', borderRadius: 3 }}>
                  <div style={{ width: `${r.progress_percentage || 0}%`, height: '100%', background: color, borderRadius: 3 }} />
                </div>
                <span style={{ fontSize: 11, minWidth: 35 }}>{fmtPct(r.progress_percentage)}</span>
              </div>
            )
          },
          { key: 'planned_budget', label: t('industry_reports.budget'), align: 'right', render: r => fmtNum(r.planned_budget) },
          { key: 'invoiced_amount', label: t('industry_reports.invoiced'), align: 'right', render: r => fmtNum(r.invoiced_amount) },
          { key: 'profit', label: t('industry_reports.profit'), align: 'right', render: r => <span style={{ color: gte(r.profit, '0') ? '#10B981' : '#EF4444' }}>{fmtNum(r.profit)}</span> },
        ]} />
      </div>
    )}
  </>
}

function renderDrugExpiry(data, t, color) {
  const s = data.summary || {}
  return <>
    <div className="metrics-grid">
      <MetricCard color="#EF4444" label={t('industry_reports.expired')} value={s.expired_count} alert={s.expired_count > 0 ? '🔴' : ''} />
      <MetricCard color="#F59E0B" label={t('industry_reports.expires_30d')} value={s.expiring_30_days} alert={s.expiring_30_days > 0 ? '🟡' : ''} />
      <MetricCard color="#3B82F6" label={t('industry_reports.expires_60d')} value={s.expiring_60_days} />
      <MetricCard color="#10B981" label={t('industry_reports.expires_90d')} value={s.expiring_90_days} />
      <MetricCard color="#EF4444" label={t('industry_reports.value_at_risk')} value={fmtNum(s.total_value_at_risk)} />
    </div>
    {data.items?.length > 0 && (
      <div className="card" style={{ padding: 20, marginTop: 16 }}>
        <h3>💊 {t('industry_reports.at_risk_products')}</h3>
        <DataTable color={color} rows={data.items} columns={[
          { key: 'product_name', label: t('industry_reports.product') },
          { key: 'batch_number', label: t('industry_reports.batch_number') },
          { key: 'warehouse_name', label: t('industry_reports.warehouse') },
          { key: 'available_quantity', label: t('industry_reports.qty'), align: 'center', render: r => fmtNum(r.available_quantity) },
          { key: 'expiry_date', label: t('industry_reports.expiry'), render: r => fmtDate(r.expiry_date) },
          { key: 'days_left', label: t('industry_reports.days_left'), align: 'center',
            render: r => <span style={{ fontWeight: 700, color: r.days_left <= 0 ? '#EF4444' : r.days_left <= 30 ? '#F59E0B' : '#10B981' }}>{r.days_left}</span> },
          { key: 'value_at_risk', label: t('industry_reports.value'), align: 'right', render: r => fmtNum(r.value_at_risk) },
        ]} />
      </div>
    )}
  </>
}

function renderFleetTracking(data, t, color) {
  const s = data.summary || {}
  return <>
    <div className="metrics-grid">
      <MetricCard color={color} label={t('industry_reports.total_deliveries')} value={s.total} />
      <MetricCard color="#10B981" label={t('industry_reports.delivered')} value={s.delivered} />
      <MetricCard color="#F59E0B" label={t('industry_reports.in_transit')} value={s.in_transit} />
      <MetricCard color="#EF4444" label={t('industry_reports.cancelled')} value={s.cancelled} />
      <MetricCard color={color} label={t('industry_reports.vehicles')} value={s.vehicles_used} />
      <MetricCard color={color} label={t('industry_reports.completion_rate')} value={fmtPct(s.on_time_rate)} />
    </div>
    {data.vehicles?.length > 0 && (
      <div className="card" style={{ padding: 20, marginTop: 16 }}>
        <h3>🚛 {t('industry_reports.vehicle_performance')}</h3>
        <DataTable color={color} rows={data.vehicles} columns={[
          { key: 'vehicle_number', label: t('industry_reports.vehicle') },
          { key: 'driver_name', label: t('industry_reports.driver') },
          { key: 'total_deliveries', label: t('industry_reports.trips'), align: 'center' },
          { key: 'completed', label: t('industry_reports.done'), align: 'center' },
          { key: 'completion_rate', label: t('industry_reports.rate'), align: 'center', render: r => fmtPct(r.completion_rate) },
          { key: 'total_qty', label: t('industry_reports.qty'), align: 'right', render: r => fmtNum(r.total_qty) },
        ]} />
      </div>
    )}
  </>
}

function renderUtilization(data, t, color) {
  const s = data.summary || {}
  return <>
    <div className="metrics-grid">
      <MetricCard color={color} label={t('industry_reports.employees')} value={s.total_employees} />
      <MetricCard color={color} label={t('industry_reports.billable_hours')} value={fmtNum(s.total_billable_hours)} />
      <MetricCard color={gte(s.avg_utilization_pct, '70') ? '#10B981' : '#F59E0B'} label={t('industry_reports.avg_utilization')}
        value={fmtPct(s.avg_utilization_pct)} alert={gte(s.avg_utilization_pct, '70') ? '✅' : '⚠️'} />
      <MetricCard color={color} label={t('industry_reports.eff_hourly_rate')} value={fmtNum(s.effective_hourly_rate)} />
      <MetricCard color={color} label={t('industry_reports.service_revenue')} value={fmtNum(s.service_revenue)} />
      <MetricCard color={gte(s.net_profit, '0') ? '#10B981' : '#EF4444'} label={t('industry_reports.net_profit')} value={fmtNum(s.net_profit)} />
    </div>
    {data.employees?.length > 0 && (
      <div className="card" style={{ padding: 20, marginTop: 16 }}>
        <h3>👥 {t('industry_reports.employee_performance')}</h3>
        <DataTable color={color} rows={data.employees} columns={[
          { key: 'employee_name', label: t('industry_reports.employee') },
          { key: 'billable_hours', label: t('industry_reports.billable_col'), align: 'center', render: r => fmtNum(r.billable_hours) },
          { key: 'available_hours', label: t('industry_reports.available'), align: 'center' },
          { key: 'utilization_pct', label: t('industry_reports.utilization_pct'), align: 'center',
            render: r => <span style={{ fontWeight: 600, color: gte(r.utilization_pct, '70') ? '#10B981' : '#F59E0B' }}>{fmtPct(r.utilization_pct)}</span> },
          { key: 'tasks_count', label: t('industry_reports.tasks'), align: 'center' },
          { key: 'completed_tasks', label: t('industry_reports.done'), align: 'center' },
        ]} />
      </div>
    )}
  </>
}

function renderWorkshopRevenue(data, t, color) {
  const s = data.summary || {}
  return <>
    <div className="metrics-grid">
      <MetricCard color={color} label={t('industry_reports.total_jobs')} value={s.total_jobs} />
      <MetricCard color={color} label={t('industry_reports.revenue')} value={fmtNum(s.total_revenue)} />
      <MetricCard color={color} label={t('industry_reports.avg_job_value')} value={fmtNum(s.avg_job_value)} />
      <MetricCard color="#10B981" label={t('industry_reports.gross_margin_col')} value={fmtPct(s.gross_margin_pct)} />
      <MetricCard color={color} label={t('industry_reports.services')} value={s.service_items} />
      <MetricCard color={color} label={t('industry_reports.parts')} value={s.parts_items} />
    </div>
    {data.services?.length > 0 && (
      <div className="card" style={{ padding: 20, marginTop: 16 }}>
        <h3>🔧 {t('industry_reports.service_breakdown')}</h3>
        <DataTable color={color} rows={data.services} columns={[
          { key: 'service_name', label: t('industry_reports.service_part') },
          { key: 'product_type', label: t('industry_reports.type'), render: r => r.product_type === 'service' ? t('industry_reports.service') : t('industry_reports.part') },
          { key: 'job_count', label: t('industry_reports.jobs'), align: 'center' },
          { key: 'total_revenue', label: t('industry_reports.revenue_col'), align: 'right', render: r => fmtNum(r.total_revenue) },
          { key: 'margin', label: t('industry_reports.margin'), align: 'right', render: r => fmtNum(r.margin) },
          { key: 'margin_pct', label: '%', align: 'center', render: r => <span style={{ color: gte(r.margin_pct, '30') ? '#10B981' : '#EF4444' }}>{fmtPct(r.margin_pct)}</span> },
        ]} />
      </div>
    )}
  </>
}

function renderEcomReturns(data, t, color) {
  const s = data.summary || {}
  return <>
    <div className="metrics-grid">
      <MetricCard color={color} label={t('industry_reports.total_sales')} value={s.total_sales} sub={fmtNum(s.total_sales_value)} />
      <MetricCard color="#EF4444" label={t('industry_reports.returns')} value={s.total_returns} sub={fmtNum(s.total_return_value)} />
      <MetricCard color={gt(s.return_rate_pct, '10') ? '#EF4444' : '#10B981'} label={t('industry_reports.return_rate_count')}
        value={fmtPct(s.return_rate_pct)} alert={gt(s.return_rate_pct, '10') ? '⚠️' : '✅'} />
      <MetricCard color={color} label={t('industry_reports.return_rate_value')} value={fmtPct(s.value_return_rate_pct)} />
      <MetricCard color="#10B981" label={t('industry_reports.net_sales')} value={fmtNum(s.net_sales)} />
    </div>
    {data.top_returned_products?.length > 0 && (
      <div className="card" style={{ padding: 20, marginTop: 16 }}>
        <h3>📦 {t('industry_reports.top_returned_products')}</h3>
        <DataTable color={color} rows={data.top_returned_products} columns={[
          { key: 'product_name', label: t('industry_reports.product') },
          { key: 'product_code', label: t('industry_reports.code') },
          { key: 'return_count', label: t('industry_reports.return_count'), align: 'center' },
          { key: 'returned_qty', label: t('industry_reports.qty'), align: 'center', render: r => fmtNum(r.returned_qty) },
          { key: 'return_value', label: t('industry_reports.value'), align: 'right', render: r => fmtNum(r.return_value) },
        ]} />
      </div>
    )}
  </>
}

function renderAgentPerformance(data, t, color) {
  const s = data.summary || {}
  return <>
    <div className="metrics-grid">
      <MetricCard color={color} label={t('industry_reports.total_agents')} value={s.total_agents} />
      <MetricCard color={color} label={t('industry_reports.grand_total')} value={fmtNum(s.grand_total_sales)} />
      <MetricCard color={color} label={t('industry_reports.avg_per_agent')} value={fmtNum(s.avg_sales_per_agent)} />
    </div>
    {data.agents?.length > 0 && (
      <div className="card" style={{ padding: 20, marginTop: 16 }}>
        <h3>👤 {t('industry_reports.agent_breakdown')}</h3>
        <DataTable color={color} rows={data.agents} columns={[
          { key: 'agent_full_name', label: t('industry_reports.agent'), render: r => r.agent_full_name || r.agent_name },
          { key: 'invoice_count', label: t('industry_reports.invoices'), align: 'center' },
          { key: 'total_sales', label: t('industry_reports.sales'), align: 'right', render: r => fmtNum(r.total_sales) },
          { key: 'total_collected', label: t('industry_reports.collected'), align: 'right', render: r => fmtNum(r.total_collected) },
          { key: 'collection_rate_pct', label: t('industry_reports.collection'), align: 'center',
            render: r => <span style={{ color: gte(r.collection_rate_pct, '80') ? '#10B981' : '#EF4444' }}>{fmtPct(r.collection_rate_pct)}</span> },
          { key: 'customer_count', label: t('industry_reports.customers'), align: 'center' },
          { key: 'share_pct', label: t('industry_reports.share'), align: 'center', render: r => fmtPct(r.share_pct) },
        ]} />
      </div>
    )}
    {data.top_customers?.length > 0 && (
      <div className="card" style={{ padding: 20, marginTop: 16 }}>
        <h3>🏆 {t('industry_reports.top_customers')}</h3>
        <DataTable color={color} rows={data.top_customers} columns={[
          { key: 'customer_name', label: t('industry_reports.customer') },
          { key: 'order_count', label: t('industry_reports.orders'), align: 'center' },
          { key: 'total_value', label: t('industry_reports.value'), align: 'right', render: r => fmtNum(r.total_value) },
        ]} />
      </div>
    )}
  </>
}

function renderCropYield(data, t, color) {
  const s = data.summary || {}
  return <>
    <div className="metrics-grid">
      <MetricCard color={color} label={t('industry_reports.crops')} value={s.total_crops} />
      <MetricCard color={color} label={t('industry_reports.revenue')} value={fmtNum(s.total_revenue)} />
      <MetricCard color={color} label={t('industry_reports.direct_cost')} value={fmtNum(s.total_direct_cost)} />
      <MetricCard color="#10B981" label={t('industry_reports.gross_margin_col')} value={fmtPct(s.gross_margin_pct)} />
      <MetricCard color={color} label={t('industry_reports.operating_exp')} value={fmtNum(s.total_operating_expenses)} />
      <MetricCard color={gte(s.net_farm_income, '0') ? '#10B981' : '#EF4444'} label={t('industry_reports.net_farm_income')} value={fmtNum(s.net_farm_income)} />
    </div>
    {data.crops?.length > 0 && (
      <div className="card" style={{ padding: 20, marginTop: 16 }}>
        <h3>🌾 {t('industry_reports.crop_details')}</h3>
        <DataTable color={color} rows={data.crops} columns={[
          { key: 'product_name', label: t('industry_reports.crop') },
          { key: 'total_qty_sold', label: t('industry_reports.qty'), align: 'center', render: r => fmtNum(r.total_qty_sold) },
          { key: 'total_revenue', label: t('industry_reports.revenue_col'), align: 'right', render: r => fmtNum(r.total_revenue) },
          { key: 'total_cost', label: t('industry_reports.cost'), align: 'right', render: r => fmtNum(r.total_cost) },
          { key: 'profit', label: t('industry_reports.profit'), align: 'right', render: r => <span style={{ color: gte(r.profit, '0') ? '#10B981' : '#EF4444' }}>{fmtNum(r.profit)}</span> },
          { key: 'margin_pct', label: '%', align: 'center', render: r => fmtPct(r.margin_pct) },
        ]} />
      </div>
    )}
  </>
}

// ─── RENDERER MAP ───
const RENDERERS = {
  'food-cost': renderFoodCost,
  'production-cost': renderProductionCost,
  'progress-billing': renderProgressBilling,
  'drug-expiry': renderDrugExpiry,
  'fleet-tracking': renderFleetTracking,
  'utilization': renderUtilization,
  'workshop-revenue': renderWorkshopRevenue,
  'ecom-returns': renderEcomReturns,
  'agent-performance': renderAgentPerformance,
  'crop-yield': renderCropYield,
}

// ═══════════════════════════════════════════
//   MAIN COMPONENT
// ═══════════════════════════════════════════
export default function IndustryReport() {
  const { reportType } = useParams()
  const { t } = useTranslation()

  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  const config = REPORT_CONFIG[reportType]

  useEffect(() => {
    if (!config) { setError(t('errors.unknown_report_type')); setLoading(false); return }
    fetchReport()
  }, [reportType, config, t])

  const fetchReport = async () => {
    try {
      setLoading(true)
      setError(null)
      const res = await api.get(config.endpoint)
      setData(res.data)
    } catch (err) {
      setError(err.response?.data?.detail || err.message || t('errors.failed_load_report'))
    } finally {
      setLoading(false)
    }
  }

  if (!config) {
    return (
      <div className="workspace fade-in">
        <div className="workspace-header"><BackButton /><h1>❌ {t('industry_reports.not_found')}</h1></div>
        <p>{t('industry_reports.report_not_found')}</p>
      </div>
    )
  }

  const title = t(config.titleKey)
  const desc  = t(config.descKey)
  const renderFn = RENDERERS[reportType]

  return (
    <div className="workspace fade-in">
      <div className="workspace-header">
        <BackButton />
        <div className="header-title">
          <h1 className="workspace-title">
            <span style={{ marginInlineEnd: 8 }}>{config.icon}</span>{title}
          </h1>
          <p className="workspace-subtitle">{desc}</p>
        </div>
      </div>

      {data?.period && (
        <div style={{ display: 'flex', gap: 12, marginBottom: 16, fontSize: 13, color: '#64748b' }}>
          <span>📅 {data.period.from} → {data.period.to}</span>
        </div>
      )}

      {loading ? (
        <div style={{ textAlign: 'center', padding: '60px 0' }}>
          <PageLoading />
          <p style={{ color: '#64748b' }}>{t('industry_reports.loading')}</p>
        </div>
      ) : error ? (
        <div className="card" style={{ padding: 40, textAlign: 'center' }}>
          <p style={{ color: '#EF4444', fontSize: 16, marginBottom: 12 }}>❌ {error}</p>
          <button onClick={fetchReport} className="btn btn-primary" style={{ padding: '8px 20px' }}>
            {t('industry_reports.retry')}
          </button>
        </div>
      ) : data && renderFn ? (
        <div style={{ display: 'grid', gap: 16 }}>
          {renderFn(data, t, config.color)}
        </div>
      ) : (
        <div className="card" style={{ padding: 40, textAlign: 'center', color: '#94a3b8' }}>
          {t('industry_reports.no_data')}
        </div>
      )}

      <style>{`@keyframes spin { to { transform: rotate(360deg); } }`}</style>
    </div>
  )
}
