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
            toastEmitter.show('فشل تحميل البيانات', 'error')
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
            toastEmitter.show('فشل جلب التفاصيل', 'error')
        }
    }

    const replay = async (id) => {
        if (!window.confirm('إعادة إرسال هذا العنصر إلى قائمة الانتظار؟')) return
        try {
            await integrationQueuesAPI.replayDLQ(id)
            toastEmitter.show('تم إعادة الإرسال', 'success')
            setDetail(null)
            load()
        } catch (err) {
            const msg = err?.response?.data?.detail || 'فشل إعادة الإرسال'
            toastEmitter.show(typeof msg === 'string' ? msg : 'فشل إعادة الإرسال', 'error')
        }
    }

    const archive = async (id) => {
        if (!window.confirm('أرشفة هذا العنصر بدون إعادة إرسال؟')) return
        try {
            await integrationQueuesAPI.archiveDLQ(id)
            toastEmitter.show('تم الأرشفة', 'success')
            setDetail(null)
            load()
        } catch (err) {
            toastEmitter.show('فشل الأرشفة', 'error')
        }
    }

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                        <h1 className="workspace-title">
                            <Inbox size={24} className="me-2" />
                            قوائم انتظار التكاملات و DLQ
                        </h1>
                        <p className="text-muted small mb-0">مراجعة وإدارة المحاولات الفاشلة للمدفوعات والرسائل النصية</p>
                    </div>
                    <button className="btn btn-outline-primary d-flex align-items-center gap-2" onClick={load}>
                        <RefreshCcw size={16} />
                        تحديث
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
                        DLQ (الفشل النهائي)
                    </button>
                </li>
                <li className="nav-item">
                    <button
                        className={`nav-link ${tab === 'payment' ? 'active' : ''}`}
                        onClick={() => { setTab('payment'); setShowArchived(false); }}
                    >
                        قائمة المدفوعات
                    </button>
                </li>
                <li className="nav-item">
                    <button
                        className={`nav-link ${tab === 'sms' ? 'active' : ''}`}
                        onClick={() => { setTab('sms'); setShowArchived(false); }}
                    >
                        قائمة الرسائل
                    </button>
                </li>
            </ul>

            <div className="card">
                <div className="card-body">
                    {tab === 'dlq' ? (
                        <div className="d-flex justify-content-between align-items-center mb-3">
                            <h5 className="mb-0">عناصر DLQ</h5>
                            <div className="form-check">
                                <input
                                    type="checkbox"
                                    className="form-check-input"
                                    id="showArchived"
                                    checked={showArchived}
                                    onChange={(e) => setShowArchived(e.target.checked)}
                                />
                                <label className="form-check-label" htmlFor="showArchived">
                                    عرض المؤرشفة
                                </label>
                            </div>
                        </div>
                    ) : (
                        <div className="d-flex justify-content-between align-items-center mb-3">
                            <h5 className="mb-0">{tab === 'payment' ? 'محاولات المدفوعات' : 'محاولات الرسائل'}</h5>
                            <select
                                className="form-select"
                                style={{ width: 200 }}
                                value={statusFilter}
                                onChange={(e) => setStatusFilter(e.target.value)}
                            >
                                <option value="">جميع الحالات</option>
                                <option value="pending">قيد الانتظار</option>
                                <option value="processing">قيد المعالجة</option>
                                <option value={tab === 'payment' ? 'succeeded' : 'sent'}>
                                    {tab === 'payment' ? 'ناجحة' : 'مُرسلة'}
                                </option>
                                <option value="permanently_failed">فشل نهائي</option>
                            </select>
                        </div>
                    )}

                    {loading ? (
                        <p className="text-muted">جاري التحميل…</p>
                    ) : items.length === 0 ? (
                        <p className="text-muted">لا توجد عناصر</p>
                    ) : tab === 'dlq' ? (
                        <div className="table-responsive">
                            <table className="table table-hover">
                                <thead>
                                    <tr>
                                        <th>#</th>
                                        <th>النوع</th>
                                        <th>المزوّد</th>
                                        <th>السبب</th>
                                        <th>تاريخ الفشل</th>
                                        <th>الحالة</th>
                                        <th>إجراءات</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {items.map((it) => (
                                        <tr key={it.id}>
                                            <td>{it.id}</td>
                                            <td>
                                                <span className="badge bg-info">
                                                    {it.queue_type === 'payment' ? 'مدفوعات' : 'رسائل'}
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
                                                    <span className="badge bg-secondary">مؤرشف</span>
                                                ) : (
                                                    <span className="badge bg-danger">نشط</span>
                                                )}
                                            </td>
                                            <td>
                                                <div className="d-flex gap-2">
                                                    <button
                                                        className="btn btn-sm btn-outline-primary"
                                                        onClick={() => openDetail(it.id)}
                                                        title="تفاصيل"
                                                    >
                                                        <Eye size={14} />
                                                    </button>
                                                    {!it.archived_at && (
                                                        <>
                                                            <button
                                                                className="btn btn-sm btn-outline-success"
                                                                onClick={() => replay(it.id)}
                                                                title="إعادة إرسال"
                                                            >
                                                                <RotateCcw size={14} />
                                                            </button>
                                                            <button
                                                                className="btn btn-sm btn-outline-secondary"
                                                                onClick={() => archive(it.id)}
                                                                title="أرشفة"
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
                                        <th>المزوّد</th>
                                        {tab === 'payment' ? (
                                            <>
                                                <th>المبلغ</th>
                                                <th>العملة</th>
                                            </>
                                        ) : (
                                            <th>المستلم</th>
                                        )}
                                        <th>المحاولات</th>
                                        <th>الحالة</th>
                                        <th>المحاولة التالية</th>
                                        <th>آخر خطأ</th>
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
                                <h5 className="modal-title">تفاصيل DLQ #{detail.id}</h5>
                                <button type="button" className="btn-close" onClick={() => setDetail(null)}><X size={20} /></button>
                            </div>
                            <div className="modal-body">
                                <dl className="row">
                                    <dt className="col-sm-4">النوع</dt>
                                    <dd className="col-sm-8">{detail.queue_type}</dd>
                                    <dt className="col-sm-4">المزوّد</dt>
                                    <dd className="col-sm-8">{detail.provider || '-'}</dd>
                                    <dt className="col-sm-4">معرّف العنصر الأصلي</dt>
                                    <dd className="col-sm-8">{detail.queue_item_id}</dd>
                                    <dt className="col-sm-4">السبب</dt>
                                    <dd className="col-sm-8 text-danger">{detail.reason || '-'}</dd>
                                    <dt className="col-sm-4">تاريخ الفشل</dt>
                                    <dd className="col-sm-8">{detail.created_at ? new Date(detail.created_at).toLocaleString('ar') : '-'}</dd>
                                </dl>

                                <h6 className="mt-3">البيانات (Payload)</h6>
                                <pre className="bg-light p-2 rounded" style={{ maxHeight: 200, overflow: 'auto', fontSize: 12 }}>
                                    {JSON.stringify(detail.payload || {}, null, 2)}
                                </pre>

                                {detail.gateway_response && (
                                    <>
                                        <h6 className="mt-3">رد البوّابة (Gateway Response)</h6>
                                        <pre className="bg-light p-2 rounded" style={{ maxHeight: 200, overflow: 'auto', fontSize: 12 }}>
                                            {JSON.stringify(detail.gateway_response, null, 2)}
                                        </pre>
                                    </>
                                )}
                            </div>
                            <div className="modal-footer">
                                <button type="button" className="btn btn-secondary" onClick={() => setDetail(null)}>
                                    إغلاق
                                </button>
                                {!detail.archived_at && (
                                    <>
                                        <button type="button" className="btn btn-outline-secondary" onClick={() => archive(detail.id)}>
                                            <Archive size={14} className="me-1" />
                                            أرشفة
                                        </button>
                                        <button type="button" className="btn btn-success" onClick={() => replay(detail.id)}>
                                            <RotateCcw size={14} className="me-1" />
                                            إعادة إرسال
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
