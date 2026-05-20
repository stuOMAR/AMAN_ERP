import { useState, useEffect, useRef } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import {
    Edit2, Trash2, Plus, CheckCircle2,
    DollarSign, TrendingUp, TrendingDown, ClipboardList,
    FolderKanban, Calendar, BarChart3, Clock, FileText, Download, File
} from 'lucide-react';
import { projectsAPI, treasuryAPI } from '../../utils/api';
import { formatNumber } from '../../utils/format';
import Decimal from 'decimal.js';
import { toastEmitter } from '../../utils/toastEmitter';
import SimpleModal from '../../components/common/SimpleModal';
import GanttChart from './GanttChart';
import Timesheets from './Timesheets';
import '../../components/ModuleStyles.css';

import DateInput from '../../components/common/DateInput';
import { formatShortDate, formatDate } from '../../utils/dateUtils';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'
import { useBranch } from '../../context/BranchContext';

export default function ProjectDetails() {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const { id } = useParams();
    const { currentBranch } = useBranch();

    const fileInputRef = useRef(null);

    const [project, setProject] = useState(null);
    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);
    const [activeTab, setActiveTab] = useState('overview');

    // Modals
    const [showTaskModal, setShowTaskModal] = useState(false);
    const [showExpenseModal, setShowExpenseModal] = useState(false);
    const [showRevenueModal, setShowRevenueModal] = useState(false);
    const [showInvoiceModal, setShowInvoiceModal] = useState(false);
    const [showDeleteConfirm, setShowDeleteConfirm] = useState(false);

    // Treasury accounts for expense form
    const [treasuryAccounts, setTreasuryAccounts] = useState([]);
    const [documents, setDocuments] = useState([]);

    // Task form
    const [taskForm, setTaskForm] = useState({
        task_name: '', description: '', start_date: '', end_date: '',
        planned_hours: '', status: 'pending'
    });

    // Expense form
    const [expenseForm, setExpenseForm] = useState({
        expense_type: 'other', expense_date: new Date().toISOString().split('T')[0],
        amount: '', description: '', treasury_id: ''
    });

    // Revenue form
    const [revenueForm, setRevenueForm] = useState({
        revenue_type: 'milestone', revenue_date: new Date().toISOString().split('T')[0],
        amount: '', description: ''
    });

    // Invoice form
    const [invoiceForm, setInvoiceForm] = useState({
        invoice_date: new Date().toISOString().split('T')[0],
        due_date: new Date().toISOString().split('T')[0],
        invoice_due_date: new Date().toISOString().split('T')[0], // Add explicit field if needed, but reusing due_date
        description: '', amount: '', notes: ''
    });

    const [submitting, setSubmitting] = useState(false);

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchProject();
            fetchDocuments();
            fetchTreasury();
        }, 300)
        return () => clearTimeout(timer)
    }, [id, currentBranch?.id]);

    const fetchProject = async () => {
        try {
            setLoading(true);
            const res = await projectsAPI.get(id);
            setProject(res.data);
            // Pre-fill invoice description
            if (res.data) {
                setInvoiceForm(prev => ({ ...prev, description: `Project Invoice: ${res.data.project_name}` }));
            }
        } catch (err) {
            toastEmitter.emit(t('common.load_error'), 'error');
            navigate('/projects');
        } finally {
            setLoading(false);
            setInitialLoad(false);
        }
    };

    const fetchTreasury = async () => {
        try {
            const res = await treasuryAPI.listAccounts(currentBranch?.id);
            setTreasuryAccounts(res.data || []);
        } catch { }
    };

    const handleDelete = async () => {
        try {
            await projectsAPI.delete(id);
            toastEmitter.emit(t('projects.messages.deleted'), 'success');
            navigate('/projects');
        } catch (err) {
            toastEmitter.emit(err.response?.data?.detail || t('common.save_error'), 'error');
        }
        setShowDeleteConfirm(false);
    };

    // Task handlers
    const handleAddTask = async () => {
        if (!taskForm.task_name.trim()) return;
        setSubmitting(true);
        try {
            await projectsAPI.createTask(id, {
                ...taskForm,
                planned_hours: taskForm.planned_hours || '0',
                start_date: taskForm.start_date || null,
                end_date: taskForm.end_date || null,
            });
            toastEmitter.emit(t('projects.messages.task_added'), 'success');
            setShowTaskModal(false);
            setTaskForm({ task_name: '', description: '', start_date: '', end_date: '', planned_hours: '', status: 'pending' });
            fetchProject();
        } catch (err) {
            toastEmitter.emit(t('common.save_error'), 'error');
        } finally {
            setSubmitting(false);
        }
    };

    const handleUpdateTaskStatus = async (taskId, newStatus) => {
        try {
            await projectsAPI.updateTask(id, taskId, { status: newStatus, progress: newStatus === 'completed' ? 100 : undefined });
            fetchProject();
        } catch (err) {
            toastEmitter.emit(t('common.save_error'), 'error');
        }
    };

    const handleDeleteTask = async (taskId) => {
        try {
            await projectsAPI.deleteTask(id, taskId);
            fetchProject();
        } catch (err) {
            toastEmitter.emit(t('common.save_error'), 'error');
        }
    };

    // Expense handler
    const handleAddExpense = async () => {
        if (!expenseForm.amount || new Decimal(expenseForm.amount || 0).lte(0)) {
            toastEmitter.emit(t('projects.errors.amount_required'), 'error');
            return;
        }
        setSubmitting(true);
        try {
            await projectsAPI.createExpense(id, {
                ...expenseForm,
                amount: expenseForm.amount,
                treasury_id: expenseForm.treasury_id ? parseInt(expenseForm.treasury_id, 10) : null,
            });
            toastEmitter.emit(t('projects.messages.expense_added'), 'success');
            setShowExpenseModal(false);
            setExpenseForm({ expense_type: 'other', expense_date: new Date().toISOString().split('T')[0], amount: '', description: '', treasury_id: '' });
            fetchProject();
        } catch (err) {
            toastEmitter.emit(err.response?.data?.detail || t('common.save_error'), 'error');
        } finally {
            setSubmitting(false);
        }
    };

    // Revenue handler
    const handleAddRevenue = async () => {
        if (!revenueForm.amount || new Decimal(revenueForm.amount || 0).lte(0)) {
            toastEmitter.emit(t('projects.errors.amount_required'), 'error');
            return;
        }
        setSubmitting(true);
        try {
            await projectsAPI.createRevenue(id, {
                ...revenueForm,
                amount: revenueForm.amount,
            });
            toastEmitter.emit(t('projects.messages.revenue_added'), 'success');
            setShowRevenueModal(false);
            setRevenueForm({ revenue_type: 'milestone', revenue_date: new Date().toISOString().split('T')[0], amount: '', description: '' });
            fetchProject();
        } catch (err) {
            toastEmitter.emit(err.response?.data?.detail || t('common.save_error'), 'error');
        } finally {
            setSubmitting(false);
        }
    };

    // Invoice Handler
    const handleCreateInvoice = async () => {
        if (!invoiceForm.amount || new Decimal(invoiceForm.amount || 0).lte(0)) {
            toastEmitter.emit(t('projects.errors.amount_required'), 'error');
            return;
        }
        setSubmitting(true);
        try {
            // Simplified Invoice Items for this quick action
            const payload = {
                customer_id: project.customer_id,
                warehouse_id: null,
                invoice_date: invoiceForm.invoice_date,
                due_date: invoiceForm.due_date,
                notes: invoiceForm.notes,
                items: [{
                    description: invoiceForm.description, // Corrected field name
                    quantity: 1,
                    unit_price: invoiceForm.amount,
                    discount: 0
                }]
            };

            await projectsAPI.createInvoice(id, payload);
            toastEmitter.emit(t('projects.messages.invoice_created'), 'success');
            setShowInvoiceModal(false);
            setInvoiceForm({ ...invoiceForm, amount: '', notes: '' });
            fetchProject(); // Updates revenue
        } catch (err) {
            toastEmitter.emit(err.response?.data?.detail || t('common.save_error'), 'error');
        } finally {
            setSubmitting(false);
        }
    };

    // Document Fetch
    const fetchDocuments = async () => {
        try {
            const res = await projectsAPI.getDocuments(id);
            setDocuments(res.data || []);
        } catch { }
    };

    // Document Upload
    const handleFileUpload = async (e) => {
        const file = e.target.files[0];
        if (!file) return;

        const formData = new FormData();
        formData.append('file', file);

        try {
            await projectsAPI.uploadDocument(id, formData);
            toastEmitter.emit(t('projects.messages.upload_success'), 'success');
            fetchDocuments();
        } catch (err) {
            toastEmitter.emit(t('common.upload_error'), 'error');
        } finally {
            if (fileInputRef.current) fileInputRef.current.value = '';
        }
    };

    const handleDeleteDocument = async (docId) => {
        try {
            await projectsAPI.deleteDocument(id, docId);
            toastEmitter.emit(t('common.deleted'), 'success');
            fetchDocuments();
        } catch (err) {
            toastEmitter.emit(t('common.delete_error'), 'error');
        }
    };

    const getStatusBadge = (status) => {
        const map = {
            planning: { label: t('projects.status.planning'), class: 'badge-info' },
            in_progress: { label: t('projects.status.in_progress'), class: 'badge-warning' },
            completed: { label: t('projects.status.completed'), class: 'badge-success' },
            on_hold: { label: t('projects.status.on_hold'), class: 'badge-secondary' },
            cancelled: { label: t('projects.status.cancelled'), class: 'badge-danger' },
            pending: { label: t('projects.task_status.pending'), class: 'badge-secondary' },
        };
        const s = map[status] || { label: status, class: 'badge-secondary' };
        return <span className={`badge ${s.class}`}>{s.label}</span>;
    };

    const getExpenseTypeLabel = (type) => {
        const map = {
            materials: t('projects.expense_types.materials'),
            labor: t('projects.expense_types.labor'),
            services: t('projects.expense_types.services'),
            travel: t('projects.expense_types.travel'),
            other: t('projects.expense_types.other'),
        };
        return map[type] || type;
    };

    const getRevenueTypeLabel = (type) => {
        const map = {
            milestone: t('projects.revenue_types.milestone'),
            invoice: t('projects.revenue_types.invoice'),
            advance: t('projects.revenue_types.advance'),
            other: t('projects.revenue_types.other'),
        };
        return map[type] || type;
    };

    if (initialLoad && loading) {
        return <PageLoading />;
    }

    if (!project) return null;

    const fs = project.financial_summary || {};
    const progress = project.progress_percentage || 0;
    const tasks = project.tasks || [];
    const expenses = project.expenses || [];
    const revenues = project.revenues || [];

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            {/* Header */}
            <div className="workspace-header">
                <div className="d-flex align-items-center justify-content-between w-100">
                    <div className="d-flex align-items-center gap-3">
                        <BackButton />
                        <div>
                            <div className="d-flex align-items-center gap-2">
                                <h1 className="workspace-title mb-0">{project.project_name}</h1>
                                {getStatusBadge(project.status)}
                            </div>
                            <p className="workspace-subtitle mb-0">
                                {project.project_code} {project.customer_name ? `• ${project.customer_name}` : ''}
                            </p>
                        </div>
                    </div>
                    <div className="header-actions d-flex gap-2">
                        <button className="btn btn-light" onClick={() => navigate(`/projects/${id}/edit`)}>
                            <Edit2 size={16} /> {t('common.edit')}
                        </button>
                        <button className="btn btn-danger" onClick={() => setShowDeleteConfirm(true)}>
                            <Trash2 size={16} />
                        </button>
                    </div>
                </div>
            </div>

            {/* Financial Metrics */}
            <div className="metrics-grid mb-4">
                <div className="metric-card">
                    <div className="metric-icon" style={{ background: 'linear-gradient(135deg, #667eea, #764ba2)' }}>
                        <DollarSign size={24} color="white" />
                    </div>
                    <div className="metric-info">
                        <span className="metric-value">{formatNumber(fs.planned_budget || 0)}</span>
                        <span className="metric-label">{t('projects.metrics.budget')}</span>
                    </div>
                </div>
                <div className="metric-card">
                    <div className="metric-icon" style={{ background: 'linear-gradient(135deg, #f5576c, #ff6b6b)' }}>
                        <TrendingDown size={24} color="white" />
                    </div>
                    <div className="metric-info">
                        <span className="metric-value">{formatNumber(fs.total_expenses || 0)}</span>
                        <span className="metric-label">{t('projects.metrics.expenses')}</span>
                    </div>
                </div>
                <div className="metric-card">
                    <div className="metric-icon" style={{ background: 'linear-gradient(135deg, #43e97b, #38f9d7)' }}>
                        <TrendingUp size={24} color="white" />
                    </div>
                    <div className="metric-info">
                        <span className="metric-value">{formatNumber(fs.total_revenues || 0)}</span>
                        <span className="metric-label">{t('projects.metrics.revenues')}</span>
                    </div>
                </div>
                <div className="metric-card">
                    <div className="metric-icon" style={{ background: fs.profit_loss >= 0 ? 'linear-gradient(135deg, #11998e, #38ef7d)' : 'linear-gradient(135deg, #eb3349, #f45c43)' }}>
                        <BarChart3 size={24} color="white" />
                    </div>
                    <div className="metric-info">
                        <span className="metric-value" style={{ color: fs.profit_loss >= 0 ? '#28a745' : '#dc3545' }}>
                            {formatNumber(fs.profit_loss || 0)}
                        </span>
                        <span className="metric-label">{t('projects.metrics.profit_loss')}</span>
                    </div>
                </div>
            </div>

            {/* Progress Bar */}
            <div className="card section-card mb-4">
                <div className="card-body">
                    <div className="d-flex justify-content-between mb-2">
                        <span className="fw-medium">{t('projects.fields.progress')}</span>
                        <span className="fw-bold">{progress.toFixed(0)}%</span>
                    </div>
                    <div style={{ height: 12, borderRadius: 6, background: '#e9ecef', overflow: 'hidden' }}>
                        <div style={{
                            width: `${progress}%`, height: '100%', borderRadius: 6,
                            background: progress >= 80 ? '#28a745' : progress >= 50 ? '#ffc107' : '#17a2b8',
                            transition: 'width 0.5s ease'
                        }} />
                    </div>
                    <div className="d-flex justify-content-between mt-2">
                        <small className="text-muted">
                            {t('projects.fields.budget_consumed')}: {(fs.budget_consumed_pct || 0).toFixed(1)}%
                        </small>
                        <small className="text-muted">
                            {tasks.filter(t => t.status === 'completed').length}/{tasks.length} {t('projects.fields.tasks_completed')}
                        </small>
                    </div>
                </div>
            </div>

            {/* Tabs */}
            <div className="d-flex gap-2 mb-4 flex-wrap">
                {['overview', 'tasks', 'gantt', 'timesheets', 'documents', 'expenses', 'revenues', 'financials'].map(tab => (
                    <button key={tab}
                        className={`btn ${activeTab === tab ? 'btn-primary' : 'btn-light'}`}
                        onClick={() => setActiveTab(tab)}>
                        {tab === 'overview' && <><FolderKanban size={16} /> {t('projects.tabs.overview')}</>}
                        {tab === 'tasks' && <><ClipboardList size={16} /> {t('projects.tabs.tasks')} ({tasks.length})</>}
                        {tab === 'gantt' && <><Calendar size={16} /> {t('projects.tabs.gantt')}</>}
                        {tab === 'timesheets' && <><Clock size={16} /> {t('projects.tabs.timesheets')}</>}
                        {tab === 'documents' && <><FileText size={16} /> {t('projects.tabs.documents')}</>}
                        {tab === 'expenses' && <><TrendingDown size={16} /> {t('projects.tabs.expenses')} ({expenses.length})</>}
                        {tab === 'revenues' && <><TrendingUp size={16} /> {t('projects.tabs.revenues')} ({revenues.length})</>}
                        {tab === 'financials' && <><DollarSign size={16} /> {t('projects.tabs.financials')}</>}
                    </button>
                ))}
            </div>

            {/* Tab Content */}
            {activeTab === 'overview' && (
                <div className="card section-card">
                    <div className="card-body">
                        <div className="row g-4">
                            <div className="col-md-6">
                                <div className="mb-3">
                                    <small className="text-muted d-block">{t('projects.fields.type')}</small>
                                    <span className="fw-medium">{project.project_type === 'external' ? t('projects.types.external') : project.project_type === 'consulting' ? t('projects.types.consulting') : t('projects.types.internal')}</span>
                                </div>
                                <div className="mb-3">
                                    <small className="text-muted d-block">{t('projects.fields.customer')}</small>
                                    <span className="fw-medium">{project.customer_name || t('common.not_specified')}</span>
                                </div>
                                <div className="mb-3">
                                    <small className="text-muted d-block">{t('projects.fields.manager')}</small>
                                    <span className="fw-medium">{project.manager_name || t('common.not_specified')}</span>
                                </div>
                            </div>
                            <div className="col-md-6">
                                <div className="mb-3">
                                    <small className="text-muted d-block">{t('projects.fields.start_date')}</small>
                                    <span className="fw-medium">{formatDate(project.start_date)}</span>
                                </div>
                                <div className="mb-3">
                                    <small className="text-muted d-block">{t('projects.fields.end_date')}</small>
                                    <span className="fw-medium">{formatDate(project.end_date)}</span>
                                </div>
                                <div className="mb-3">
                                    <small className="text-muted d-block">{t('projects.fields.description')}</small>
                                    <span className="fw-medium">{project.description || '-'}</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {activeTab === 'tasks' && (
                <div className="card section-card">
                    <div className="card-body">
                        <div className="d-flex justify-content-between mb-3">
                            <h5 className="section-title">{t('projects.tabs.tasks')}</h5>
                            <button className="btn btn-primary btn-sm" onClick={() => setShowTaskModal(true)}>
                                <Plus size={16} /> {t('projects.add_task')}
                            </button>
                        </div>
                        {tasks.length === 0 ? (
                            <div className="text-center py-5 text-muted">{t('projects.no_tasks')}</div>
                        ) : (
                            <div className="data-table-container">
                                <table className="data-table">
                                    <thead>
                                        <tr>
                                            <th>{t('projects.task_fields.name')}</th>
                                            <th>{t('projects.task_fields.status')}</th>
                                            <th>{t('projects.task_fields.progress')}</th>
                                            <th>{t('projects.task_fields.hours')}</th>
                                            <th>{t('projects.task_fields.assigned')}</th>
                                            <th></th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {tasks.map(task => (
                                            <tr key={task.id}>
                                                <td className="fw-medium">{task.task_name}</td>
                                                <td>{getStatusBadge(task.status)}</td>
                                                <td>{task.progress || 0}%</td>
                                                <td>{task.actual_hours || 0}/{task.planned_hours || 0}</td>
                                                <td>{task.assigned_to_name || '-'}</td>
                                                <td>
                                                    <div className="d-flex gap-1">
                                                        {task.status !== 'completed' && (
                                                            <button className="btn btn-icon btn-sm btn-light"
                                                                title={t('projects.complete_task')}
                                                                onClick={() => handleUpdateTaskStatus(task.id, 'completed')}>
                                                                <CheckCircle2 size={14} />
                                                            </button>
                                                        )}
                                                        <button className="btn btn-icon btn-sm btn-light text-danger"
                                                            onClick={() => handleDeleteTask(task.id)}>
                                                            <Trash2 size={14} />
                                                        </button>
                                                    </div>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </div>
                </div>
            )}

            {activeTab === 'gantt' && (
                <div className="card section-card">
                    <div className="card-body">
                        <div className="d-flex justify-content-between mb-3">
                            <h5 className="section-title">{t('projects.tabs.gantt')}</h5>
                        </div>
                        <GanttChart tasks={tasks} />
                    </div>
                </div>
            )}

            {activeTab === 'timesheets' && (
                <div className="card section-card">
                    <div className="card-body">
                        <div className="d-flex justify-content-between mb-3">
                            <h5 className="section-title">{t('projects.tabs.timesheets')}</h5>
                        </div>
                        <Timesheets projectId={id} tasks={tasks} />
                    </div>
                </div>
            )}

            {activeTab === 'documents' && (
                <div className="card section-card">
                    <div className="card-body">
                        <div className="d-flex justify-content-between mb-3">
                            <h5 className="section-title">{t('projects.tabs.documents')}</h5>
                            <button className="btn btn-primary btn-sm" onClick={() => fileInputRef.current.click()}>
                                <Plus size={16} /> {t('common.upload')}
                            </button>
                            <input type="file" ref={fileInputRef} className="d-none" onChange={handleFileUpload} />
                        </div>
                        {documents.length === 0 ? (
                            <div className="text-center py-5 text-muted">{t('common.no_data')}</div>
                        ) : (
                            <div className="row g-3">
                                {documents.map(doc => (
                                    <div key={doc.id} className="col-md-4 col-lg-3">
                                        <div className="card h-100 shadow-sm border">
                                            <div className="d-flex flex-column align-items-center text-center">
                                                <div className="mb-2 text-primary"><FileText size={32} /></div>
                                                <h6 className="text-truncate w-100" title={doc.file_name}>{doc.file_name}</h6>
                                                <small className="text-muted d-block mb-2">{formatShortDate(doc.created_at)}</small>
                                                <div className="mt-auto d-flex gap-2">
                                                    <a href={`/api${doc.file_url}`} target="_blank" className="btn btn-sm btn-light btn-icon" download>
                                                        <Download size={14} />
                                                    </a>
                                                    <button className="btn btn-sm btn-light btn-icon text-danger" onClick={() => handleDeleteDocument(doc.id)}>
                                                        <Trash2 size={14} />
                                                    </button>
                                                </div>
                                            </div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </div>
            )}

            {activeTab === 'expenses' && (
                <div className="card section-card">
                    <div className="card-body">
                        <div className="d-flex justify-content-between mb-3">
                            <h5 className="section-title">{t('projects.tabs.expenses')}</h5>
                            <button className="btn btn-primary btn-sm" onClick={() => setShowExpenseModal(true)}>
                                <Plus size={16} /> {t('projects.add_expense')}
                            </button>
                        </div>
                        {expenses.length === 0 ? (
                            <div className="text-center py-5 text-muted">{t('projects.no_expenses')}</div>
                        ) : (
                            <div className="data-table-container">
                                <table className="data-table">
                                    <thead>
                                        <tr>
                                            <th>{t('projects.expense_fields.date')}</th>
                                            <th>{t('projects.expense_fields.type')}</th>
                                            <th>{t('projects.expense_fields.description')}</th>
                                            <th>{t('projects.expense_fields.amount')}</th>
                                            <th>{t('projects.expense_fields.by')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {expenses.map(exp => (
                                            <tr key={exp.id}>
                                                <td>{exp.expense_date}</td>
                                                <td>{getExpenseTypeLabel(exp.expense_type)}</td>
                                                <td>{exp.description || '-'}</td>
                                                <td className="fw-bold text-danger">{formatNumber(exp.amount)}</td>
                                                <td>{exp.created_by_name || '-'}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </div>
                </div>
            )}

            {activeTab === 'revenues' && (
                <div className="card section-card">
                    <div className="card-body">
                        <div className="d-flex justify-content-between mb-3">
                            <h5 className="section-title">{t('projects.tabs.revenues')}</h5>
                            <div className="d-flex gap-2">
                                <button className="btn btn-outline-primary btn-sm" onClick={() => setShowInvoiceModal(true)}>
                                    <File size={16} /> {t('projects.create_invoice')}
                                </button>
                                <button className="btn btn-primary btn-sm" onClick={() => setShowRevenueModal(true)}>
                                    <Plus size={16} /> {t('projects.add_revenue')}
                                </button>
                            </div>
                        </div>
                        {revenues.length === 0 ? (
                            <div className="text-center py-5 text-muted">{t('projects.no_revenues')}</div>
                        ) : (
                            <div className="data-table-container">
                                <table className="data-table">
                                    <thead>
                                        <tr>
                                            <th>{t('projects.revenue_fields.date')}</th>
                                            <th>{t('projects.revenue_fields.type')}</th>
                                            <th>{t('projects.revenue_fields.description')}</th>
                                            <th>{t('projects.revenue_fields.amount')}</th>
                                            <th>{t('projects.revenue_fields.by')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {revenues.map(rev => (
                                            <tr key={rev.id}>
                                                <td>{rev.revenue_date}</td>
                                                <td>{getRevenueTypeLabel(rev.revenue_type)}</td>
                                                <td>{rev.description || '-'}</td>
                                                <td className="fw-bold text-success">{formatNumber(rev.amount)}</td>
                                                <td>{rev.created_by_name || '-'}</td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </div>
                </div>
            )}

            {activeTab === 'financials' && (
                <div className="row g-4">
                    {/* Cost Breakdown */}
                    <div className="col-md-6">
                        <div className="card section-card h-100">
                            <div className="card-body">
                                <h5 className="section-title mb-4">{t('projects.financials.cost_structure')}</h5>
                                <div className="d-flex flex-column gap-3">
                                    <div className="d-flex justify-content-between align-items-center p-3 bg-light rounded">
                                        <div className="d-flex align-items-center gap-2">
                                            <div className="rounded-circle bg-primary" style={{ width: 10, height: 10 }}></div>
                                            <span>{t('projects.expense_types.labor')}</span>
                                        </div>
                                        <div className="fw-bold">{formatNumber(fs.cost_breakdown?.labor || 0)}</div>
                                    </div>
                                    <div className="d-flex justify-content-between align-items-center p-3 bg-light rounded">
                                        <div className="d-flex align-items-center gap-2">
                                            <div className="rounded-circle bg-warning" style={{ width: 10, height: 10 }}></div>
                                            <span>{t('projects.expense_types.materials')}</span>
                                        </div>
                                        <div className="fw-bold">{formatNumber(fs.cost_breakdown?.materials || 0)}</div>
                                    </div>
                                    <div className="d-flex justify-content-between align-items-center p-3 bg-light rounded">
                                        <div className="d-flex align-items-center gap-2">
                                            <div className="rounded-circle bg-info" style={{ width: 10, height: 10 }}></div>
                                            <span>{t('projects.financials.overhead')}</span>
                                        </div>
                                        <div className="fw-bold">{formatNumber(fs.cost_breakdown?.indirect_overhead || 0)}</div>
                                    </div>
                                    <div className="mt-3 pt-3 border-top d-flex justify-content-between">
                                        <span className="fw-bold">{t('common.total')}</span>
                                        <span className="fw-bold">{formatNumber(fs.total_expenses || 0)}</span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>

                    {/* Profitability */}
                    <div className="col-md-6">
                        <div className="card section-card h-100">
                            <div className="card-body">
                                <h5 className="section-title mb-4">{t('projects.financials.profitability')}</h5>
                                <div className="text-center py-4">
                                    <div className="display-4 fw-bold mb-2" style={{ color: fs.net_profit >= 0 ? '#28a745' : '#dc3545' }}>
                                        {formatNumber(fs.net_profit || 0)}
                                    </div>
                                    <div className="text-muted mb-4">{t('projects.financials.net_profit')}</div>

                                    <div className="d-inline-block px-4 py-2 rounded-pill bg-light border">
                                        <span className="text-muted me-2">{t('projects.financials.margin')}:</span>
                                        <span className={`fw-bold ${fs.margin_pct >= 20 ? 'text-success' : fs.margin_pct > 0 ? 'text-warning' : 'text-danger'}`}>
                                            {fs.margin_pct || 0}%
                                        </span>
                                    </div>
                                </div>
                            </div>
                        </div>
                    </div>
                </div>
            )}

            {/* ═══ Task Modal ═══ */}
            <SimpleModal
                isOpen={showTaskModal}
                onClose={() => setShowTaskModal(false)}
                title={t('projects.add_task')}
                footer={
                    <>
                        <button className="btn btn-secondary" onClick={() => setShowTaskModal(false)}>{t('common.cancel')}</button>
                        <button className="btn btn-primary" onClick={handleAddTask} disabled={submitting}>{submitting ? t('common.saving') : t('common.save')}</button>
                    </>
                }
            >
                <div className="mb-3">
                    <label className="form-label">{t('projects.task_fields.name')} *</label>
                    <input type="text" className="form-input" value={taskForm.task_name}
                        onChange={e => setTaskForm({ ...taskForm, task_name: e.target.value })} />
                </div>
                <div className="mb-3">
                    <label className="form-label">{t('projects.task_fields.description')}</label>
                    <textarea className="form-input" rows={2} value={taskForm.description}
                        onChange={e => setTaskForm({ ...taskForm, description: e.target.value })} />
                </div>
                <div className="row g-3">
                    <div className="col-6">
                        <label className="form-label">{t('projects.fields.start_date')}</label>
                        <DateInput className="form-input" value={taskForm.start_date}
                            onChange={e => setTaskForm({ ...taskForm, start_date: e.target.value })} />
                    </div>
                    <div className="col-6">
                        <label className="form-label">{t('projects.fields.end_date')}</label>
                        <DateInput className="form-input" value={taskForm.end_date}
                            onChange={e => setTaskForm({ ...taskForm, end_date: e.target.value })} />
                    </div>
                </div>
                <div className="mt-3">
                    <label className="form-label">{t('projects.task_fields.hours')}</label>
                    <input type="number" className="form-input" value={taskForm.planned_hours}
                        onChange={e => setTaskForm({ ...taskForm, planned_hours: e.target.value })}
                        min="0" step="0.5" placeholder="0" dir="ltr" />
                </div>
            </SimpleModal>

            {/* ═══ Expense Modal ═══ */}
            <SimpleModal
                isOpen={showExpenseModal}
                onClose={() => setShowExpenseModal(false)}
                title={t('projects.add_expense')}
                footer={
                    <>
                        <button className="btn btn-secondary" onClick={() => setShowExpenseModal(false)}>{t('common.cancel')}</button>
                        <button className="btn btn-primary" onClick={handleAddExpense} disabled={submitting}>{submitting ? t('common.saving') : t('projects.confirm_expense')}</button>
                    </>
                }
            >
                <div className="mb-3">
                    <label className="form-label">{t('projects.expense_fields.type')} *</label>
                    <select className="form-input" value={expenseForm.expense_type}
                        onChange={e => setExpenseForm({ ...expenseForm, expense_type: e.target.value })}>
                        <option value="materials">{t('projects.expense_types.materials')}</option>
                        <option value="labor">{t('projects.expense_types.labor')}</option>
                        <option value="services">{t('projects.expense_types.services')}</option>
                        <option value="travel">{t('projects.expense_types.travel')}</option>
                        <option value="other">{t('projects.expense_types.other')}</option>
                    </select>
                </div>
                <div className="row g-3 mb-3">
                    <div className="col-6">
                        <label className="form-label">{t('projects.expense_fields.date')} *</label>
                        <DateInput className="form-input" value={expenseForm.expense_date}
                            onChange={e => setExpenseForm({ ...expenseForm, expense_date: e.target.value })} />
                    </div>
                    <div className="col-6">
                        <label className="form-label">{t('projects.expense_fields.amount')} *</label>
                        <input type="number" className="form-input" value={expenseForm.amount}
                            onChange={e => setExpenseForm({ ...expenseForm, amount: e.target.value })}
                            min="0" step="0.01" placeholder="0.00" dir="ltr" />
                    </div>
                </div>
                <div className="mb-3">
                    <label className="form-label">{t('projects.expense_fields.treasury')}</label>
                    <select className="form-input" value={expenseForm.treasury_id}
                        onChange={e => setExpenseForm({ ...expenseForm, treasury_id: e.target.value })}>
                        <option value="">{t('projects.fields.default_cash')}</option>
                        {treasuryAccounts.map(ta => (
                            <option key={ta.id} value={ta.id}>{ta.name} ({formatNumber(ta.current_balance)})</option>
                        ))}
                    </select>
                </div>
                <div className="mb-3">
                    <label className="form-label">{t('projects.expense_fields.description')}</label>
                    <textarea className="form-input" rows={2} value={expenseForm.description}
                        onChange={e => setExpenseForm({ ...expenseForm, description: e.target.value })} />
                </div>
                <div className="alert alert-info small">
                    💡 {t('projects.expense_note')}
                </div>
            </SimpleModal>

            {/* ═══ Revenue Modal ═══ */}
            <SimpleModal
                isOpen={showRevenueModal}
                onClose={() => setShowRevenueModal(false)}
                title={t('projects.add_revenue')}
                footer={
                    <>
                        <button className="btn btn-secondary" onClick={() => setShowRevenueModal(false)}>{t('common.cancel')}</button>
                        <button className="btn btn-primary" onClick={handleAddRevenue} disabled={submitting}>{submitting ? t('common.saving') : t('projects.confirm_revenue')}</button>
                    </>
                }
            >
                <div className="mb-3">
                    <label className="form-label">{t('projects.revenue_fields.type')} *</label>
                    <select className="form-input" value={revenueForm.revenue_type}
                        onChange={e => setRevenueForm({ ...revenueForm, revenue_type: e.target.value })}>
                        <option value="milestone">{t('projects.revenue_types.milestone')}</option>
                        <option value="invoice">{t('projects.revenue_types.invoice')}</option>
                        <option value="advance">{t('projects.revenue_types.advance')}</option>
                        <option value="other">{t('projects.revenue_types.other')}</option>
                    </select>
                </div>
                <div className="row g-3 mb-3">
                    <div className="col-6">
                        <label className="form-label">{t('projects.revenue_fields.date')} *</label>
                        <DateInput className="form-input" value={revenueForm.revenue_date}
                            onChange={e => setRevenueForm({ ...revenueForm, revenue_date: e.target.value })} />
                    </div>
                    <div className="col-6">
                        <label className="form-label">{t('projects.revenue_fields.amount')} *</label>
                        <input type="number" className="form-input" value={revenueForm.amount}
                            onChange={e => setRevenueForm({ ...revenueForm, amount: e.target.value })}
                            min="0" step="0.01" placeholder="0.00" dir="ltr" />
                    </div>
                </div>
                <div className="mb-3">
                    <label className="form-label">{t('projects.revenue_fields.description')}</label>
                    <textarea className="form-input" rows={2} value={revenueForm.description}
                        onChange={e => setRevenueForm({ ...revenueForm, description: e.target.value })} />
                </div>
                <div className="alert alert-info small">
                    💡 {t('projects.revenue_note')}
                </div>
            </SimpleModal>

            {/* ═══ Invoice Modal ═══ */}
            <SimpleModal
                isOpen={showInvoiceModal}
                onClose={() => setShowInvoiceModal(false)}
                title={t('projects.create_invoice')}
                footer={
                    <>
                        <button className="btn btn-secondary" onClick={() => setShowInvoiceModal(false)}>{t('common.cancel')}</button>
                        <button className="btn btn-primary" onClick={handleCreateInvoice} disabled={submitting}>{submitting ? t('common.saving') : t('common.create')}</button>
                    </>
                }
            >
                <div className="row g-3 mb-3">
                    <div className="col-6">
                        <label className="form-label">{t('common.date')} *</label>
                        <DateInput className="form-input" value={invoiceForm.invoice_date}
                            onChange={e => setInvoiceForm({ ...invoiceForm, invoice_date: e.target.value })} />
                    </div>
                    <div className="col-6">
                        <label className="form-label">{t('common.due_date')} *</label>
                        <DateInput className="form-input" value={invoiceForm.due_date}
                            onChange={e => setInvoiceForm({ ...invoiceForm, due_date: e.target.value })} />
                    </div>
                </div>
                <div className="mb-3">
                    <label className="form-label">{t('common.description')} *</label>
                    <input type="text" className="form-input" value={invoiceForm.description}
                        onChange={e => setInvoiceForm({ ...invoiceForm, description: e.target.value })} />
                </div>
                <div className="mb-3">
                    <label className="form-label">{t('common.amount')} *</label>
                    <input type="number" className="form-input" value={invoiceForm.amount}
                        onChange={e => setInvoiceForm({ ...invoiceForm, amount: e.target.value })}
                        min="0" step="0.01" placeholder="0.00" dir="ltr" />
                </div>
                <div className="mb-3">
                    <label className="form-label">{t('common.notes')}</label>
                    <textarea className="form-input" rows={2} value={invoiceForm.notes}
                        onChange={e => setInvoiceForm({ ...invoiceForm, notes: e.target.value })} />
                </div>
                <div className="alert alert-info small">
                    💡 {t('projects.invoice_note')}
                </div>
            </SimpleModal>

            {/* ═══ Delete Confirm ═══ */}
            <SimpleModal
                isOpen={showDeleteConfirm}
                onClose={() => setShowDeleteConfirm(false)}
                title={t('projects.confirm_delete')}
                footer={
                    <>
                        <button className="btn btn-secondary" onClick={() => setShowDeleteConfirm(false)}>{t('common.cancel')}</button>
                        <button className="btn btn-danger" onClick={handleDelete}>{t('common.delete')}</button>
                    </>
                }
            >
                <p>{t('projects.delete_warning')}</p>
            </SimpleModal>
        </div>
    );
}
