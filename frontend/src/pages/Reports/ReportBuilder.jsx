import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { 
    Save, Play, Plus, Trash2, Filter, 
    Columns, Database, FileText, Download
} from 'lucide-react';
import { customReportsAPI } from '../../utils/api';
import { toastEmitter } from '../../utils/toastEmitter';
import { hasPermission } from '../../utils/auth';
import '../../components/ModuleStyles.css';

import { formatShortDate } from '../../utils/dateUtils';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'

export default function ReportBuilder() {
    const { t } = useTranslation();
    const canDeleteReports = hasPermission('reports.delete');

    const [loading, setLoading] = useState(false);
    const [previewData, setPreviewData] = useState(null);
    const [savedReports, setSavedReports] = useState([]);
    const [showSavedList, setShowSavedList] = useState(false);

    // Available Tables (Mock for now, or could be fetched)
    const availableTables = [
        { id: 'projects', label: t('reports.tables.projects'), columns: ['id', 'project_name', 'status', 'start_date', 'end_date', 'budget', 'manager_id'] },
        { id: 'tasks', label: t('reports.tables.tasks'), columns: ['id', 'project_id', 'task_name', 'status', 'start_date', 'end_date', 'planned_hours', 'actual_hours'] },
        { id: 'sales_invoices', label: t('reports.tables.sales'), columns: ['id', 'invoice_number', 'customer_id', 'invoice_date', 'total_amount', 'status'] },
        { id: 'expenses', label: t('reports.tables.expenses'), columns: ['id', 'project_id', 'expense_date', 'amount', 'category', 'description'] },
        { id: 'customers', label: t('reports.tables.customers'), columns: ['id', 'name', 'email', 'phone', 'city'] },
    ];

    const [config, setConfig] = useState({
        name: '',
        description: '',
        table_name: 'projects',
        columns: [],
        filters: {},
        sort_by: 'id',
        sort_order: 'desc'
    });

    useEffect(() => {
        fetchSavedReports();
    }, []);

    const fetchSavedReports = async () => {
        try {
            const res = await customReportsAPI.list();
            setSavedReports(res.data || []);
        } catch { }
    };

    const handleColumnToggle = (col) => {
        setConfig(prev => {
            const exists = prev.columns.includes(col);
            if (exists) {
                return { ...prev, columns: prev.columns.filter(c => c !== col) };
            } else {
                return { ...prev, columns: [...prev.columns, col] };
            }
        });
    };

    const handleAddFilter = () => {
        // Simplified filter UI: just adding a placeholder for now
        // In real app, we need field, operator, value
        const field = availableTables.find(tbl => tbl.id === config.table_name)?.columns[0];
        setConfig(prev => ({
            ...prev,
            filters: { ...prev.filters, [field]: '' }
        }));
    };

    const handleFilterChange = (oldField, newField, value) => {
        const newFilters = { ...config.filters };
        if (oldField !== newField) {
            delete newFilters[oldField];
        }
        newFilters[newField] = value;
        setConfig(prev => ({ ...prev, filters: newFilters }));
    };

    const handleRemoveFilter = (field) => {
        const newFilters = { ...config.filters };
        delete newFilters[field];
        setConfig(prev => ({ ...prev, filters: newFilters }));
    };

    const handlePreview = async (overrideConfig) => {
        const effectiveConfig = overrideConfig || config;
        if (effectiveConfig.columns.length === 0) {
            toastEmitter.emit(t('reports.errors.no_columns'), 'error');
            return;
        }
        setLoading(true);
        try {
            const res = await customReportsAPI.preview(effectiveConfig);
            setPreviewData(res.data);
        } catch (err) {
            toastEmitter.emit(t('common.error'), 'error');
        } finally {
            setLoading(false);
        }
    };

    const handleExport = async () => {
        if (!previewData || previewData.length === 0) {
            toastEmitter.emit(t('reports.errors.no_data_to_export'), 'error');
            return;
        }
        try {
            const res = await customReportsAPI.export(config);
            const blob = new Blob([res.data], { type: res.headers['content-type'] || 'application/octet-stream' });
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${config.name || 'report'}.xlsx`;
            document.body.appendChild(a);
            a.click();
            a.remove();
            window.URL.revokeObjectURL(url);
        } catch (err) {
            toastEmitter.emit(t('common.exportError', 'Export failed'), 'error');
        }
    };

    const handleSave = async () => {
        if (!config.name) {
            toastEmitter.emit(t('reports.errors.name_required'), 'error');
            return;
        }
        try {
            await customReportsAPI.create(config);
            toastEmitter.emit(t('common.saved'), 'success');
            fetchSavedReports();
        } catch (err) {
            toastEmitter.emit(t('common.save_error'), 'error');
        }
    };

    const loadReport = async (id) => {
        try {
            const res = await customReportsAPI.get(id);
            const report = res.data;
            const loadedConfig = {
                ...report.query_config,
                name: report.report_name,
                description: report.description
            };
            setConfig(loadedConfig);
            setShowSavedList(false);
            handlePreview(loadedConfig);
        } catch { }
    };

    const deleteReport = async (id) => {
        if (!window.confirm(t('common.confirm_delete'))) return;
        try {
            await customReportsAPI.delete(id);
            fetchSavedReports();
        } catch { }
    };

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <div className="d-flex align-items-center justify-content-between w-100">
                    <div className="d-flex align-items-center gap-3">
                        <BackButton />
                        <div>
                            <h1 className="workspace-title mb-0">{t('reports.builder_title')}</h1>
                            <p className="workspace-subtitle mb-0">{t('reports.builder_subtitle')}</p>
                        </div>
                    </div>
                    <div className="d-flex gap-2">
                        <button className="btn btn-light" onClick={() => setShowSavedList(!showSavedList)}>
                            <FileText size={16} /> {t('reports.saved_reports')}
                        </button>
                        <button className="btn btn-primary" onClick={handleSave}>
                            <Save size={16} /> {t('common.save')}
                        </button>
                    </div>
                </div>
            </div>

            <div className="row g-4">
                {/* Configuration Panel */}
                <div className="col-lg-4">
                    <div className="card section-card mb-4">
                        <div className="card-body">
                            <h5 className="section-title mb-3"><Database size={16} /> {t('reports.data_source')}</h5>

                            <div className="mb-3">
                                <label className="form-label">{t('reports.report_name')}</label>
                                <input type="text" className="form-input" value={config.name}
                                    onChange={e => setConfig({ ...config, name: e.target.value })}
                                    placeholder={t('reports.report_name_placeholder')} />
                            </div>

                            <div className="mb-3">
                                <label className="form-label">{t('reports.select_table')}</label>
                                <select className="form-input" value={config.table_name}
                                    onChange={e => setConfig({ ...config, table_name: e.target.value, columns: [] })}>
                                    {availableTables.map(tbl => (
                                        <option key={tbl.id} value={tbl.id}>{tbl.label}</option>
                                    ))}
                                </select>
                            </div>
                        </div>
                    </div>

                    <div className="card section-card mb-4">
                        <div className="card-body">
                            <h5 className="section-title mb-3"><Columns size={16} /> {t('reports.columns')}</h5>
                            <div className="d-flex flex-wrap gap-2">
                                        {availableTables.find(tbl => tbl.id === config.table_name)?.columns.map(col => (
                                    <button
                                        key={col}
                                        className={`btn btn-sm ${config.columns.includes(col) ? 'btn-primary' : 'btn-light'}`}
                                        onClick={() => handleColumnToggle(col)}
                                    >
                                        {col}
                                    </button>
                                ))}
                            </div>
                        </div>
                    </div>

                    <div className="card section-card">
                        <div className="card-body">
                            <h5 className="section-title mb-3">
                                <div className="d-flex justify-content-between align-items-center w-100">
                                    <span><Filter size={16} /> {t('reports.filters')}</span>
                                    <button className="btn btn-sm btn-light btn-icon" onClick={handleAddFilter}><Plus size={14} /></button>
                                </div>
                            </h5>

                            {Object.entries(config.filters).map(([field, value], idx) => (
                                <div key={idx} className="d-flex gap-2 mb-2 align-items-center">
                                    <select className="form-input form-select-sm" value={field}
                                        onChange={(e) => handleFilterChange(field, e.target.value, value)}>
                                {availableTables.find(tbl => tbl.id === config.table_name)?.columns.map(col => (
                                            <option key={col} value={col}>{col}</option>
                                        ))}
                                    </select>
                                    <span>=</span>
                                    <input type="text" className="form-input form-input-sm" value={value}
                                        onChange={(e) => handleFilterChange(field, field, e.target.value)} />
                                    <button className="btn btn-icon btn-sm text-danger" onClick={() => handleRemoveFilter(field)}>
                                        <Trash2 size={14} />
                                    </button>
                                </div>
                            ))}
                            {Object.keys(config.filters).length === 0 && (
                                <p className="text-muted small text-center">{t('reports.no_filters')}</p>
                            )}

                            <button className="btn btn-success w-100 mt-3" onClick={handlePreview} disabled={loading}>
                                <Play size={16} /> {loading ? t('common.loading') : t('reports.preview')}
                            </button>
                        </div>
                    </div>
                </div>

                {/* Preview Panel */}
                <div className="col-lg-8">
                    {showSavedList ? (
                        <div className="card section-card">
                            <div className="card-body">
                                <h5 className="section-title mb-4">{t('reports.saved_reports')}</h5>
                                {savedReports.length === 0 ? (
                                    <p className="text-muted text-center">{t('common.no_data')}</p>
                                ) : (
                                    <div className="table-responsive">
                                        <table className="data-table">
                                            <thead>
                                                <tr>
                                                    <th>{t('common.name')}</th>
                                                    <th>{t('common.description')}</th>
                                                    <th>{t('common.created_at')}</th>
                                                    <th></th>
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {savedReports.map(r => (
                                                    <tr key={r.id}>
                                                        <td className="fw-bold text-primary" style={{ cursor: 'pointer' }} onClick={() => loadReport(r.id)}>
                                                            {r.report_name}
                                                        </td>
                                                        <td>{r.description || '-'}</td>
                                                        <td>{formatShortDate(r.created_at)}</td>
                                                        <td>
                                                            {canDeleteReports && (
                                                                <button className="btn btn-icon btn-sm text-danger" onClick={() => deleteReport(r.id)}>
                                                                    <Trash2 size={14} />
                                                                </button>
                                                            )}
                                                        </td>
                                                    </tr>
                                                ))}
                                            </tbody>
                                        </table>
                                    </div>
                                )}
                            </div>
                        </div>
                    ) : (
                        <div className="card section-card h-100">
                            <div className="card-body">
                                <div className="d-flex justify-content-between align-items-center mb-4">
                                    <h5 className="section-title mb-0">{t('reports.results')}</h5>
                                    {previewData && (
                                        <button className="btn btn-sm btn-outline-secondary" onClick={handleExport}>
                                            <Download size={14} /> {t('common.export')}
                                        </button>
                                    )}
                                </div>

                                {loading ? (
                                    <PageLoading />
                                ) : !previewData ? (
                                    <div className="text-center py-5 text-muted">
                                        <Database size={48} className="mb-3 opacity-25" />
                                        <p>{t('reports.click_preview')}</p>
                                    </div>
                                ) : (
                                    <div className="data-table-container">
                                        <table className="data-table">
                                            <thead>
                                                <tr>
                                                    {config.columns.map(col => (
                                                        <th key={col}>{col}</th>
                                                    ))}
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {previewData.slice(0, 50).map((row, idx) => (
                                                    <tr key={idx}>
                                                        {config.columns.map(col => (
                                                            <td key={col}>{typeof row[col] === 'object' ? JSON.stringify(row[col]) : row[col]}</td>
                                                        ))}
                                                    </tr>
                                                ))}
                                            </tbody>
                                        </table>
                                        <div className="mt-3 text-muted small">
                                            {t('reports.showing_rows')}
                                        </div>
                                    </div>
                                )}
                            </div>
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
