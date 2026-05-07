import { useState, useEffect, useCallback } from 'react'
import { useNavigate } from 'react-router-dom'
import { useTranslation } from 'react-i18next'
import { accountingAPI } from '../../utils/api'
import { useToast } from '../../context/ToastContext'
import { useBranch } from '../../context/BranchContext'
import { formatNumber } from '../../utils/format'
import { hasPermission, getCurrency } from '../../utils/auth'
import { formatDate } from '../../utils/dateUtils'
import DataTable from '../../components/common/DataTable'
import SearchFilter from '../../components/common/SearchFilter'
import BackButton from '../../components/common/BackButton'

function JournalEntryList() {
    const { t, i18n } = useTranslation()
    const navigate = useNavigate()
    const { showToast } = useToast()
    const { currentBranch } = useBranch()
    const isRTL = i18n.language === 'ar'
    const canCreate = hasPermission('accounting.create_journal_entry')
    const canPost = hasPermission('accounting.post_journal_entry')
    const canVoid = hasPermission('accounting.void_journal_entry')
    const canManage = hasPermission('accounting.manage')
    const currency = getCurrency()

    const [entries, setEntries] = useState([])
    const [loading, setLoading] = useState(true)
    const [total, setTotal] = useState(0)
    const [page, setPage] = useState(1)
    const [statusFilter, setStatusFilter] = useState('')
    const [search, setSearch] = useState('')
    const [selectedEntry, setSelectedEntry] = useState(null)
    const [detailLoading, setDetailLoading] = useState(false)
    const [showReverseModal, setShowReverseModal] = useState(false)
    const [reverseDate, setReverseDate] = useState(new Date().toISOString().slice(0, 10))
    const [reverseReason, setReverseReason] = useState('')
    const [reverseLoading, setReverseLoading] = useState(false)
    const limit = 25

    const fetchEntries = useCallback(async () => {
        try {
            setLoading(true)
            const params = { page, limit }
            if (statusFilter) params.status_filter = statusFilter
            if (search) params.search = search
            if (currentBranch?.id) params.branch_id = currentBranch.id
            const res = await accountingAPI.listJournalEntries(params)
            setEntries(res.data.items || [])
            setTotal(res.data.total || 0)
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        } finally {
            setLoading(false)
        }
    }, [page, statusFilter, search, showToast, currentBranch])

    useEffect(() => { fetchEntries() }, [fetchEntries])

    const handlePost = async (entryId) => {
        if (!confirm(t('accounting.journal_entries.post_this_journal_entry'))) return
        try {
            const res = await accountingAPI.postJournalEntry(entryId)
            showToast(res.data.message, 'success')
            fetchEntries()
            setSelectedEntry(null)
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        }
    }

    const handleVoid = async (entryId) => {
        if (!confirm(t('accounting.journal_entries.void_this_entry_a_reversal_entry_will_be_created'))) return
        try {
            const res = await accountingAPI.voidJournalEntry(entryId)
            showToast(res.data.message, 'success')
            fetchEntries()
            setSelectedEntry(null)
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        }
    }

    const handleReverse = async () => {
        if (!selectedEntry) return
        setReverseLoading(true)
        try {
            const res = await accountingAPI.reverseJournalEntry(selectedEntry.id, {
                reversal_date: reverseDate,
                reason: reverseReason || undefined,
            })
            showToast(res.data.message, 'success')
            setShowReverseModal(false)
            setSelectedEntry(null)
            setReverseReason('')
            fetchEntries()
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        } finally {
            setReverseLoading(false)
        }
    }

    const handleViewDetail = async (entryId) => {
        try {
            setDetailLoading(true)
            const res = await accountingAPI.getJournalEntry(entryId)
            setSelectedEntry(res.data)
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        } finally {
            setDetailLoading(false)
        }
    }

    const statusBadge = (status) => {
        const map = {
            draft: { class: 'badge-warning', label: t('common.status_draft') || t('accounting.journal_entries.draft') },
            posted: { class: 'badge-success', label: t('common.status_posted') || t('accounting.journal_entries.posted') },
            voided: { class: 'badge-secondary', label: t('common.status_voided') || t('accounting.journal_entries.voided') },
        }
        const s = map[status] || { class: '', label: status }
        return <span className={`badge ${s.class}`}>{s.label}</span>
    }

    const totalPages = Math.ceil(total / limit)

    const columns = [
        {
            key: 'entry_number',
            label: t('accounting.journal_entries.table.id'),
            render: (val) => <strong>{val}</strong>,
        },
        {
            key: 'entry_date',
            label: t('accounting.journal_entries.table.date'),
            render: (val) => formatDate(val),
        },
        {
            key: 'description',
            label: t('accounting.journal_entries.table.description'),
            style: { maxWidth: '250px', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' },
        },
        {
            key: 'reference',
            label: t('common.reference'),
            render: (val) => val || '\u2014',
        },
        {
            key: 'total_debit',
            label: t('accounting.journal_entries.table.debit'),
            render: (val) => <span>{formatNumber(val)} <small>{currency}</small></span>,
        },
        {
            key: 'total_credit',
            label: t('accounting.journal_entries.table.credit'),
            render: (val) => <span>{formatNumber(val)} <small>{currency}</small></span>,
        },
        {
            key: 'status',
            label: t('accounting.journal_entries.table.status'),
            render: (val) => statusBadge(val),
        },
        ...((canPost || canVoid) ? [{
            key: '_actions',
            label: t('accounting.journal_entries.table.actions'),
            render: (_, row) => (
                <div onClick={ev => ev.stopPropagation()} style={{ display: 'flex', gap: '0.25rem' }}>
                    {row.status === 'draft' && canPost && (
                        <button className="btn btn-sm btn-success" onClick={() => handlePost(row.id)}>
                            {t('accounting.journal_entries.post')}
                        </button>
                    )}
                    {row.status === 'posted' && canVoid && (
                        <button className="btn btn-sm btn-danger" onClick={() => handleVoid(row.id)}>
                            {t('accounting.journal_entries.void')}
                        </button>
                    )}
                </div>
            ),
        }] : []),
    ]

    return (
        <div className="workspace fade-in">
            <div className="workspace-header" style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                <BackButton />
                <div>
                    <h1 className="workspace-title">
                        {t('accounting.journal_entries.title')}
                    </h1>
                    <p className="workspace-subtitle">
                        {total} {t('accounting.journal_entries.title')}
                    </p>
                </div>
                {canCreate && (
                    <button className="btn btn-primary" onClick={() => navigate('/accounting/journal-entries/new')}>
                        + {t('accounting.journal_entries.new_entry')}
                    </button>
                )}
            </div>

            <SearchFilter
                value={search}
                onChange={(val) => { setSearch(val); setPage(1) }}
                placeholder={t('accounting.journal_entries.search_placeholder', '\u0628\u062D\u062B \u0628\u0627\u0644\u0645\u0631\u062C\u0639 \u0623\u0648 \u0627\u0644\u0648\u0635\u0641...')}
                filters={[{
                    key: 'status',
                    label: t('common.all_status'),
                    options: [
                        { value: 'draft', label: t('common.status_draft') || t('accounting.journal_entries.draft') },
                        { value: 'posted', label: t('common.status_posted') || t('accounting.journal_entries.posted') },
                        { value: 'voided', label: t('common.status_voided') || t('accounting.journal_entries.voided') },
                    ],
                }]}
                filterValues={{ status: statusFilter }}
                onFilterChange={(key, val) => { setStatusFilter(val); setPage(1) }}
            />

            <DataTable
                columns={columns}
                data={entries}
                loading={loading}
                onRowClick={(row) => handleViewDetail(row.id)}
                paginate={false}
                emptyTitle={t('accounting.journal_entries.no_entries_found')}
                emptyAction={canCreate ? { label: t('accounting.journal_entries.new_entry'), onClick: () => navigate('/accounting/journal-entries/new') } : undefined}
            />

            {/* Server-side Pagination */}
            {totalPages > 1 && (
                <div style={{ display: 'flex', justifyContent: 'center', padding: '1rem', gap: '0.5rem' }}>
                    <button className="btn btn-sm btn-outline" disabled={page <= 1} onClick={() => setPage(p => p - 1)}>
                        {t('accounting.u2190')}
                    </button>
                    <span style={{ padding: '0.25rem 1rem', lineHeight: '32px' }}>
                        {page} / {totalPages}
                    </span>
                    <button className="btn btn-sm btn-outline" disabled={page >= totalPages} onClick={() => setPage(p => p + 1)}>
                        {t('accounting.u2192')}
                    </button>
                </div>
            )}

            {/* Detail Modal */}
            {selectedEntry && (
                <div className="modal-overlay" onClick={() => setSelectedEntry(null)}>
                    <div className="modal-content" onClick={ev => ev.stopPropagation()} style={{ maxWidth: '800px', maxHeight: '80vh', overflow: 'auto' }}>
                        <div className="modal-header">
                            <h3>{selectedEntry.entry_number} — {statusBadge(selectedEntry.status)}</h3>
                            <button className="modal-close" onClick={() => setSelectedEntry(null)}>{'\u2715'}</button>
                        </div>
                        <div className="modal-body">
                            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '0.75rem', marginBottom: '1rem' }}>
                                <div><strong>{t('common.date')}:</strong> {formatDate(selectedEntry.entry_date)}</div>
                                <div><strong>{t('common.reference')}:</strong> {selectedEntry.reference || '\u2014'}</div>
                                <div style={{ gridColumn: '1 / -1' }}><strong>{t('common.description')}:</strong> {selectedEntry.description}</div>
                                <div><strong>{t('common.currency') || t('accounting.journal_entries.currency')}:</strong> {selectedEntry.currency}</div>
                                <div><strong>{t('common.created_by')}:</strong> {selectedEntry.created_by_name}</div>
                            </div>

                            <table className="data-table" style={{ fontSize: '0.85rem' }}>
                                <thead>
                                    <tr>
                                        <th>{t('common.account') || t('accounting.journal_entries.account')}</th>
                                        <th>{t('common.description')}</th>
                                        <th>{t('accounting.journal_entries.table.debit')}</th>
                                        <th>{t('accounting.journal_entries.table.credit')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {selectedEntry.lines?.map((l, i) => (
                                        <tr key={i}>
                                            <td>{l.account_number} - {isRTL ? l.account_name : (l.account_name_en || l.account_name)}</td>
                                            <td>{l.description || '\u2014'}</td>
                                            <td>{l.debit > 0 ? formatNumber(l.debit) : ''}</td>
                                            <td>{l.credit > 0 ? formatNumber(l.credit) : ''}</td>
                                        </tr>
                                    ))}
                                    <tr style={{ fontWeight: 'bold', borderTop: '2px solid var(--border)' }}>
                                        <td colSpan="2">{t('common.total')}</td>
                                        <td>{formatNumber(selectedEntry.lines?.reduce((s, l) => s + parseFloat(l.debit || 0), 0))}</td>
                                        <td>{formatNumber(selectedEntry.lines?.reduce((s, l) => s + parseFloat(l.credit || 0), 0))}</td>
                                    </tr>
                                </tbody>
                            </table>
                        </div>
                        <div className="modal-footer">
                            {selectedEntry.status === 'draft' && canPost && (
                                <button className="btn btn-success" onClick={() => handlePost(selectedEntry.id)}>
                                    {'\u2713'} {t('accounting.journal_entries.post_entry')}
                                </button>
                            )}
                            {selectedEntry.status === 'posted' && canManage && selectedEntry.source !== 'reversal' && (
                                <button className="btn btn-warning" onClick={() => {
                                    setReverseDate(new Date().toISOString().slice(0, 10))
                                    setReverseReason('')
                                    setShowReverseModal(true)
                                }}>
                                    ↩ {t('accounting.journal_entries.reverse_entry', 'عكس القيد')}
                                </button>
                            )}
                            {selectedEntry.status === 'posted' && canVoid && selectedEntry.source !== 'reversal' && (
                                <button className="btn btn-danger" onClick={() => handleVoid(selectedEntry.id)}>
                                    {'\u2715'} {t('accounting.journal_entries.void_entry')}
                                </button>
                            )}
                            <button className="btn btn-secondary" onClick={() => setSelectedEntry(null)}>
                                {t('accounting.journal_entries.close')}
                            </button>
                        </div>
                    </div>
                </div>
            )}
            {/* Reverse Confirmation Modal */}
            {showReverseModal && selectedEntry && (
                <div className="modal-overlay" onClick={() => setShowReverseModal(false)}>
                    <div className="modal-content" onClick={ev => ev.stopPropagation()} style={{ maxWidth: '480px' }}>
                        <div className="modal-header">
                            <h3>↩ {t('accounting.journal_entries.reverse_entry', 'عكس القيد')}</h3>
                            <button className="modal-close" onClick={() => setShowReverseModal(false)}>{'\u2715'}</button>
                        </div>
                        <div className="modal-body" style={{ display: 'flex', flexDirection: 'column', gap: '1rem' }}>
                            <p style={{ margin: 0 }}>
                                {t('accounting.journal_entries.reverse_confirm_msg', 'سيتم إنشاء قيد عكسي لـ')} <strong>{selectedEntry.entry_number}</strong>.
                                {' '}{t('accounting.journal_entries.reverse_original_kept', 'القيد الأصلي يبقى مرحَّلاً.')}
                            </p>
                            <div>
                                <label style={{ display: 'block', marginBottom: '0.25rem', fontWeight: 500 }}>
                                    {t('accounting.journal_entries.reversal_date', 'تاريخ القيد العكسي')}
                                </label>
                                <input
                                    type="date"
                                    className="form-control"
                                    value={reverseDate}
                                    onChange={e => setReverseDate(e.target.value)}
                                />
                            </div>
                            <div>
                                <label style={{ display: 'block', marginBottom: '0.25rem', fontWeight: 500 }}>
                                    {t('common.reason', 'السبب')} ({t('common.optional', 'اختياري')})
                                </label>
                                <input
                                    type="text"
                                    className="form-control"
                                    value={reverseReason}
                                    onChange={e => setReverseReason(e.target.value)}
                                    placeholder={t('accounting.journal_entries.reverse_reason_placeholder', 'مثال: تصحيح خطأ، عكس مستحقات...')}
                                />
                            </div>
                        </div>
                        <div className="modal-footer">
                            <button
                                className="btn btn-warning"
                                onClick={handleReverse}
                                disabled={reverseLoading || !reverseDate}
                            >
                                {reverseLoading ? t('common.loading', '...') : `↩ ${t('accounting.journal_entries.confirm_reverse', 'تأكيد العكس')}`}
                            </button>
                            <button className="btn btn-secondary" onClick={() => setShowReverseModal(false)}>
                                {t('common.cancel', 'إلغاء')}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}

export default JournalEntryList
