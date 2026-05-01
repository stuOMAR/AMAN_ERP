import { useState, useEffect } from 'react'
import { wpsAPI, hrAPI } from '../../utils/api'
import { toastEmitter } from '../../utils/toastEmitter'
import { formatNumber } from '../../utils/format'
import { useTranslation } from 'react-i18next'
import BackButton from '../../components/common/BackButton'

function WPSExport() {
    const { t } = useTranslation()
    const [periods, setPeriods] = useState([])
    const [selectedPeriod, setSelectedPeriod] = useState('')
    const [exportFormat, setExportFormat] = useState('sif')
    const [preview, setPreview] = useState(null)
    const [loading, setLoading] = useState(false)

    useEffect(() => {
        hrAPI.listPayrollPeriods().then(r => setPeriods(r.data)).catch(() => toastEmitter.emit(t('common.error'), 'error'))
    }, [])

    const handlePreview = async () => {
        if (!selectedPeriod) return
        setLoading(true)
        try {
            const res = await wpsAPI.previewWPS(selectedPeriod)
            setPreview(res.data)
        } catch (err) {
            toastEmitter.emit(err.response?.data?.detail || t('common.error'), 'error')
        } finally { setLoading(false) }
    }

    const handleExport = async () => {
        if (!selectedPeriod) return
        setLoading(true)
        try {
            const res = await wpsAPI.exportWPS({ period_id: Number(selectedPeriod), format: exportFormat })
            const isSif = exportFormat === 'sif'
            const mimeType = isSif ? 'text/plain' : 'text/csv'
            const ext = isSif ? 'sif' : 'csv'
            const blob = new Blob([res.data], { type: mimeType })
            const url = window.URL.createObjectURL(blob)
            const a = document.createElement('a')
            a.href = url
            a.download = `WPS_${selectedPeriod}.${ext}`
            a.click()
            window.URL.revokeObjectURL(url)
            toastEmitter.emit(t('wps.exported'), 'success')
        } catch (err) {
            toastEmitter.emit(err.response?.data?.detail || t('common.error'), 'error')
        } finally { setLoading(false) }
    }

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">🏦 {t('wps.title')}</h1>
                    <p className="workspace-subtitle">{t('wps.subtitle')}</p>
                </div>
            </div>

            <div className="card p-4">
                <div className="alert alert-info mb-3">
                    ⚠️ {t('wps.sa_only_note')}
                </div>
                <div className="form-grid-3">
                    <div className="form-group">
                        <label>{t('wps.payroll_period')}</label>
                        <select className="form-select" value={selectedPeriod} onChange={e => setSelectedPeriod(e.target.value)}>
                            <option value="">{t('common.select')}</option>
                            {periods.map(p => (
                                <option key={p.id} value={p.id}>{p.name || `${p.month}/${p.year}`}</option>
                            ))}
                        </select>
                    </div>
                    <div className="form-group">
                        <label>{t('wps.format')}</label>
                        <select className="form-select" value={exportFormat} onChange={e => setExportFormat(e.target.value)}>
                            <option value="sif">SIF — SAMA Fixed-Width (بنكي)</option>
                            <option value="csv">CSV — Spreadsheet (قراءة)</option>
                        </select>
                    </div>
                    <div className="form-group" style={{ display: 'flex', alignItems: 'flex-end', gap: 8 }}>
                        <button className="btn btn-secondary" onClick={handlePreview} disabled={!selectedPeriod || loading}>
                            👁️ {t('wps.preview')}
                        </button>
                        <button className="btn btn-primary" onClick={handleExport} disabled={!selectedPeriod || loading}>
                            📥 {t('wps.export_sif')}
                        </button>
                    </div>
                </div>
            </div>

            {preview && (
                <div className="card mt-4">
                    <div className="p-4">
                        <h3 className="card-title">{t('wps.preview_results')} ({preview.entries?.length || 0} {t('common.records')})</h3>
                        {preview.warnings?.length > 0 && (
                            <div className="alert alert-warning mt-2">
                                {preview.warnings.map((w, i) => <div key={i}>⚠️ {w}</div>)}
                            </div>
                        )}
                    </div>
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>{t('common.employee')}</th>
                                <th>{t('wps.employee_id')}</th>
                                <th>{t('wps.iban')}</th>
                                <th>{t('wps.salary')}</th>
                                <th>{t('wps.allowances')}</th>
                                <th>{t('wps.deductions')}</th>
                                <th>{t('wps.net')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {(preview.entries || []).map((e, i) => (
                                <tr key={i}>
                                    <td>{e.employee_name}</td>
                                    <td>{e.employee_id_number || '-'}</td>
                                    <td className="text-xs">{e.iban || <span className="text-danger">{t('wps.missing_iban')}</span>}</td>
                                    <td>{formatNumber(e.basic_salary)}</td>
                                    <td>{formatNumber(e.allowances)}</td>
                                    <td>{formatNumber(e.deductions)}</td>
                                    <td className="font-bold">{formatNumber(e.net_salary)}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    )
}

export default WPSExport
