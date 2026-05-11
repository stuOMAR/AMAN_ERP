import { useState, useEffect } from 'react'
import { treasuryAPI } from '../../utils/api'
import { useTranslation } from 'react-i18next'
import { formatShortDate } from '../../utils/dateUtils'
import { useToast } from '../../context/ToastContext'
import { useBranch } from '../../context/BranchContext'
import { getCurrency } from '../../utils/auth'
import BackButton from '../../components/common/BackButton'
import { PageLoading } from '../../components/common/LoadingStates'

function BankImport() {
    const { t } = useTranslation()
    const { showToast } = useToast()
    const { currentBranch } = useBranch()
    const currency = getCurrency()
    const [batches, setBatches] = useState([])
    const [loading, setLoading] = useState(true)
    const [initialLoad, setInitialLoad] = useState(true)
    const [uploading, setUploading] = useState(false)
    const [selectedBatch, setSelectedBatch] = useState(null)
    const [lines, setLines] = useState([])

    useEffect(() => {
        const timer = setTimeout(() => {
            const params = {};
            if (currentBranch?.id) params.branch_id = currentBranch.id;
            treasuryAPI.listBankImports(params).then(r => setBatches(r.data)).catch(console.error).finally(() => { setLoading(false); setInitialLoad(false); })
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch])

    const handleUpload = async (e) => {
        const file = e.target.files[0]
        if (!file) return
        setUploading(true)
        try {
            const res = await treasuryAPI.importBankStatement(file)
            showToast(t('bank_import.uploaded', { count: res.data.lines_imported }), 'success')
            setBatches(prev => [res.data, ...prev])
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        } finally {
            setUploading(false)
            e.target.value = ''
        }
    }

    const viewBatch = async (batchId) => {
        try {
            const res = await treasuryAPI.getBankImportLines(batchId)
            setLines(res.data)
            setSelectedBatch(batchId)
        } catch (err) {
            showToast(t('common.error'), 'error')
        }
    }

    const handleAutoMatch = async (batchId) => {
        try {
            const res = await treasuryAPI.autoMatchBankImport(batchId)
            showToast(t('bank_import.matched', { count: res.data.matched_count }), 'success')
            viewBatch(batchId)
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        }
    }

    if (initialLoad) return <PageLoading />

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">📥 {t('bank_import.title')}</h1>
                    <p className="workspace-subtitle">{t('bank_import.subtitle')}</p>
                </div>
                <div className="header-actions">
                    <label className="btn btn-primary" style={{ cursor: 'pointer' }}>
                        {uploading ? t('common.uploading') : `📤 ${t('bank_import.upload_csv')}`}
                        <input type="file" accept=".csv" onChange={handleUpload} style={{ display: 'none' }} disabled={uploading} />
                    </label>
                </div>
            </div>

            {/* Batches List */}
            <div className="card">
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>{t('bank_import.batch_id')}</th>
                            <th>{t('bank_import.filename')}</th>
                            <th>{t('bank_import.lines_count')}</th>
                            <th>{t('common.date')}</th>
                            <th>{t('common.actions')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {batches.length === 0 ? (
                            <tr><td colSpan="5" className="text-center py-5 text-muted">{t('bank_import.empty')}</td></tr>
                        ) : batches.map(b => (
                            <tr key={b.id} className={selectedBatch === b.id ? 'bg-light' : ''}>
                                <td className="font-medium">#{b.id}</td>
                                <td>{b.filename}</td>
                                <td>{b.lines_imported || b.line_count || '-'}</td>
                                <td>{formatShortDate(b.created_at)}</td>
                                <td className="flex gap-1">
                                    <button className="btn-icon" onClick={() => viewBatch(b.id)} title={t('common.view')}>👁️</button>
                                    <button className="btn btn-secondary btn-sm" onClick={() => handleAutoMatch(b.id)}>🔗 {t('bank_import.auto_match')}</button>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            </div>

            {/* Lines Detail */}
            {selectedBatch && lines.length > 0 && (
                <div className="card mt-4">
                    <div className="p-4">
                        <h3 className="card-title">{t('bank_import.lines')} - #{selectedBatch}</h3>
                    </div>
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>{t('common.date')}</th>
                                <th>{t('common.description')}</th>
                                <th>{t('common.reference')}</th>
                                <th>{t('common.debit')}</th>
                                <th>{t('common.credit')}</th>
                                <th>{t('bank_import.match_status')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {lines.map((l, i) => (
                                <tr key={i}>
                                    <td>{l.transaction_date ? formatShortDate(l.transaction_date) : '-'}</td>
                                    <td>{l.description}</td>
                                    <td>{l.reference || '-'}</td>
                                    <td className="text-danger">{l.debit ? Number(l.debit).toLocaleString() : '-'}</td>
                                    <td className="text-success">{l.credit ? Number(l.credit).toLocaleString() : '-'}</td>
                                    <td>
                                        <span className={`status-badge ${l.matched ? 'success' : 'draft'}`}>
                                            {l.matched ? t('bank_import.matched_label') : t('bank_import.unmatched')}
                                        </span>
                                    </td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            )}
        </div>
    )
}

export default BankImport
