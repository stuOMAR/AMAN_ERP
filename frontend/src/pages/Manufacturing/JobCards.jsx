import { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { Play, Pause, CheckCircle, Clock, Factory } from 'lucide-react'
import api from '../../utils/api'
import { toastEmitter } from '../../utils/toastEmitter'
import { useToast } from '../../context/ToastContext'
import '../../components/ModuleStyles.css'
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'
import { formatNumber } from '../../utils/format'

export default function JobCards() {
    const { t } = useTranslation()
    const { showToast } = useToast()

    const [operations, setOperations] = useState([])
    const [loading, setLoading] = useState(true)
    const [actionLoading, setActionLoading] = useState(null)

    useEffect(() => {
        fetchOperations()
    }, [])

    const fetchOperations = async () => {
        try {
            setLoading(true)
            const res = await api.get('/manufacturing/orders/operations/active')
            setOperations(res.data)
        } catch (err) {
            toastEmitter.emit(t('common.error'), 'error')
        } finally {
            setLoading(false)
        }
    }

    const handleAction = async (opId, action, qty = 0) => {
        setActionLoading(opId)
        try {
            let url = `/manufacturing/operations/${opId}/${action}`
            if (action === 'complete') url += `?completed_qty=${qty}`

            await api.post(url)
            showToast(t(`manufacturing.job_card.${action}_success`, 'تم تحديث العملية بنجاح'), 'success')
            fetchOperations()
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error_occurred'), 'error')
        } finally {
            setActionLoading(null)
        }
    }

    const getStatusStyle = (status) => {
        switch (status) {
            case 'in_progress': return { bg: '#fff7ed', color: '#c2410c', border: '#ffedd5' }
            case 'completed': return { bg: '#f0fdf4', color: '#15803d', border: '#dcfce7' }
            case 'paused': return { bg: '#fef2f2', color: '#b91c1c', border: '#fee2e2' }
            default: return { bg: '#f8fafc', color: '#475569', border: '#f1f5f9' }
        }
    }

    if (loading) {
        return <PageLoading />
    }

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <h1 className="workspace-title">
                    <Clock size={24} className="text-primary" /> {t('manufacturing.job_cards.title')}
                </h1>
                <p className="text-muted">{t('manufacturing.job_cards.subtitle')}</p>
            </div>

            <div className="modules-grid">
                {operations.length === 0 ? (
                    <div style={{ gridColumn: '1 / -1', textAlign: 'center', padding: '40px' }}>
                        <div style={{ fontSize: '48px', marginBottom: '12px' }}>📋</div>
                        <h3 style={{ color: 'var(--text-secondary)' }}>{t('manufacturing.job_cards.no_active')}</h3>
                    </div>
                ) : (
                    operations.map(op => {
                        const style = getStatusStyle(op.status)
                        return (
                            <div key={op.id} className="section-card" style={{ padding: 0, overflow: 'hidden', border: `1px solid ${style.border}` }}>
                                <div className="card-header" style={{ background: style.bg, display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: `1px solid ${style.border}` }}>
                                    <span className="badge" style={{ background: style.color, color: '#fff' }}>
                                        {t(`manufacturing.status.${op.status}`, op.status)}
                                    </span>
                                    <Link to={`/manufacturing/orders/${op.production_order_id}`} style={{ color: 'var(--text-muted)', fontSize: '13px', textDecoration: 'none' }}>#{op.order_number}</Link>
                                </div>
                                <div style={{ padding: '20px' }}>
                                    <h5 style={{ fontWeight: 700, marginBottom: '6px', fontSize: '15px' }}>{op.operation_description || op.operation_name}</h5>
                                    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', color: 'var(--text-muted)', marginBottom: '16px', fontSize: '13px' }}>
                                        <Factory size={14} /> {op.work_center_name}
                                    </div>

                                    <div style={{ background: 'var(--bg-hover)', borderRadius: '10px', padding: '12px', marginBottom: '16px' }}>
                                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '6px' }}>
                                            <span style={{ color: 'var(--text-muted)', fontSize: '13px' }}>{t('manufacturing.job_cards.planned_time')}:</span>
                                            <span style={{ fontWeight: 700, fontSize: '13px' }}>{op.cycle_time || op.setup_time || '-'} {t('common.minutes')}</span>
                                        </div>
                                        <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                            <span style={{ color: 'var(--text-muted)', fontSize: '13px' }}>{t('manufacturing.job_cards.actual_time')}:</span>
                                            <span style={{ fontWeight: 700, fontSize: '13px', color: 'var(--primary)' }}>{formatNumber(op.actual_run_time || 0, 0)} {t('common.minutes')}</span>
                                        </div>
                                    </div>

                                    <div style={{ display: 'flex', gap: '8px' }}>
                                        {op.status !== 'in_progress' ? (
                                            <button
                                                className="btn btn-primary"
                                                style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}
                                                disabled={actionLoading === op.id}
                                                onClick={() => handleAction(op.id, 'start')}
                                            >
                                                <Play size={16} /> {t('common.start')}
                                            </button>
                                        ) : (
                                            <>
                                                <button
                                                    className="btn btn-warning"
                                                    style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}
                                                    disabled={actionLoading === op.id}
                                                    onClick={() => handleAction(op.id, 'pause')}
                                                >
                                                    <Pause size={16} /> {t('common.pause')}
                                                </button>
                                                <button
                                                    className="btn btn-success"
                                                    style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: '6px' }}
                                                    disabled={actionLoading === op.id}
                                                    onClick={() => {
                                                        const qty = prompt(t('manufacturing.job_cards.enter_qty'), op.planned_quantity || 1)
                                                        if (qty) handleAction(op.id, 'complete', qty)
                                                    }}
                                                >
                                                    <CheckCircle size={16} /> {t('common.complete')}
                                                </button>
                                            </>
                                        )}
                                    </div>
                                </div>
                            </div>
                        )
                    })
                )}
            </div>
        </div>
    )
}
