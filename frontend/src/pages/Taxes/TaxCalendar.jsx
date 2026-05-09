import { useState, useEffect, useCallback } from 'react';
import { useTranslation } from 'react-i18next';
import { taxesAPI } from '../../services/taxes';
import { formatShortDate } from '../../utils/dateUtils';
import '../../components/ModuleStyles.css';
import BackButton from '../../components/common/BackButton';
import DateInput from '../../components/common/DateInput';
import { useToast } from '../../context/ToastContext'
import { PageLoading } from '../../components/common/LoadingStates';
import DataTable from '../../components/common/DataTable';
import { useBranch } from '../../context/BranchContext';

const TAX_TYPES = [
    { value: 'vat', label: 'ضريبة القيمة المضافة' },
    { value: 'income', label: 'ضريبة الدخل' },
    { value: 'withholding', label: 'ضريبة الاستقطاع' },
    { value: 'gosi', label: 'التأمينات الاجتماعية' },
    { value: 'zakat', label: 'الزكاة' },
    { value: 'customs', label: 'الجمارك' },
    { value: 'other', label: 'أخرى' },
];

const STATUS_COLORS = {
    overdue: { bg: '#fef2f2', color: '#dc2626', label: 'متأخر' },
    upcoming: { bg: '#fffbeb', color: '#d97706', label: 'قريب' },
    pending: { bg: '#eff6ff', color: '#2563eb', label: 'قادم' },
    completed: { bg: '#f0fdf4', color: '#16a34a', label: 'مكتمل' },
};

