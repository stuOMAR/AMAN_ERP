import { useState, useEffect } from 'react'
import { useTranslation } from 'react-i18next'
import { accountingAPI } from '../../utils/api'
import { hasPermission } from '../../utils/auth'
import BackButton from '../../components/common/BackButton'
import DataTable from '../../components/common/DataTable'
import { formatNumber } from '../../utils/format'
import { useToast } from '../../context/ToastContext'
import DateInput from '../../components/common/DateInput';

function ConsolidationView() {
    const { t } = useTranslation()
    const { showToast } = useToast()
    const [entities, setEntities] = useState([])
    const [selectedGroup, setSelectedGroup] = useState('')
    const [asOfDate, setAsOfDate] = useState(new Date().toISOString().split('T')[0])
    const [result, setResult] = useState(null)
    const [balances, setBalances] = useState([])
    const [loading, setLoading] = useState(false)
    const canManageIntercompany = hasPermission(['intercompany.manage', 'accounting.edit'])
    const permissionDenied = () => showToast(t('common.permission_denied', 'ليس لديك صلاحية تنفيذ هذا الإجراء'), 'error')

    useEffect(() => {
        accountingAPI.listEntityGroups()
            .then(res => setEntities(Array.isArray(res.data) ? res.data : []))
            .catch(() => {})
        accountingAPI.getICBalances()
            .then(res => setBalances(Array.isArray(res.data?.balances) ? res.data.balances : []))
            .catch(() => {})
    }, [])

    const runConsolidation = async () => {
        if (!canManageIntercompany) {
            permissionDenied()
            return
        }
        if (!selectedGroup) return
        try {
            setLoading(true)
            const res = await accountingAPI.runConsolidation({
                entity_group_id: parseInt(selectedGroup),
                as_of_date: asOfDate,
            })
            setResult(res.data)
            showToast(t('intercompany.consolidation_success'), 'success')
            // Refresh balances after consolidation
            accountingAPI.getICBalances()
                .then(res => setBalances(Array.isArray(res.data?.balances) ? res.data.balances : []))
                .catch(() => {})
        } catch (e) {
            showToast(e.response?.data?.detail || t('intercompany.consolidation_error'), 'error')
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <h1 className="workspace-title">{t('intercompany.consolidation_subtitle')}</h1>
            </div>

            {/* Run Consolidation */}
            <div className="card" style={{ padding: 16, marginBottom: 16 }}>
                <h3>{t('intercompany.run_consolidation')}</h3>
                <div className="form-row">
                    <div className="form-group">
                        <label>{t('intercompany.select_entity_group')}</label>
                        <select value={selectedGroup} onChange={e => setSelectedGroup(e.target.value)}>
                            <option value="">{t('common.select')}</option>
                            {entities.map(ent => (
                                <option key={ent.id} value={ent.id}>{ent.name}</option>
                            ))}
                        </select>
                    </div>
                    <div className="form-group">
                        <label>{t('intercompany.as_of_date')}</label>
                        <DateInput value={asOfDate} onChange={e => setAsOfDate(e.target.value)} />
                    </div>
                    <div className="form-group" style={{ display: 'flex', alignItems: 'flex-end' }}>
                        <button className="btn btn-primary" disabled={!selectedGroup || loading || !canManageIntercompany} onClick={runConsolidation}>
                            {loading ? t('common.loading') : t('intercompany.run_consolidation')}
                        </button>
                    </div>
                </div>
            </div>

            {/* Consolidation Result */}
            {result && (
                <div className="card" style={{ padding: 16, marginBottom: 16 }}>
                    <h3>{t('intercompany.elimination_results')}</h3>
                    <p><strong>{t('intercompany.total_eliminated')}:</strong> {result.total_eliminated}</p>
                    {result.elimination_lines && result.elimination_lines.length > 0 ? (
                        <DataTable
                            data={result.elimination_lines}
                            columns={[
                                { key: 'source_entity_name', label: t('intercompany.source_entity'), render: (value, line) => value || line.source_entity_id },
                                { key: 'target_entity_name', label: t('intercompany.target_entity'), render: (value, line) => value || line.target_entity_id },
                                { key: 'amount', label: t('intercompany.source_amount'), render: (value, line) => <>{formatNumber(value)} {line.currency}</> },
                                { key: 'elimination_je_id', label: t('intercompany.elimination_journal'), render: (value) => value || '-' },
                            ]}
                            paginate={false}
                        />
                    ) : (
                        <p>{t('intercompany.no_pending')}</p>
                    )}
                </div>
            )}

            {/* Balances */}
            <div className="card" style={{ padding: 16 }}>
                <h3>{t('intercompany.balances_title')}</h3>
                {balances.length === 0 ? (
                    <p>{t('intercompany.no_pending')}</p>
                ) : (
                    <DataTable
                        data={balances}
                        columns={[
                            { key: 'source_entity_name', label: t('intercompany.source_entity'), render: (value, row) => value || row.source_entity_id },
                            { key: 'target_entity_name', label: t('intercompany.target_entity'), render: (value, row) => value || row.target_entity_id },
                            { key: 'pending_count', label: t('intercompany.pending_count') },
                            { key: 'net_amount', label: t('intercompany.net_amount'), render: (value) => formatNumber(value) },
                        ]}
                        paginate={false}
                    />
                )}
            </div>
        </div>
    )
}

export default ConsolidationView
