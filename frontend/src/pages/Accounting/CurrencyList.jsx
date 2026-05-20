import React, { useState, useEffect, useMemo } from 'react'
import { useTranslation } from 'react-i18next'
import { currenciesAPI } from '../../utils/api'
import { useToast } from '../../context/ToastContext'
import { getCurrency, hasPermission } from '../../utils/auth'
import { Plus, Edit2, Trash2, History, RefreshCw, DollarSign, X } from 'lucide-react'

import BackButton from '../../components/common/BackButton';
import DataTable from '../../components/common/DataTable';
import SearchFilter from '../../components/common/SearchFilter';

export default function CurrencyList() {
    const { t } = useTranslation()
    const { showToast } = useToast()
    const [currencies, setCurrencies] = useState([])
    const [loading, setLoading] = useState(true)
    const [showModal, setShowModal] = useState(false)
    const [editingCurrency, setEditingCurrency] = useState(null)
    const [showRateModal, setShowRateModal] = useState(false)
    const [selectedCurrency, setSelectedCurrency] = useState(null)
    const [rateHistory, setRateHistory] = useState([])
    const [historyLoading, setHistoryLoading] = useState(false)
    const [searchQuery, setSearchQuery] = useState('')

    // Form Data
    const [formData, setFormData] = useState({
        code: '',
        name: '',
        name_en: '',
        symbol: '',
        is_base: false,
        current_rate: 1.0,
        is_active: true
    })

    const [rateData, setRateData] = useState({
        rate: '',
        rate_date: new Date().toISOString().split('T')[0]
    })
    const canManageCurrencies = hasPermission(['accounting.manage', 'currencies.manage'])
    const permissionDenied = () => showToast(t('common.permission_denied', 'ليس لديك صلاحية تنفيذ هذا الإجراء'), 'error')

    useEffect(() => {
        fetchCurrencies()
    }, [])

    const fetchCurrencies = async () => {
        try {
            setLoading(true)
            const response = await currenciesAPI.list()
            setCurrencies(response.data)
        } catch (error) {
            console.error(error)
            showToast(t('common.error_loading'), 'error')
        } finally {
            setLoading(false)
        }
    }

    const fetchHistory = async (id) => {
        try {
            setHistoryLoading(true)
            const response = await currenciesAPI.getHistory(id)
            setRateHistory(response.data)
        } catch (error) {
            console.error(error)
        } finally {
            setHistoryLoading(false)
        }
    }

    const openModal = (curr = null) => {
        if (!canManageCurrencies) {
            permissionDenied()
            return
        }
        if (curr) {
            setEditingCurrency(curr)
            setFormData({
                code: curr.code || '',
                name: curr.name || '',
                name_en: curr.name_en || '',
                symbol: curr.symbol || '',
                is_base: !!curr.is_base,
                current_rate: curr.current_rate || 1.0,
                is_active: curr.is_active ?? true
            })
        } else {
            setEditingCurrency(null)
            setFormData({
                code: '',
                name: '',
                name_en: '',
                symbol: '',
                is_base: false,
                current_rate: 1.0,
                is_active: true
            })
        }
        setShowModal(true)
    }

    const openRateModal = (curr) => {
        if (!canManageCurrencies) {
            permissionDenied()
            return
        }
        setSelectedCurrency(curr)
        setRateData({
            rate: curr.current_rate || '',
            rate_date: new Date().toISOString().split('T')[0]
        })
        fetchHistory(curr.id)
        setShowRateModal(true)
    }

    const handleSubmit = async (e) => {
        e.preventDefault()
        if (!canManageCurrencies) {
            permissionDenied()
            return
        }
        try {
            if (editingCurrency) {
                await currenciesAPI.update(editingCurrency.id, formData)
                showToast(t('common.success_update'), 'success')
            } else {
                await currenciesAPI.create(formData)
                showToast(t('common.success_add'), 'success')
            }
            setShowModal(false)
            fetchCurrencies()
        } catch (error) {
            console.error(error)
        }
    }

    const handleRateSubmit = async (e) => {
        e.preventDefault()
        if (!canManageCurrencies) {
            permissionDenied()
            return
        }
        try {
            await currenciesAPI.addRate({
                currency_id: selectedCurrency.id,
                rate: rateData.rate,
                rate_date: rateData.rate_date || null
            })
            showToast(t('accounting.currencies.rate_updated'), 'success')
            setShowRateModal(false)
            fetchCurrencies()
        } catch (error) {
            console.error(error)
        }
    }

    const handleDelete = async (id) => {
        if (!canManageCurrencies) {
            permissionDenied()
            return
        }
        if (window.confirm(t('common.confirm_delete'))) {
            try {
                await currenciesAPI.delete(id)
                showToast(t('common.success_delete'), 'success')
                fetchCurrencies()
            } catch (error) {
                console.error(error)
            }
        }
    }

    const filteredCurrencies = useMemo(() =>
        currencies.filter(c =>
            c.name?.toLowerCase().includes(searchQuery.toLowerCase()) ||
            c.code?.toLowerCase().includes(searchQuery.toLowerCase())
        ), [currencies, searchQuery]
    )

    const columns = useMemo(() => [
        {
            key: 'code',
            label: t('accounting.currencies.table.code'),
            render: (val) => (
                <span className="badge rounded-pill bg-light text-dark border px-3 font-mono">{val}</span>
            ),
        },
        {
            key: 'name',
            label: t('accounting.currencies.table.name'),
            render: (val, row) => (
                <span className="fw-semibold text-dark">{val} {row.name_en ? `(${row.name_en})` : ''}</span>
            ),
        },
        {
            key: 'symbol',
            label: t('accounting.currencies.table.symbol'),
            style: { textAlign: 'center' },
            headerStyle: { textAlign: 'center' },
            render: (val) => <span className="fw-bold">{val}</span>,
        },
        {
            key: 'is_base',
            label: t('accounting.currencies.table.is_base'),
            style: { textAlign: 'center' },
            headerStyle: { textAlign: 'center' },
            render: (val) => val ? (
                <span className="badge bg-success-subtle text-success border px-3">{t('accounting.currencies.base_label')}</span>
            ) : (
                <span className="text-muted small">{t('accounting.currencies.secondary_label')}</span>
            ),
        },
        {
            key: 'current_rate',
            label: t('accounting.currencies.table.rate'),
            style: { textAlign: 'end' },
            headerStyle: { textAlign: 'end' },
            render: (val, row) => (
                <span className="font-mono">
                    {val}
                    {canManageCurrencies && (
                        <button
                            onClick={(e) => { e.stopPropagation(); openRateModal(row); }}
                            className="btn-icon ms-2"
                            style={{ width: '28px', height: '28px' }}
                            title={t('accounting.currencies.update_rate')}
                        >
                            <History size={14} />
                        </button>
                    )}
                </span>
            ),
        },
        {
            key: '_actions',
            label: t('common.actions'),
            width: '120px',
            style: { textAlign: 'center' },
            headerStyle: { textAlign: 'center' },
            render: (_, row) => canManageCurrencies ? (
                <div className="d-flex justify-content-center gap-2">
                    <button
                        onClick={(e) => { e.stopPropagation(); openModal(row); }}
                        className="btn-icon"
                        style={{ width: '30px', height: '30px', background: 'var(--bg-secondary)', color: 'var(--text-secondary)' }}
                    >
                        <Edit2 size={14} />
                    </button>
                    {!row.is_base && (
                        <button
                            onClick={(e) => { e.stopPropagation(); handleDelete(row.id); }}
                            className="btn-icon"
                            style={{ width: '30px', height: '30px', background: '#fee2e2', color: '#ef4444' }}
                        >
                            <Trash2 size={14} />
                        </button>
                    )}
                </div>
            ) : null,
        },
    ], [t, canManageCurrencies])

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="d-flex align-items-center justify-content-between w-100">
                    <div>
                        <h1 className="workspace-title" style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                            <DollarSign size={28} className="text-primary" />
                            {t('common.currencies')}
                        </h1>
                        <p className="workspace-subtitle">{t('accounting.currencies.subtitle')}</p>
                    </div>
                    {canManageCurrencies && (
                        <button className="btn btn-primary shadow-sm" onClick={() => openModal()}>
                            <Plus size={18} />
                            {t('common.add_new')}
                        </button>
                    )}
                </div>
            </div>

            <div className="metrics-grid mb-4">
                <div className="metric-card">
                    <div className="metric-label">{t('accounting.currencies.total_count')}</div>
                    <div className="metric-value text-primary">{currencies.length}</div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('accounting.currencies.base_currency')}</div>
                    <div className="metric-value text-success">
                        {currencies.find(c => c.is_base)?.code || getCurrency()}
                    </div>
                </div>
            </div>

            <SearchFilter
                value={searchQuery}
                onChange={setSearchQuery}
                placeholder={t('common.search')}
            />

            <DataTable
                columns={columns}
                data={filteredCurrencies}
                loading={loading}
                emptyIcon={<DollarSign size={40} />}
                emptyTitle={t('common.no_data')}
                rowKey="id"
                paginate={true}
            />

            {/* Edit/Create Modal */}
            {showModal && canManageCurrencies && (
                <div className="modal-overlay fade-in">
                    <div className="modal-content" style={{ maxWidth: '480px' }}>
                        <div className="modal-header">
                            <h2 className="modal-title">
                                {editingCurrency ? t('accounting.currencies.form.edit_title') : t('accounting.currencies.form.add_title')}
                            </h2>
                            <button onClick={() => setShowModal(false)} className="btn-icon border-0 bg-transparent"><X size={20} /></button>
                        </div>

                        <form onSubmit={handleSubmit}>
                            <div className="modal-body p-4">
                                <div className="form-group">
                                    <label className="form-label">{t('accounting.currencies.form.code')} *</label>
                                    <input
                                        type="text"
                                        maxLength="3"
                                        className="form-input font-mono"
                                        value={formData.code}
                                        onChange={(e) => setFormData({ ...formData, code: e.target.value.toUpperCase() })}
                                        required
                                        placeholder="USD"
                                        dir="ltr"
                                    />
                                </div>

                                <div className="row g-3">
                                    <div className="col-md-6">
                                        <div className="form-group mb-3">
                                            <label className="form-label">{t('accounting.currencies.form.name_ar')} *</label>
                                            <input
                                                type="text"
                                                className="form-input"
                                                value={formData.name}
                                                onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                                                required
                                            />
                                        </div>
                                    </div>
                                    <div className="col-md-6">
                                        <div className="form-group mb-3">
                                            <label className="form-label">{t('accounting.currencies.form.name_en')}</label>
                                            <input
                                                type="text"
                                                className="form-input"
                                                value={formData.name_en}
                                                onChange={(e) => setFormData({ ...formData, name_en: e.target.value })}
                                                dir="ltr"
                                            />
                                        </div>
                                    </div>
                                </div>

                                <div className="form-group">
                                    <label className="form-label">{t('accounting.currencies.form.symbol')}</label>
                                    <input
                                        type="text"
                                        className="form-input w-25"
                                        value={formData.symbol}
                                        onChange={(e) => setFormData({ ...formData, symbol: e.target.value })}
                                        placeholder="$"
                                        dir="ltr"
                                    />
                                </div>

                                <div className="bg-primary-subtle p-3 rounded-3 mt-4 border border-primary-light">
                                    <label className="d-flex align-items-center gap-3 cursor-pointer mb-0">
                                        <input
                                            type="checkbox"
                                            checked={formData.is_base}
                                            onChange={(e) => setFormData({ ...formData, is_base: e.target.checked })}
                                            className="form-check-input"
                                            style={{ width: '20px', height: '20px' }}
                                        />
                                        <div>
                                            <span className="d-block fw-bold text-dark">{t('accounting.currencies.form.set_base')}</span>
                                            <span className="text-muted small">
                                                {t('accounting.currencies.form.base_hint')}
                                            </span>
                                        </div>
                                    </label>
                                </div>
                            </div>

                            <div className="modal-footer">
                                <button type="button" onClick={() => setShowModal(false)} className="btn btn-secondary">{t('common.cancel')}</button>
                                <button type="submit" className="btn btn-primary px-4">{t('common.save')}</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {/* Rate History Modal */}
            {showRateModal && selectedCurrency && canManageCurrencies && (
                <div className="modal-overlay fade-in">
                    <div className="modal-content" style={{ maxWidth: '550px' }}>
                        <div className="modal-header">
                            <div>
                                <h2 className="modal-title">{t('accounting.currencies.rate.title')}</h2>
                                <p className="text-muted small mb-0">{selectedCurrency.name} ({selectedCurrency.code})</p>
                            </div>
                            <button onClick={() => setShowRateModal(false)} className="btn-icon border-0 bg-transparent"><X size={20} /></button>
                        </div>

                        <div className="modal-body p-4">
                            <form onSubmit={handleRateSubmit} className="bg-light p-4 rounded-3 border mb-4">
                                <div className="row g-3">
                                    <div className="col-md-6">
                                        <label className="form-label fw-bold">{t('accounting.currencies.rate.new_rate')}</label>
                                        <div style={{ position: 'relative' }}>
                                            <input
                                                type="number"
                                                step="0.000001"
                                                className="form-input w-100"
                                                value={rateData.rate}
                                                onChange={(e) => setRateData({ ...rateData, rate: e.target.value })}
                                                required
                                                style={{ paddingLeft: '50px' }}
                                            />
                                            <span style={{
                                                position: 'absolute',
                                                left: '10px',
                                                top: '50%',
                                                transform: 'translateY(-50%)',
                                                color: 'var(--text-secondary)',
                                                fontWeight: 'bold'
                                            }}>
                                                {selectedCurrency.symbol || selectedCurrency.code}
                                            </span>
                                        </div>
                                        <small className="text-muted d-block mt-1">
                                            1 {selectedCurrency.code} = {rateData.rate} {currencies.find(c => c.is_base)?.code || 'Base'}
                                        </small>
                                    </div>
                                    <div className="col-md-6">
                                        <label className="form-label fw-bold">{t('accounting.currencies.rate.date')}</label>
                                        <input

                                            className="form-input w-100"
                                            value={rateData.rate_date}
                                            onChange={(e) => setRateData({ ...rateData, rate_date: e.target.value })}
                                            required
                                        />
                                    </div>
                                    <div className="col-12 mt-3">
                                        <button type="submit" className="btn btn-success w-100 d-flex justify-content-center align-items-center gap-2">
                                            <RefreshCw size={18} />
                                            {t('common.update')}
                                        </button>
                                    </div>
                                </div>
                            </form>

                            <h3 className="fw-bold text-dark mb-3 small">{t('accounting.currencies.rate.history')}</h3>
                            <div className="data-table-container shadow-none border">
                                <table className="data-table">
                                    <thead className="bg-light">
                                        <tr>
                                            <th className="py-2">{t('accounting.currencies.rate.history_date')}</th>
                                            <th className="py-2">{t('accounting.currencies.rate.history_rate')}</th>
                                            <th className="py-2">{t('accounting.currencies.rate.history_source')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {historyLoading ? (
                                            <tr><td colSpan="3" className="text-center p-3 text-muted">{t('common.loading')}...</td></tr>
                                        ) : rateHistory.length === 0 ? (
                                            <tr><td colSpan="3" className="text-center p-3 text-muted">{t('accounting.currencies.no_history')}</td></tr>
                                        ) : (
                                            rateHistory.map(h => (
                                                <tr key={h.id}>
                                                    <td className="py-2">{h.rate_date}</td>
                                                    <td className="py-2 font-mono">{h.rate}</td>
                                                    <td className="py-2 text-muted small">{h.source}</td>
                                                </tr>
                                            ))
                                        )}
                                    </tbody>
                                </table>
                            </div>
                        </div>
                        <div className="modal-footer">
                            <button onClick={() => setShowRateModal(false)} className="btn btn-secondary px-4">{t('common.close')}</button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}
