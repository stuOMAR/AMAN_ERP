import { useState, useEffect, useRef, Fragment } from 'react'
import { useTranslation } from 'react-i18next'
import { servicesAPI } from '../../utils/api'
import '../../components/ModuleStyles.css'
import { formatShortDate } from '../../utils/dateUtils'
import BackButton from '../../components/common/BackButton'
import { useToast } from '../../context/ToastContext'
import { hasPermission } from '../../utils/auth'
import { downloadBlob } from '../../utils/fileDownload'
import { Download } from 'lucide-react'
import QuotaMeter from '../dms/QuotaMeter'

const accessBadgeStyles = {
    public:     { background: '#22c55e', color: '#fff' },
    company:    { background: '#3b82f6', color: '#fff' },
    department: { background: '#eab308', color: '#fff' },
    private:    { background: '#ef4444', color: '#fff' }
}

function DocumentManagement() {
    const { t } = useTranslation()
  const { showToast } = useToast()
    const fileInputRef = useRef(null)
    const versionFileRef = useRef(null)

    const categoryOptions = [
        { value: 'general',  label: t('documents.cat_general') },
        { value: 'contract', label: t('documents.cat_contract') },
        { value: 'invoice',  label: t('documents.cat_invoice') },
        { value: 'report',   label: t('documents.cat_report') },
        { value: 'policy',   label: t('documents.cat_policy') },
        { value: 'manual',   label: t('documents.cat_manual') }
    ]

    const accessOptions = [
        { value: 'public',     label: t('documents.access_public') },
        { value: 'company',    label: t('documents.access_company') },
        { value: 'department', label: t('documents.access_department') },
        { value: 'private',    label: t('documents.access_private') }
    ]

    const [documents, setDocuments] = useState([])
    const [loading, setLoading] = useState(true)
    const [showUploadModal, setShowUploadModal] = useState(false)
    const [showEditModal, setShowEditModal] = useState(false)
    const [showVersionModal, setShowVersionModal] = useState(false)
    const [filterCategory, setFilterCategory] = useState('')
    const [searchQuery, setSearchQuery] = useState('')

    // Detail view
    const [expandedId, setExpandedId] = useState(null)
    const [detail, setDetail] = useState(null)
    const [detailLoading, setDetailLoading] = useState(false)

    const [uploadForm, setUploadForm] = useState({
        title: '', description: '', category: 'general', tags: '', access_level: 'company', file: null
    })
    const [editForm, setEditForm] = useState({
        id: null, title: '', description: '', category: 'general', tags: '', access_level: 'company'
    })
    const [versionForm, setVersionForm] = useState({ doc_id: null, change_notes: '', file: null })

    useEffect(() => {
        fetchDocuments()
    }, [filterCategory])

    const fetchDocuments = async () => {
        try {
            setLoading(true)
            const params = {}
            if (filterCategory) params.category = filterCategory
            if (searchQuery) params.search = searchQuery
            const res = await servicesAPI.listDocuments(params)
            setDocuments(Array.isArray(res.data) ? res.data : (res.data?.items ?? []))
        } catch {
            showToast(t('dms.errors.load_failed'), 'error')
        } finally {
            setLoading(false)
        }
    }

    const handleSearch = (e) => {
        e.preventDefault()
        fetchDocuments()
    }

    const openUpload = () => {
        setUploadForm({ title: '', description: '', category: 'general', tags: '', access_level: 'company', file: null })
        setShowUploadModal(true)
    }

    const handleUpload = async (e) => {
        e.preventDefault()
        if (!uploadForm.file) return showToast(t('documents.select_file'), 'warning')
        try {
            const fd = new FormData()
            fd.append('file', uploadForm.file)
            fd.append('title', uploadForm.title)
            fd.append('description', uploadForm.description)
            fd.append('category', uploadForm.category)
            fd.append('tags', uploadForm.tags)
            fd.append('access_level', uploadForm.access_level)
            await servicesAPI.uploadDocument(fd)
            setShowUploadModal(false)
            fetchDocuments()
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        }
    }

    const openEdit = (doc) => {
        setEditForm({
            id: doc.id,
            title: doc.title || '',
            description: doc.description || '',
            category: doc.category || 'general',
            tags: doc.tags || '',
            access_level: doc.access_level || 'company'
        })
        setShowEditModal(true)
    }

    const handleEdit = async (e) => {
        e.preventDefault()
        try {
            const { id, ...data } = editForm
            await servicesAPI.updateDocument(id, data)
            setShowEditModal(false)
            fetchDocuments()
            if (expandedId === id) loadDetail(id)
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        }
    }

    const openVersionUpload = (docId) => {
        setVersionForm({ doc_id: docId, change_notes: '', file: null })
        setShowVersionModal(true)
    }

    const handleVersionUpload = async (e) => {
        e.preventDefault()
        if (!versionForm.file) return showToast(t('documents.select_file'), 'warning')
        try {
            const fd = new FormData()
            fd.append('file', versionForm.file)
            fd.append('change_notes', versionForm.change_notes)
            await servicesAPI.uploadVersion(versionForm.doc_id, fd)
            setShowVersionModal(false)
            fetchDocuments()
            if (expandedId === versionForm.doc_id) {
                const res = await servicesAPI.getDocument(versionForm.doc_id)
                setDetail(res.data)
            }
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        }
    }

    const handleDelete = async (id) => {
        if (!confirm(t('common.confirm_delete'))) return
        try {
            await servicesAPI.deleteDocument(id)
            if (expandedId === id) setExpandedId(null)
            fetchDocuments()
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.error'), 'error')
        }
    }

    const handleDownload = async (doc) => {
        if (doc.state === 'quarantined') {
            showToast(t('dms.status.quarantined'), 'error')
            return
        }
        try {
            const res = await servicesAPI.downloadDocument(doc.id)
            downloadBlob(res, doc.file_name || doc.title || `document-${doc.id}`)
        } catch (err) {
            showToast(err.response?.data?.detail || t('common.download_error', 'Download failed'), 'error')
        }
    }

    const loadDetail = async (id) => {
        if (expandedId === id) {
            setExpandedId(null)
            return
        }
        setExpandedId(id)
        setDetailLoading(true)
        try {
            const res = await servicesAPI.getDocument(id)
            setDetail(res.data)
        } catch {
            setDetail(null)
        } finally {
            setDetailLoading(false)
        }
    }

    const formatFileSize = (bytes) => {
        if (!bytes) return '0 B'
        const sizes = ['B', 'KB', 'MB', 'GB']
        const i = Math.floor(Math.log(bytes) / Math.log(1024))
        return (bytes / Math.pow(1024, i)).toFixed(1) + ' ' + sizes[i]
    }

    const getLabelByValue = (options, value) => {
        const opt = options.find(o => o.value === value)
        return opt ? opt.label : value
    }

    const getDmsStatusBadge = (state) => {
        const normalized = state || 'clean'
        const styles = {
            clean: { background: '#16a34a', color: '#fff' },
            pending_scan: { background: '#f59e0b', color: '#111827' },
            quarantined: { background: '#dc2626', color: '#fff' }
        }
        return (
            <span className="badge" style={styles[normalized] || {}}>
                {t(`dms.status.${normalized}`, normalized)}
            </span>
        )
    }

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">{t('documents.title')}</h1>
                    <p className="workspace-subtitle">{t('documents.desc')}</p>
                </div>
                <div className="header-actions">
                    <button className="btn btn-primary" onClick={openUpload}>+ {t('documents.upload')}</button>
                </div>
            </div>

            {hasPermission('dms.audit_admin') && (
                <div className="card section-card" style={{ marginBottom: '16px' }}>
                    <div className="card-body">
                        <QuotaMeter />
                    </div>
                </div>
            )}

            {/* Search & Filter */}
            <div className="toolbar" style={{ display: 'flex', gap: '12px', marginBottom: '16px', flexWrap: 'wrap' }}>
                <form onSubmit={handleSearch} style={{ display: 'flex', gap: '8px', flex: 1, minWidth: '200px' }}>
                    <input
                        className="form-input"
                        placeholder={t('documents.search_placeholder')}
                        value={searchQuery}
                        onChange={e => setSearchQuery(e.target.value)}
                        style={{ flex: 1 }}
                    />
                    <button type="submit" className="btn btn-primary">{t('common.search')}</button>
                </form>
                <select className="form-input" style={{ width: 'auto' }} value={filterCategory} onChange={e => setFilterCategory(e.target.value)}>
                    <option value="">{t('documents.all_categories')}</option>
                    {categoryOptions.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                </select>
            </div>

            {/* Table */}
            <div className="data-table-container">
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>{t('documents.col_number')}</th>
                            <th>{t('documents.col_title')}</th>
                            <th>{t('documents.col_category')}</th>
                            <th>{t('documents.col_filename')}</th>
                            <th>{t('documents.col_size')}</th>
                            <th>{t('documents.col_version')}</th>
                            <th>{t('documents.col_status', 'Status')}</th>
                            <th>{t('documents.col_access')}</th>
                            <th>{t('documents.col_uploaded_by')}</th>
                            <th>{t('documents.col_date')}</th>
                            <th>{t('common.actions')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {loading ? (
                            <tr><td colSpan="11" style={{ textAlign: 'center', padding: '40px' }}>{t('common.loading')}</td></tr>
                        ) : documents.length === 0 ? (
                            <tr><td colSpan="11" style={{ textAlign: 'center', padding: '40px' }}>{t('common.no_data')}</td></tr>
                        ) : documents.map(doc => (
                            <Fragment key={doc.id}>
                                <tr style={{ cursor: 'pointer' }} onClick={() => loadDetail(doc.id)}>
                                    <td><strong>{doc.doc_number}</strong></td>
                                    <td>{doc.title}</td>
                                    <td>{getLabelByValue(categoryOptions, doc.category)}</td>
                                    <td style={{ fontSize: '13px' }}>{doc.file_name}</td>
                                    <td>{formatFileSize(doc.file_size)}</td>
                                    <td style={{ textAlign: 'center' }}>v{doc.current_version}</td>
                                    <td>{getDmsStatusBadge(doc.state)}</td>
                                    <td><span className="badge" style={accessBadgeStyles[doc.access_level] || {}}>{getLabelByValue(accessOptions, doc.access_level)}</span></td>
                                    <td>{doc.created_by_name || '—'}</td>
                                    <td>{formatShortDate(doc.created_at)}</td>
                                    <td onClick={e => e.stopPropagation()}>
                                        <div style={{ display: 'flex', gap: '4px' }}>
                                            <button
                                                className="btn btn-sm btn-light btn-icon"
                                                onClick={() => handleDownload(doc)}
                                                title={t('common.download', 'Download')}
                                                disabled={doc.state === 'quarantined'}
                                            >
                                                <Download size={14} />
                                            </button>
                                            <button className="btn btn-sm" onClick={() => openEdit(doc)} title={t('common.edit')}>✏️</button>
                                            <button className="btn btn-sm btn-primary" onClick={() => openVersionUpload(doc.id)} title={t('documents.new_version')}>📄</button>
                                            <button className="btn btn-sm btn-danger" onClick={() => handleDelete(doc.id)} title={t('common.delete')}>🗑️</button>
                                        </div>
                                    </td>
                                </tr>

                                {/* Expanded Detail — Versions */}
                                {expandedId === doc.id && (
                                    <tr key={`detail-${doc.id}`}>
                                        <td colSpan="11" style={{ background: 'var(--bg-secondary)', padding: '20px' }}>
                                            {detailLoading ? (
                                                <div style={{ textAlign: 'center' }}>{t('common.loading')}</div>
                                            ) : detail ? (
                                                <div>
                                                    {detail.description && <p><strong>{t('documents.description')}:</strong> {detail.description}</p>}
                                                    {detail.tags && <p><strong>{t('documents.tags')}:</strong> {detail.tags}</p>}

                                                    <h4 style={{ marginTop: '16px', marginBottom: '8px' }}>{t('documents.versions')}</h4>
                                                    {detail.versions && detail.versions.length > 0 ? (
                                                        <table className="data-table" style={{ fontSize: '13px' }}>
                                                            <thead>
                                                                <tr>
                                                                    <th>{t('documents.version_num')}</th>
                                                                    <th>{t('documents.col_filename')}</th>
                                                                    <th>{t('documents.col_size')}</th>
                                                                    <th>{t('documents.change_notes')}</th>
                                                                    <th>{t('documents.uploaded_by')}</th>
                                                                    <th>{t('documents.col_date')}</th>
                                                                </tr>
                                                            </thead>
                                                            <tbody>
                                                                {detail.versions.map(v => (
                                                                    <tr key={v.id}>
                                                                        <td>v{v.version_number}</td>
                                                                        <td>{v.file_name}</td>
                                                                        <td>{formatFileSize(v.file_size)}</td>
                                                                        <td>{v.change_notes || '—'}</td>
                                                                        <td>{v.uploaded_by_name || '—'}</td>
                                                                        <td>{formatShortDate(v.uploaded_at)}</td>
                                                                    </tr>
                                                                ))}
                                                            </tbody>
                                                        </table>
                                                    ) : (
                                                        <p style={{ color: 'var(--text-secondary)', fontSize: '13px' }}>{t('documents.no_versions')}</p>
                                                    )}
                                                </div>
                                            ) : null}
                                        </td>
                                    </tr>
                                )}
                            </Fragment>
                        ))}
                    </tbody>
                </table>
            </div>

            {/* Upload Modal */}
            {showUploadModal && (
                <div className="modal-overlay" onClick={() => setShowUploadModal(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: '550px' }}>
                        <div className="modal-header">
                            <h3>{t('documents.upload')}</h3>
                            <button className="modal-close" onClick={() => setShowUploadModal(false)}>×</button>
                        </div>
                        <form onSubmit={handleUpload}>
                            <div className="modal-body">
                                <div className="form-group mb-3">
                                    <label className="form-label">{t('documents.file')} *</label>
                                    <input
                                        ref={fileInputRef}
                                        type="file"
                                        className="form-input"
                                        onChange={e => setUploadForm({...uploadForm, file: e.target.files[0]})}
                                        required
                                    />
                                </div>
                                <div className="form-group mb-3">
                                    <label className="form-label">{t('documents.col_title')}</label>
                                    <input className="form-input" value={uploadForm.title} onChange={e => setUploadForm({...uploadForm, title: e.target.value})} placeholder={t('documents.title_placeholder')} />
                                </div>
                                <div className="form-group mb-3">
                                    <label className="form-label">{t('documents.description')}</label>
                                    <textarea className="form-input" value={uploadForm.description} onChange={e => setUploadForm({...uploadForm, description: e.target.value})} rows={2} />
                                </div>
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                                    <div className="form-group mb-3">
                                        <label className="form-label">{t('documents.col_category')}</label>
                                        <select className="form-input" value={uploadForm.category} onChange={e => setUploadForm({...uploadForm, category: e.target.value})}>
                                            {categoryOptions.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                                        </select>
                                    </div>
                                    <div className="form-group mb-3">
                                        <label className="form-label">{t('documents.col_access')}</label>
                                        <select className="form-input" value={uploadForm.access_level} onChange={e => setUploadForm({...uploadForm, access_level: e.target.value})}>
                                            {accessOptions.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                                        </select>
                                    </div>
                                </div>
                                <div className="form-group mb-3">
                                    <label className="form-label">{t('documents.tags')}</label>
                                    <input className="form-input" value={uploadForm.tags} onChange={e => setUploadForm({...uploadForm, tags: e.target.value})} placeholder={t('documents.tags_placeholder')} />
                                </div>
                            </div>
                            <div className="modal-footer">
                                <button type="button" className="btn btn-secondary" onClick={() => setShowUploadModal(false)}>{t('common.cancel')}</button>
                                <button type="submit" className="btn btn-primary">{t('documents.upload')}</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {/* Edit Metadata Modal */}
            {showEditModal && (
                <div className="modal-overlay" onClick={() => setShowEditModal(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: '500px' }}>
                        <div className="modal-header">
                            <h3>{t('documents.edit')}</h3>
                            <button className="modal-close" onClick={() => setShowEditModal(false)}>×</button>
                        </div>
                        <form onSubmit={handleEdit}>
                            <div className="modal-body">
                                <div className="form-group mb-3">
                                    <label className="form-label">{t('documents.col_title')}</label>
                                    <input className="form-input" value={editForm.title} onChange={e => setEditForm({...editForm, title: e.target.value})} required />
                                </div>
                                <div className="form-group mb-3">
                                    <label className="form-label">{t('documents.description')}</label>
                                    <textarea className="form-input" value={editForm.description} onChange={e => setEditForm({...editForm, description: e.target.value})} rows={2} />
                                </div>
                                <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '12px' }}>
                                    <div className="form-group mb-3">
                                        <label className="form-label">{t('documents.col_category')}</label>
                                        <select className="form-input" value={editForm.category} onChange={e => setEditForm({...editForm, category: e.target.value})}>
                                            {categoryOptions.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                                        </select>
                                    </div>
                                    <div className="form-group mb-3">
                                        <label className="form-label">{t('documents.col_access')}</label>
                                        <select className="form-input" value={editForm.access_level} onChange={e => setEditForm({...editForm, access_level: e.target.value})}>
                                            {accessOptions.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
                                        </select>
                                    </div>
                                </div>
                                <div className="form-group mb-3">
                                    <label className="form-label">{t('documents.tags')}</label>
                                    <input className="form-input" value={editForm.tags} onChange={e => setEditForm({...editForm, tags: e.target.value})} />
                                </div>
                            </div>
                            <div className="modal-footer">
                                <button type="button" className="btn btn-secondary" onClick={() => setShowEditModal(false)}>{t('common.cancel')}</button>
                                <button type="submit" className="btn btn-primary">{t('common.save')}</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}

            {/* New Version Modal */}
            {showVersionModal && (
                <div className="modal-overlay" onClick={() => setShowVersionModal(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: '450px' }}>
                        <div className="modal-header">
                            <h3>{t('documents.new_version')}</h3>
                            <button className="modal-close" onClick={() => setShowVersionModal(false)}>×</button>
                        </div>
                        <form onSubmit={handleVersionUpload}>
                            <div className="modal-body">
                                <div className="form-group mb-3">
                                    <label className="form-label">{t('documents.file')} *</label>
                                    <input
                                        ref={versionFileRef}
                                        type="file"
                                        className="form-input"
                                        onChange={e => setVersionForm({...versionForm, file: e.target.files[0]})}
                                        required
                                    />
                                </div>
                                <div className="form-group mb-3">
                                    <label className="form-label">{t('documents.change_notes')}</label>
                                    <textarea className="form-input" value={versionForm.change_notes} onChange={e => setVersionForm({...versionForm, change_notes: e.target.value})} rows={3} />
                                </div>
                            </div>
                            <div className="modal-footer">
                                <button type="button" className="btn btn-secondary" onClick={() => setShowVersionModal(false)}>{t('common.cancel')}</button>
                                <button type="submit" className="btn btn-primary">{t('documents.upload')}</button>
                            </div>
                        </form>
                    </div>
                </div>
            )}
        </div>
    )
}

export default DocumentManagement
