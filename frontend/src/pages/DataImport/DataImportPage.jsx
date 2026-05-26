import React, { useEffect, useState } from 'react';
import { useTranslation } from 'react-i18next';
import { Download, AlertTriangle, FileText, Play, Info, Eye } from 'lucide-react';
import BackButton from '../../components/common/BackButton';
import { dataImportAPI } from '../../services/dataImport';
import { useToast } from '../../context/ToastContext';
import { hasPermission } from '../../utils/auth';
import { Spinner } from '../../components/common/LoadingStates'

const makeIdempotencyKey = (prefix) => (
    `${prefix}:${globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`}`
)

const DataImportPage = () => {
    const { t } = useTranslation();
    const { showToast } = useToast();
    const canImport = hasPermission(['data_import.create', 'data_import.manage', 'data_import.execute']);

    const [entity, setEntity] = useState('');
    const [file, setFile] = useState(null);
    const [previewData, setPreviewData] = useState(null);
    const [loading, setLoading] = useState(false);
    const [importing, setImporting] = useState(false);

    const fallbackEntities = [
        { value: 'accounts', label: t('data_import.accounts') },
        { value: 'parties', label: t('data_import.parties') },
        { value: 'customers', label: t('data_import.customers', 'Customers') },
        { value: 'suppliers', label: t('data_import.suppliers', 'Suppliers') },
        { value: 'products', label: t('data_import.products') },
        { value: 'employees', label: t('data_import.employees') }
    ];
    const [entities, setEntities] = useState(fallbackEntities);

    useEffect(() => {
        let cancelled = false;
        dataImportAPI.getEntityTypes()
            .then((response) => {
                if (!cancelled && Array.isArray(response.data)) {
                    setEntities(response.data.map((item) => ({
                        value: item.value,
                        label: item.label || item.value
                    })));
                }
            })
            .catch(() => {
                if (!cancelled) setEntities(fallbackEntities);
            });
        return () => {
            cancelled = true;
        };
    }, [t]);

    const handleFileChange = (e) => {
        setFile(e.target.files[0]);
        setPreviewData(null); // Clear preview when file changes
    };

    const handleDownloadTemplate = async () => {
        if (!entity) {
            showToast(t('data_import.select_entity'), "warning");
            return;
        }
        try {
            const response = await dataImportAPI.getTemplate(entity);
            const url = URL.createObjectURL(new Blob([response.data], {
                type: response.headers?.['content-type'] || 'text/csv'
            }));
            const link = document.createElement('a');
            link.href = url;
            link.download = `${entity}_template.csv`;
            document.body.appendChild(link);
            link.click();
            link.remove();
            URL.revokeObjectURL(url);
        } catch (error) {
            showToast(t('common.error'), "error");
        }
    };

    const handlePreview = async () => {
        if (!entity || !file) {
            showToast(t('common.fill_required'), "warning");
            return;
        }

        const formData = new FormData();
        formData.append('file', file);

        setLoading(true);
        try {
            const response = await dataImportAPI.previewImport(formData, entity);
            setPreviewData(response.data);
            showToast(t('common.success'), "success");
        } catch (error) {
            showToast(error.response?.data?.detail || t('common.error'), "error");
        } finally {
            setLoading(false);
        }
    };

    const handleImport = async () => {
        if (!previewData) return;

        if (!window.confirm(t('common.confirm_action'))) return;

        const formData = new FormData();
        formData.append('file', file);

        setImporting(true);
        try {
            await dataImportAPI.executeImport(
                formData,
                entity,
                makeIdempotencyKey(`data-import:${entity}`)
            );

            showToast(t('common.success'), "success");
            setPreviewData(null);
            setFile(null);
        } catch (error) {
            showToast(error.response?.data?.detail || t('common.error'), "error");
        } finally {
            setImporting(false);
        }
    };

    return (
        <div className="workspace fade-in space-y-6">
            <div className="flex justify-between items-center">
                <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
                    <BackButton />
                    <h1 className="text-2xl font-bold">{t('data_import.title')}</h1>
                </div>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* Step 1: Configuration */}
                <div className="card bg-base-100 shadow-sm border border-base-200 lg:col-span-1">
                    <div className="card-body">
                        <h2 className="card-title text-lg flex items-center gap-2">
                            <span className="badge badge-primary badge-outline">1</span>
                            {t('data_import.setup')}
                        </h2>

                        <div className="space-y-4 mt-4">
                            <div className="form-group mb-4">
                                <label className="form-label">{t('data_import.entity_type')}</label>
                                <select
                                    className="form-input"
                                    value={entity}
                                    onChange={(e) => setEntity(e.target.value)}
                                >
                                    <option value="">{t('common.select')}</option>
                                    {entities.map(e => <option key={e.value} value={e.value}>{e.label}</option>)}
                                </select>
                            </div>

                            <div className="bg-base-200/50 p-4 rounded-xl space-y-2 border border-base-200">
                                <p className="text-sm font-bold">{t('data_import.need_template')}</p>
                                <p className="text-xs opacity-70">{t('data_import.need_template_desc')}</p>
                                <button
                                    className="btn btn-sm btn-outline btn-block mt-2 gap-2"
                                    onClick={handleDownloadTemplate}
                                    disabled={!entity}
                                >
                                    <Download size={16} /> {t('data_import.download_template')}
                                </button>
                            </div>

                            <div className="form-group mb-4">
                                <label className="form-label">{t('data_import.upload_file')}</label>
                                <input
                                    type="file"
                                    className="form-input"
                                    onChange={handleFileChange}
                                    accept=".csv,.xlsx,.xls"
                                />
                            </div>

                            <button
                                className="btn btn-primary btn-block mt-4 gap-2"
                                onClick={handlePreview}
                                disabled={!entity || !file || loading}
                            >
                                {loading ? <Spinner size="sm"/> : <Eye size={18} />}
                                {t('data_import.preview_data')}
                            </button>
                        </div>
                    </div>
                </div>

                {/* Step 2: Preview & Validation */}
                <div className="card bg-base-100 shadow-sm border border-base-200 lg:col-span-2">
                    <div className="card-body">
                        <h2 className="card-title text-lg flex items-center gap-2">
                            <span className="badge badge-primary badge-outline">2</span>
                            {t('data_import.preview')}
                        </h2>

                        {!previewData ? (
                            <div className="flex flex-col items-center justify-center h-64 opacity-30">
                                <FileText size={48} />
                                <p className="mt-2">{t('data_import.upload_file')}</p>
                            </div>
                        ) : (
                            <div className="space-y-4">
                                {(() => {
                                    const previewRows = previewData.preview_rows || [];
                                    const hasErrors = (previewData.invalid_count || 0) > 0 || (previewData.errors?.length || 0) > 0;
                                    return (
                                        <>
                                <div className="flex justify-between items-center bg-info/10 p-3 rounded-lg border border-info/20 text-info text-sm">
                                    <div className="flex items-center gap-2">
                                        <Info size={16} />
                                        <span>{t('data_import.found_records', { count: previewData.total_rows || 0 })}</span>
                                    </div>
                                    {hasErrors && (
                                        <div className="text-error font-bold text-xs">
                                            {previewData.invalid_count || previewData.errors.length} {t('data_import.validation_errors')}
                                        </div>
                                    )}
                                </div>

                                <div className="overflow-x-auto border rounded-xl max-h-[400px]">
                                    <table className="table table-compact w-full sticky-header">
                                        <thead>
                                            <tr>
                                                {previewData.columns.map(col => (
                                                    <th key={col}>{col}</th>
                                                ))}
                                            </tr>
                                        </thead>
                                        <tbody>
                                            {previewRows.slice(0, 10).map((row, i) => (
                                                <tr key={i} className={row.valid ? '' : 'bg-error/10'}>
                                                    {previewData.columns.map(col => (
                                                        <td key={col} className="text-xs">{String(row.data?.[col] || '')}</td>
                                                    ))}
                                                </tr>
                                            ))}
                                        </tbody>
                                    </table>
                                    {previewRows.length > 10 && (
                                        <div className="p-2 text-center text-xs opacity-50 bg-base-200">
                                            {t('data_import.showing_rows', { count: 10, total: previewRows.length })}
                                        </div>
                                    )}
                                </div>

                                <div className="flex justify-end gap-4 mt-6">
                                    <button
                                        className="btn btn-ghost"
                                        onClick={() => setPreviewData(null)}
                                    >
                                        {t('data_import.clear', 'Clear')}
                                    </button>
                                    <button
                                        className="btn btn-success gap-2"
                                        disabled={importing || hasErrors || !canImport}
                                        onClick={handleImport}
                                    >
                                        {importing ? <Spinner size="sm"/> : <Play size={18} />}
                                        {t('data_import.start_import')}
                                    </button>
                                </div>
                                {hasErrors && (
                                    <div className="alert alert-error text-xs p-2 mt-2">
                                        <AlertTriangle size={14} />
                                        {t('data_import.fix_errors')}
                                    </div>
                                )}
                                        </>
                                    );
                                })()}
                            </div>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
};

export default DataImportPage;