function TaxCalendar() {
    const { t } = useTranslation();
  const { showToast } = useToast()
    const { currentBranch } = useBranch()
    const [items, setItems] = useState([]);
    const [summary, setSummary] = useState({});
    const [loading, setLoading] = useState(true);
    const [filter, setFilter] = useState({ status: '', tax_type: '' });
    const [showModal, setShowModal] = useState(false);
    const [editItem, setEditItem] = useState(null);
    const [form, setForm] = useState({
        title: '', tax_type: 'vat', due_date: '', notes: '',
        is_recurring: false, recurrence_months: 3,
        reminder_days: [7, 3, 1]
    });

    const loadData = useCallback(async () => {
        setLoading(true);
        try {
            const params = {};
            if (filter.status) params.status = filter.status;
            if (filter.tax_type) params.tax_type = filter.tax_type;
            if (currentBranch?.id) params.branch_id = currentBranch.id;
            const [itemsRes, summaryRes] = await Promise.all([
                taxesAPI.listCalendar(params),
                taxesAPI.getCalendarSummary(params)
            ]);
            setItems(itemsRes.data || []);
            setSummary(summaryRes.data || {});
        } catch (e) {
            console.error('Error loading tax calendar:', e);
            showToast(e.response?.data?.detail || t('common.error', 'حدث خطأ في تحميل التقويم الضريبي'), 'error');
        } finally {
            setLoading(false);
        }
    }, [currentBranch?.id, filter, showToast, t]);

    useEffect(() => { loadData(); }, [loadData]);

    const openNew = () => {
        setEditItem(null);
        setForm({ title: '', tax_type: 'vat', due_date: '', notes: '', is_recurring: false, recurrence_months: 3, reminder_days: [7, 3, 1] });
        setShowModal(true);
    };

    const openEdit = (item) => {
        setEditItem(item);
        setForm({
            title: item.title,
            tax_type: item.tax_type || 'vat',
            due_date: item.due_date?.substring(0, 10) || '',
            notes: item.notes || '',
            is_recurring: item.is_recurring || false,
            recurrence_months: item.recurrence_months || 3,
            reminder_days: item.reminder_days || [7, 3, 1]
        });
        setShowModal(true);
    };

    const handleSave = async () => {
        try {
            if (editItem) {
                await taxesAPI.updateCalendarItem(editItem.id, { ...form, branch_id: currentBranch?.id || null });
            } else {
                await taxesAPI.createCalendarItem({ ...form, branch_id: currentBranch?.id || null });
            }
            setShowModal(false);
            loadData();
        } catch (e) {
            showToast(e.response?.data?.detail || 'Error', 'error');
        }
    };

    const handleComplete = async (item) => {
        if (!confirm(t('tax_calendar.confirm_complete', `هل تريد تحديد "${item.title}" كمكتمل؟`))) return;
        try {
            await taxesAPI.completeCalendarItem(item.id);
            loadData();
        } catch (e) {
            showToast(t('common.error'), 'error');
        }
    };

    const handleDelete = async (item) => {
        if (!confirm(t('common.confirm_delete', 'هل أنت متأكد من الحذف؟'))) return;
        try {
            await taxesAPI.deleteCalendarItem(item.id);
            loadData();
        } catch (e) {
            showToast(t('common.error'), 'error');
        }
    };

    const getDaysUntil = (dateStr) => {
        const d = new Date(dateStr);
        const now = new Date();
        now.setHours(0, 0, 0, 0);
        return Math.ceil((d - now) / 86400000);
    };

    const columns = [
        {
            key: 'title',
            label: t('tax_calendar.event', 'الحدث'),
            render: (value, item) => (
                <div>
                    <div style={{ fontWeight: 600 }}>{value}</div>
                    {item.notes && <div style={{ fontSize: 12, color: '#888', marginTop: 2 }}>{item.notes}</div>}
                </div>
            ),
        },
        { key: 'tax_type', label: t('tax_calendar.type', 'النوع'), render: (v) => TAX_TYPES.find(t => t.value === v)?.label || v || '-' },
        { key: 'due_date', label: t('tax_calendar.due_date', 'تاريخ الاستحقاق'), render: (v) => formatShortDate(v) },
        {
            key: 'days_left',
            label: t('tax_calendar.days_left', 'الأيام المتبقية'),
            render: (_, item) => {
                const days = getDaysUntil(item.due_date);
                if (item.is_completed) return '✓';
                return (
                    <span style={{ color: days < 0 ? '#dc2626' : days <= 7 ? '#d97706' : '#2563eb', fontWeight: 600 }}>
                        {days < 0 ? `متأخر ${Math.abs(days)} يوم` : days === 0 ? 'اليوم' : `${days} يوم`}
                    </span>
                );
            },
        },
        { key: 'is_recurring', label: t('tax_calendar.recurring', 'متكرر'), render: (v, item) => v ? `كل ${item.recurrence_months} أشهر` : '-' },
        {
            key: 'status',
            label: t('common.status_title', 'الحالة'),
            render: (v) => {
                const st = STATUS_COLORS[v] || STATUS_COLORS.pending;
                return <span style={{ background: st.bg, color: st.color, padding: '3px 10px', borderRadius: 12, fontSize: 12, fontWeight: 600 }}>{st.label}</span>;
            },
        },
        {
            key: 'actions',
            label: t('common.actions', 'الإجراءات'),
            sortable: false,
            searchable: false,
            exportable: false,
            render: (_, item) => (
                <div style={{ display: 'flex', gap: 4 }}>
                    {!item.is_completed && <button className="btn btn-sm btn-success" onClick={() => handleComplete(item)} title="إكمال">✓</button>}
                    <button className="btn btn-sm btn-secondary" onClick={() => openEdit(item)} title="تعديل">تعديل</button>
                    <button className="btn btn-sm btn-danger" onClick={() => handleDelete(item)} title="حذف">حذف</button>
                </div>
            ),
        },
    ];

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">📅 {t('tax_calendar.title', 'تقويم الالتزامات الضريبية')}</h1>
                    <p className="workspace-subtitle">{t('tax_calendar.subtitle', 'متابعة مواعيد التقديم والسداد الضريبي')}</p>
                </div>
                <div className="header-actions">
                    <button className="btn btn-primary" onClick={openNew}>+ {t('tax_calendar.add', 'إضافة موعد')}</button>
                </div>
            </div>

            {/* Summary Cards */}
            <div className="metrics-grid" style={{ marginBottom: 16 }}>
                <div className="metric-card">
                    <div className="metric-value">{summary.total || 0}</div>
                    <div className="metric-label">{t('tax_calendar.total', 'إجمالي المواعيد')}</div>
                </div>
                <div className="metric-card" style={{ borderRight: '3px solid #dc2626' }}>
                    <div className="metric-value" style={{ color: '#dc2626' }}>{summary.overdue || 0}</div>
                    <div className="metric-label">{t('tax_calendar.overdue', 'متأخر')}</div>
                </div>
                <div className="metric-card" style={{ borderRight: '3px solid #d97706' }}>
                    <div className="metric-value" style={{ color: '#d97706' }}>{summary.upcoming_week || 0}</div>
                    <div className="metric-label">{t('tax_calendar.upcoming', 'خلال أسبوع')}</div>
                </div>
                <div className="metric-card" style={{ borderRight: '3px solid #2563eb' }}>
                    <div className="metric-value" style={{ color: '#2563eb' }}>{summary.pending || 0}</div>
                    <div className="metric-label">{t('tax_calendar.pending', 'قادم')}</div>
                </div>
                <div className="metric-card" style={{ borderRight: '3px solid #16a34a' }}>
                    <div className="metric-value" style={{ color: '#16a34a' }}>{summary.completed || 0}</div>
                    <div className="metric-label">{t('tax_calendar.completed', 'مكتمل')}</div>
                </div>
            </div>

            {/* Filters */}
            <div className="section-card" style={{ marginBottom: 16 }}>
                <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap' }}>
                    <select className="form-input" style={{ width: 180 }} value={filter.status} onChange={e => setFilter(f => ({ ...f, status: e.target.value }))}>
                        <option value="">{t('tax_calendar.all_statuses', 'كل الحالات')}</option>
                        <option value="pending">{t('tax_calendar.pending', 'قادم')}</option>
                        <option value="overdue">{t('tax_calendar.overdue', 'متأخر')}</option>
                        <option value="completed">{t('tax_calendar.completed', 'مكتمل')}</option>
                    </select>
                    <select className="form-input" style={{ width: 200 }} value={filter.tax_type} onChange={e => setFilter(f => ({ ...f, tax_type: e.target.value }))}>
                        <option value="">{t('tax_calendar.all_types', 'كل الأنواع')}</option>
                        {TAX_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
                    </select>
                </div>
            </div>

            {/* Calendar Table */}
            <div className="section-card">
                <DataTable
                    columns={columns}
                    data={items}
                    loading={loading}
                    rowKey="id"
                    searchable
                    exportable
                    exportName="tax-calendar"
                    emptyTitle={t('tax_calendar.empty', 'لا توجد مواعيد ضريبية')}
                    emptyAction={{ label: t('taxes.add_first_appointment'), onClick: openNew }}
                />
            </div>

            {/* Next Due Alert */}
            {summary.next_due && (
                <div className="alert alert-warning" style={{ marginTop: 12 }}>
                    ⏰ {t('tax_calendar.next_due_alert', 'الموعد التالي')}: <strong>{formatShortDate(summary.next_due)}</strong>
                    {' '}({getDaysUntil(summary.next_due) <= 0 ? 'متأخر!' : `بعد ${getDaysUntil(summary.next_due)} يوم`})
                </div>
            )}

            {/* Modal */}
            {showModal && (
                <div className="modal-overlay" onClick={() => setShowModal(false)}>
                    <div className="modal-content" onClick={e => e.stopPropagation()} style={{ maxWidth: 500 }}>
                        <div className="modal-header">
                            <h3>{editItem ? t('tax_calendar.edit', 'تعديل موعد') : t('tax_calendar.add', 'إضافة موعد')}</h3>
                            <button className="modal-close" onClick={() => setShowModal(false)}>×</button>
                        </div>
                        <div className="modal-body">
                            <div className="form-grid">
                                <div className="form-group" style={{ gridColumn: '1 / -1' }}>
                                    <label className="form-label">{t('tax_calendar.event_title', 'عنوان الحدث')} *</label>
                                    <input className="form-input" value={form.title} onChange={e => setForm(f => ({ ...f, title: e.target.value }))} placeholder="تقديم إقرار ضريبة القيمة المضافة" />
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('tax_calendar.type', 'النوع')}</label>
                                    <select className="form-input" value={form.tax_type} onChange={e => setForm(f => ({ ...f, tax_type: e.target.value }))}>
                                        {TAX_TYPES.map(t => <option key={t.value} value={t.value}>{t.label}</option>)}
                                    </select>
                                </div>
                                <div className="form-group">
                                    <label className="form-label">{t('tax_calendar.due_date', 'تاريخ الاستحقاق')} *</label>
                                    <DateInput className="form-input" value={form.due_date} onChange={e => setForm(f => ({ ...f, due_date: e.target.value }))} />
                                </div>
                                <div className="form-group">
                                    <label style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                                        <input type="checkbox" checked={form.is_recurring} onChange={e => setForm(f => ({ ...f, is_recurring: e.target.checked }))} />
                                        {t('tax_calendar.is_recurring', 'متكرر')}
                                    </label>
                                </div>
                                {form.is_recurring && (
                                    <div className="form-group">
                                        <label className="form-label">{t('tax_calendar.recurrence', 'التكرار (أشهر)')}</label>
                                        <select className="form-input" value={form.recurrence_months} onChange={e => setForm(f => ({ ...f, recurrence_months: parseInt(e.target.value) }))}>
                                            <option value={1}>{t('common.monthly')}</option>
                                            <option value={3}>{t('common.quarterly')}</option>
                                            <option value={6}>نصف سنوي</option>
                                            <option value={12}>{t('common.annual')}</option>
                                        </select>
                                    </div>
                                )}
                                <div className="form-group" style={{ gridColumn: '1 / -1' }}>
                                    <label className="form-label">{t('tax_calendar.reminder', 'تنبيه قبل (أيام)')}</label>
                                    <input className="form-input" value={(form.reminder_days || []).join(', ')}
                                        onChange={e => setForm(f => ({
                                            ...f,
                                            reminder_days: e.target.value.split(',').map(d => parseInt(d.trim())).filter(d => !isNaN(d))
                                        }))}
                                        placeholder="7, 3, 1" />
                                </div>
                                <div className="form-group" style={{ gridColumn: '1 / -1' }}>
                                    <label className="form-label">{t('common.notes', 'ملاحظات')}</label>
                                    <textarea className="form-input" rows={3} value={form.notes} onChange={e => setForm(f => ({ ...f, notes: e.target.value }))} />
                                </div>
                            </div>
                        </div>
                        <div className="modal-footer">
                            <button className="btn btn-secondary" onClick={() => setShowModal(false)}>{t('common.cancel', 'إلغاء')}</button>
                            <button className="btn btn-primary" onClick={handleSave} disabled={!form.title || !form.due_date}>{t('common.save', 'حفظ')}</button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}

export default TaxCalendar;
