import { useState, useEffect, useCallback } from 'react'
import { integrationQueuesAPI } from '../../utils/api'
import { toastEmitter } from '../../utils/toastEmitter'
import { useTranslation } from 'react-i18next'
import { Inbox, RefreshCcw, RotateCcw, Archive, X, AlertTriangle, Eye } from 'lucide-react'

const STATUS_BADGE = {
    pending: 'bg-warning',
    processing: 'bg-info',
    succeeded: 'bg-success',
    sent: 'bg-success',
    permanently_failed: 'bg-danger',
}

function StatusBadge({ status }) {
    return <span className={`badge ${STATUS_BADGE[status] || 'bg-secondary'}`}>{status}</span>
}

function IntegrationDLQ() {
    const { t } = useTranslation()
    const [tab, setTab] = useState('dlq') // 'dlq' | 'payment' | 'sms'
    const [items, setItems] = useState([])
    const [loading, setLoading] = useState(false)
    const [statusFilter, setStatusFilter] = useState('')
    const [showArchived, setShowArchived] = useState(false)
    const [detail, setDetail] = useState(null)

    const load = useCallback(async () => {
        try {
            setLoading(true)
            let res
            if (tab === 'dlq') {
                res = await integrationQueuesAPI.listDLQ({ archived: showArchived ? true : undefined })
            } else if (tab === 'payment') {
                res = await integrationQueuesAPI.listPaymentQueue(statusFilter ? { status: statusFilter } : null)
            } else {
                res = await integrationQueuesAPI.listSmsQueue(statusFilter ? { status: statusFilter } : null)
            }
            setItems(Array.isArray(res.data) ? res.data : [])
        } catch (err) {
            toastEmitter.show(t('settings.integration_dlq.toast.load_failed'), 'error')
        } finally {
            setLoading(false)
        }
    }, [tab, statusFilter, showArchived])

    useEffect(() => {
        load()
    }, [load])

    const openDetail = async (id) => {
        try {
            const res = await integrationQueuesAPI.getDLQItem(id)
            setDetail(res.data)
        } catch (err) {
            toastEmitter.show(t('settings.integration_dlq.toast.details_failed'), 'error')
        }
    }

    const replay = async (id) => {
        if (!window.confirm(t('settings.integration_dlq.confirm_resend'))) return
        try {
            await integrationQueuesAPI.replayDLQ(id)
            toastEmitter.show(t('settings.integration_dlq.toast.resent_success'), 'success')
            setDetail(null)
            load()
        } catch (err) {
            const msg = err?.response?.data?.detail || t('settings.integration_dlq.toast.resend_failed')
            toastEmitter.show(typeof msg === 'string' ? msg : t('settings.integration_dlq.toast.resend_failed'), 'error')
        }
    }

    const archive = async (id) => {
        if (!window.confirm(t('settings.integration_dlq.confirm_archive'))) return
        try {
            await integrationQueuesAPI.archiveDLQ(id)
            toastEmitter.show(t('settings.integration_dlq.toast.archived_success'), 'success')
            setDetail(null)
            load()
        } catch (err) {
            toastEmitter.show(t('settings.integration_dlq.toast.archive_failed'), 'error')
        }
    }

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                        <h1 className="workspace-title">
                            <Inbox size={24} className="me-2" />
                            {t('settings.integration_dlq.title')}
                        </h1>
                        <p className="text-muted small mb-0">{t('settings.integration_dlq.subtitle')}</p>
                    </div>
                    <button className="btn btn-outline-primary d-flex align-items-center gap-2" onClick={load}>
                        <RefreshCcw size={16} />
                        {t('settings.integration_dlq.refresh')}
                    </button>
                </div>
            </div>

            <ul className="nav nav-tabs mb-3">
                <li className="nav-item">
                    <button
                        className={`nav-link ${tab === 'dlq' ? 'active' : ''}`}
                        onClick={() => { setTab('dlq'); setStatusFilter(''); }}
                    >
                        <AlertTriangle size={16} className="me-1" />
                        {t('settings.integration_dlq.dlq_title')}
                    </button>
                </li>
                <li className="nav-item">
                    <button
                        className={`nav-link ${tab === 'payment' ? 'active' : ''}`}
                        onClick={() => { setTab('payment'); setShowArchived(false); }}
                    >
                        {t('settings.integration_dlq.payment_queue')}
                    </button>
                </li>
                <li className="nav-item">
                    <button
                        className={`nav-link ${tab === 'sms' ? 'active' : ''}`}
                        onClick={() => { setTab('sms'); setShowArchived(false); }}
                    >
                        {t('settings.integration_dlq.message_queue')}
                    </button>
                </li>
            </ul>

            <div className="card">
                <div className="card-body">
                    {tab === 'dlq' ? (
                        <div className="d-flex justify-content-between align-items-center mb-3">
                            <h5 className="mb-0">{t('settings.integration_dlq.dlq_items')}</h5>
                            <div className="form-check">
                                <input
                                    type="checkbox"
                                    className="form-check-input"
                                    id="showArchived"
                                    checked={showArchived}
                                    onChange={(e) => setShowArchived(e.target.checked)}
                                />
                                <label className="form-check-label" htmlFor="showArchived">
                                    {t('settings.integration_dlq.show_archived')}
                                </label>
                            </div>
                        </div>
                    ) : (
                        <div className="d-flex justify-content-between align-items-center mb-3">
                            <h5 className="mb-0">{tab === 'payment' ? t('settings.integration_dlq.payment_attempts') : t('settings.integration_dlq.message_attempts')}</h5>
                            <select
                                className="form-select"
                                style={{ width: 200 }}
                                value={statusFilter}
                                onChange={(e) => setStatusFilter(e.target.value)}
                            >
                                <option value="">{t('settings.integration_dlq.filters.all_states')}</option>
                                <option value="pending">{t('settings.integration_dlq.filters.pending')}</option>
                                <option value="processing">{t('settings.integration_dlq.filters.processing')}</option>
                                <option value={tab === 'payment' ? 'succeeded' : 'sent'}>
                                    {tab === 'payment' ? t('settings.integration_dlq.filters.successful') : t('settings.integration_dlq.filters.successful')}
                                </option>
                                <option value="permanently_failed">{t('settings.integration_dlq.filters.permanent_failure')}</option>
                            </select>
                        </div>
                    )}

                    {loading ? (
                        <p className="text-muted">{t('settings.integration_dlq.loading')}</p>
                    ) : items.length === 0 ? (
                        <p className="text-muted">{t('settings.integration_dlq.no_items')}</p>
                    ) : tab === 'dlq' ? (
                        <div className="table-responsive">
                            <table className="table table-hover">
                                <thead>
                                    <tr>
                                        <th>#</th>
                                        <th>{t('settings.integration_dlq.table.type')}</th>
                                        <th>{t('settings.integration_dlq.table.provider')}</th>
                                        <th>{t('settings.integration_dlq.table.reason')}</th>
                                        <th>{t('settings.integration_dlq.table.failure_date')}</th>
                                        <th>{t('settings.integration_dlq.table.status')}</th>
                                        <th>{t('settings.integration_dlq.table.actions')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {items.map((it) => (
                                        <tr key={it.id}>
                                            <td>{it.id}</td>
                                            <td>
                                                <span className="badge bg-info">
                                                    {it.queue_type === 'payment' ? t('settings.integration_dlq.payment_queue') : t('settings.integration_dlq.message_queue')}
                                                </span>
                                            </td>
                                            <td>{it.provider || '-'}</td>
                                            <td style={{ maxWidth: 300 }}>
                                                <span title={it.reason} style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', display: 'block' }}>
                                                    {it.reason || '-'}
                                                </span>
                                            </td>
                                            <td>{it.created_at ? new Date(it.created_at).toLocaleString('ar') : '-'}</td>
                                            <td>
                                                {it.archived_at ? (
                                                    <span className="badge bg-secondary">{t('settings.integration_dlq.badges.archived')}</span>
                                                ) : (
                                                    <span className="badge bg-danger">{t('settings.integration_dlq.badges.active')}</span>
                                                )}
                                            </td>
                                            <td>
                                                <div className="d-flex gap-2">
                                                    <button
                                                        className="btn btn-sm btn-outline-primary"
                                                        onClick={() => openDetail(it.id)}
                                                        title={t('settings.integration_dlq.buttons.details')}
                                                    >
                                                        <Eye size={14} />
                                                    </button>
                                                    {!it.archived_at && (
                                                        <>
                                                            <button
                                                                className="btn btn-sm btn-outline-success"
                                                                onClick={() => replay(it.id)}
                                                                title={t('settings.integration_dlq.buttons.resend')}
                                                            >
                                                                <RotateCcw size={14} />
                                                            </button>
                                                            <button
                                                                className="btn btn-sm btn-outline-secondary"
                                                                onClick={() => archive(it.id)}
                                                                title={t('settings.integration_dlq.buttons.archive')}
                                                            >
                                                                <Archive size={14} />
                                                            </button>
                                                        </>
                                                    )}
                                                </div>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    ) : (
                        <div className="table-responsive">
                            <table className="table table-hover">
                                <thead>
                                    <tr>
                                        <th>#</th>
                                        <th>{t('settings.integration_dlq.table.provider')}</th>
                                        {tab === 'payment' ? (
                                            <>
                                                <th>{t('settings.integration_dlq.table.amount')}</th>
                                                <th>{t('settings.integration_dlq.table.currency')}</th>
                                            </>
                                        ) : (
                                            <th>{t('settings.integration_dlq.table.recipient')}</th>
                                        )}
                                        <th>{t('settings.integration_dlq.table.attempts')}</th>
                                        <th>{t('settings.integration_dlq.table.status')}</th>
                                        <th>{t('settings.integration_dlq.table.next_attempt')}</th>
                                        <th>{t('settings.integration_dlq.table.last_error')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {items.map((it) => (
                                        <tr key={it.id}>
                                            <td>{it.id}</td>
                                            <td>{it.provider || '-'}</td>
                                            {tab === 'payment' ? (
                                                <>
                                                    <td>{it.amount?.toLocaleString?.() || it.amount}</td>
                                                    <td>{it.currency}</td>
                                                </>
                                            ) : (
                                                <td>{it.recipient_phone || '-'}</td>
                                            )}
                                            <td>{it.retry_count}/{it.max_retries}</td>
                                            <td><StatusBadge status={it.status} /></td>
                                            <td>{it.next_retry_at ? new Date(it.next_retry_at).toLocaleString('ar') : '-'}</td>
                                            <td style={{ maxWidth: 300 }}>
                                                <span title={it.last_error} style={{ whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis', display: 'block' }}>
                                                    {it.last_error || '-'}
                                                </span>
                                            </td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    )}
                </div>
            </div>

            {/* Detail Modal */}
            {detail && (
                <div className="modal show d-block" tabIndex="-1" style={{ background: 'rgba(0,0,0,0.5)' }}>
                    <div className="modal-dialog modal-lg">
                        <div className="modal-content">
                            <div className="modal-header">
                                <h5 className="modal-title">{t('settings.integration_dlq.modal.title')}{detail.id}</h5>
                                <button type="button" className="btn-close" onClick={() => setDetail(null)}><X size={20} /></button>
                            </div>
                            <div className="modal-body">
                                <dl className="row">
                                    <dt className="col-sm-4">{t('settings.integration_dlq.modal.type')}</dt>
                                    <dd className="col-sm-8">{detail.queue_type}</dd>
                                    <dt className="col-sm-4">{t('settings.integration_dlq.modal.provider')}</dt>
                                    <dd className="col-sm-8">{detail.provider || '-'}</dd>
                                    <dt className="col-sm-4">{t('settings.integration_dlq.modal.original_item_id')}</dt>
                                    <dd className="col-sm-8">{detail.queue_item_id}</dd>
                                    <dt className="col-sm-4">{t('settings.integration_dlq.modal.reason')}</dt>
                                    <dd className="col-sm-8 text-danger">{detail.reason || '-'}</dd>
                                    <dt className="col-sm-4">{t('settings.integration_dlq.modal.failure_date')}</dt>
                                    <dd className="col-sm-8">{detail.created_at ? new Date(detail.created_at).toLocaleString('ar') : '-'}</dd>
                                </dl>

                                <h6 className="mt-3">{t('settings.integration_dlq.modal.payload')}</h6>
                                <pre className="bg-light p-2 rounded" style={{ maxHeight: 200, overflow: 'auto', fontSize: 12 }}>
                                    {JSON.stringify(detail.payload || {}, null, 2)}
                                </pre>

                                {detail.gateway_response && (
                                    <>
                                        <h6 className="mt-3">{t('settings.integration_dlq.modal.gateway_response')}</h6>
                                        <pre className="bg-light p-2 rounded" style={{ maxHeight: 200, overflow: 'auto', fontSize: 12 }}>
                                            {JSON.stringify(detail.gateway_response, null, 2)}
                                        </pre>
                                    </>
                                )}
                            </div>
                            <div className="modal-footer">
                                <button type="button" className="btn btn-secondary" onClick={() => setDetail(null)}>
                                    {t('settings.integration_dlq.modal.close')}
                                </button>
                                {!detail.archived_at && (
                                    <>
                                        <button type="button" className="btn btn-outline-secondary" onClick={() => archive(detail.id)}>
                                            <Archive size={14} className="me-1" />
                                            {t('settings.integration_dlq.modal.archive')}
                                        </button>
                                        <button type="button" className="btn btn-success" onClick={() => replay(detail.id)}>
                                            <RotateCcw size={14} className="me-1" />
                                            {t('settings.integration_dlq.modal.resend')}
                                        </button>
                                    </>
                                )}
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}

export default IntegrationDLQ
