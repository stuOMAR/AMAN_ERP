import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { purchasesAPI } from '../../utils/api'
import { useTranslation } from 'react-i18next'
import { useToast } from '../../context/ToastContext'
import { formatShortDate } from '../../utils/dateUtils'
import { formatNumber } from '../../utils/format'
import BackButton from '../../components/common/BackButton'
import DataTable from '../../components/common/DataTable'
import { PageLoading } from '../../components/common/LoadingStates'

const LINE_STATUS_COLORS = {
  matched: '#16a34a',
  quantity_mismatch: '#d97706',
  price_mismatch: '#d97706',
  both_mismatch: '#dc2626',
}

export default function MatchDetail() {
  const { t } = useTranslation()
  const { id } = useParams()
  const navigate = useNavigate()
  const { showToast } = useToast()
  const [match, setMatch] = useState(null)
  const [loading, setLoading] = useState(true)
  const [actionLoading, setActionLoading] = useState(false)
  const [notes, setNotes] = useState('')

  useEffect(() => {
    loadMatch()
  }, [id])

  const loadMatch = async () => {
    try {
      setLoading(true)
      const res = await purchasesAPI.getMatch(id)
      setMatch(res.data)
    } catch (err) {
      showToast(t('common.error_loading'), 'error')
      navigate('/buying/matching')
    } finally {
      setLoading(false)
    }
  }

  const handleApprove = async () => {
    try {
      setActionLoading(true)
      await purchasesAPI.approveMatch(id, { exception_notes: notes })
      showToast(t('matching.approved_success'), 'success')
      loadMatch()
    } catch (err) {
      showToast(err.response?.data?.detail || t('common.error'), 'error')
    } finally {
      setActionLoading(false)
    }
  }

  const handleReject = async () => {
    try {
      setActionLoading(true)
      await purchasesAPI.rejectMatch(id, { exception_notes: notes })
      showToast(t('matching.rejected_success'), 'success')
      loadMatch()
    } catch (err) {
      showToast(err.response?.data?.detail || t('common.error'), 'error')
    } finally {
      setActionLoading(false)
    }
  }

  if (loading) {
    return (
      <div className="workspace fade-in">
        <PageLoading />
      </div>
    )
  }

  if (!match) return null

  const isHeld = match.match_status === 'held'

  return (
    <div className="workspace fade-in">
      <div className="workspace-header">
        <BackButton />
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div>
            <h1 className="workspace-title">{t('matching.detail_title')} #{match.id}</h1>
            <p className="workspace-subtitle">
              {t('matching.po_number')}: {match.po_number} | {t('matching.invoice_number')}: {match.invoice_number}
            </p>
          </div>
          <span className={`badge ${match.match_status === 'matched' ? 'badge-success' : match.match_status === 'held' ? 'badge-warning' : match.match_status === 'rejected' ? 'badge-danger' : 'badge-info'}`}
            style={{ fontSize: '14px', padding: '8px 16px' }}>
            {t(`matching.status_${match.match_status}`, match.match_status)}
          </span>
        </div>
      </div>

      {/* Header info */}
      <div className="card mb-4">
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr 1fr', gap: '16px' }}>
          <div>
            <div className="text-muted small">{t('matching.supplier')}</div>
            <div style={{ fontWeight: '600' }}>{match.supplier_name || '—'}</div>
          </div>
          <div>
            <div className="text-muted small">{t('matching.matched_at')}</div>
            <div>{match.matched_at ? formatShortDate(match.matched_at) : '—'}</div>
          </div>
          {match.exception_notes && (
            <div>
              <div className="text-muted small">{t('matching.exception_notes')}</div>
              <div>{match.exception_notes}</div>
            </div>
          )}
        </div>
      </div>

      {/* Lines table */}
      <div className="card mb-4">
        <h3 className="section-title">{t('matching.lines')}</h3>
        <DataTable
          columns={[
            { key: 'product_name', label: t('matching.product'), style: { fontWeight: '600' }, render: (val, row) => val || row.po_description || `#${row.po_line_id}` },
            { key: 'po_quantity', label: t('matching.po_qty'), headerStyle: { textAlign: 'center' }, style: { textAlign: 'center' }, render: (val) => formatNumber(val) },
            { key: 'received_quantity', label: t('matching.recv_qty'), headerStyle: { textAlign: 'center' }, style: { textAlign: 'center' }, render: (val) => formatNumber(val) },
            { key: 'invoiced_quantity', label: t('matching.inv_qty'), headerStyle: { textAlign: 'center' }, style: { textAlign: 'center' }, render: (val) => formatNumber(val) },
            { key: 'po_unit_price', label: t('matching.po_price'), headerStyle: { textAlign: 'center' }, style: { textAlign: 'center' }, render: (val) => formatNumber(val) },
            { key: 'invoiced_unit_price', label: t('matching.inv_price'), headerStyle: { textAlign: 'center' }, style: { textAlign: 'center' }, render: (val) => formatNumber(val) },
            { key: 'quantity_variance_pct', label: t('matching.qty_var'), headerStyle: { textAlign: 'center' }, style: { textAlign: 'center' }, render: (val, row) => <span style={{ color: row.line_status !== 'matched' ? '#d97706' : 'inherit' }}>{formatNumber(val)}%</span> },
            { key: 'price_variance_pct', label: t('matching.price_var'), headerStyle: { textAlign: 'center' }, style: { textAlign: 'center' }, render: (val, row) => <span style={{ color: row.line_status !== 'matched' ? '#d97706' : 'inherit' }}>{formatNumber(val)}%</span> },
            { key: 'line_status', label: t('matching.line_status'), render: (val) => <span style={{ color: LINE_STATUS_COLORS[val] || '#6b7280', fontWeight: '600', fontSize: '12px' }}>{t(`matching.line_${val}`)}</span> },
          ]}
          data={match.lines || []}
          rowKey="po_line_id"
          paginate={false}
        />
      </div>

      {/* Approve / Reject actions */}
      {isHeld && (
        <div className="card">
          <h3 className="section-title">{t('matching.actions')}</h3>
          <div style={{ marginBottom: '12px' }}>
            <label className="form-label">{t('matching.exception_notes')}</label>
            <textarea
              className="form-input"
              rows="3"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              placeholder={t('matching.notes_placeholder')}
            />
          </div>
          <div style={{ display: 'flex', gap: '12px' }}>
            <button
              className="btn btn-success"
              onClick={handleApprove}
              disabled={actionLoading}
            >
              {t('matching.approve')}
            </button>
            <button
              className="btn btn-danger"
              onClick={handleReject}
              disabled={actionLoading}
            >
              {t('matching.reject')}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
