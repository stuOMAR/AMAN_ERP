import { useState, useEffect } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import api, { expensesAPI } from '../../utils/api';
import { useToast } from '../../context/ToastContext';
import { Save, FileText, CreditCard, FolderOpen } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { getCurrency } from '../../utils/auth';
import CustomDatePicker from '../../components/common/CustomDatePicker';
import BackButton from '../../components/common/BackButton';
import FormField from '../../components/common/FormField';
import { PageLoading, Spinner } from '../../components/common/LoadingStates'
import { useBranch } from '../../context/BranchContext';

export default function ExpenseForm() {
  const { t } = useTranslation();
  const { id } = useParams();
  const navigate = useNavigate();
  const { showToast } = useToast();
  const { currentBranch } = useBranch();
  const isEdit = Boolean(id);
  const currency = getCurrency() || '';

  const [loading, setLoading] = useState(false);
  const [initialLoad, setInitialLoad] = useState(true);
  const [treasuries, setTreasuries] = useState([]);
  const [accounts, setAccounts] = useState([]);
  const [costCenters, setCostCenters] = useState([]);
  const [projects, setProjects] = useState([]);

  const [formData, setFormData] = useState({
    expense_date: new Date().toISOString().split('T')[0],
    expense_type: 'other',
    amount: '',
    description: '',
    category: 'general',
    payment_method: 'cash',
    treasury_id: '',
    expense_account_id: '',
    cost_center_id: '',
    project_id: '',
    requires_approval: true,
    receipt_number: '',
    vendor_name: ''
  });

  useEffect(() => {
    const timer = setTimeout(() => {
      loadOptions();
      if (isEdit) {
        loadExpense();
      } else {
        setInitialLoad(false);
      }
    }, 300)
    return () => clearTimeout(timer)
  }, [id, currentBranch?.id]);

  const loadOptions = async () => {
    try {
      const [treasuriesRes, accountsRes, costCentersRes, projectsRes] = await Promise.all([
        api.get('/treasury/accounts', { params: { branch_id: currentBranch?.id } }),
        api.get('/accounting/accounts', { params: { account_type: 'expense' } }),
        api.get('/cost-centers/'),
        api.get('/projects/', { params: { status: 'in_progress' } })
      ]);

      setTreasuries(treasuriesRes.data);
      setAccounts(accountsRes.data);
      setCostCenters(costCentersRes.data);
      setProjects(projectsRes.data);
    } catch (error) {
      showToast(t('expenses.errors.loadOptionsFailed'), 'error');
    }
  };

  const loadExpense = async () => {
    try {
      setLoading(true);
      const res = await expensesAPI.get(id);
      const data = res.data;
      setFormData({
        expense_date: data.expense_date,
        expense_type: data.expense_type,
        amount: data.amount,
        description: data.description || '',
        category: data.category || 'general',
        payment_method: data.payment_method,
        treasury_id: data.treasury_id || '',
        expense_account_id: data.expense_account_id || '',
        cost_center_id: data.cost_center_id || '',
        project_id: data.project_id || '',
        receipt_number: data.receipt_number || '',
        vendor_name: data.vendor_name || '',
        requires_approval: data.requires_approval ?? true
      });
    } catch (error) {
      showToast(t('expenses.errors.loadFailed'), 'error');
      navigate('/expenses');
    } finally {
      setLoading(false);
      setInitialLoad(false);
    }
  };

  const handleSubmit = async (e) => {
    e.preventDefault();

    if (!formData.amount || formData.amount <= 0) {
      showToast(t('expenses.errors.invalidAmount'), 'error');
      return;
    }

    try {
      setLoading(true);
      
      const payload = {
        ...formData,
        amount: formData.amount,
        treasury_id: formData.treasury_id ? parseInt(formData.treasury_id) : null,
        expense_account_id: formData.expense_account_id ? parseInt(formData.expense_account_id) : null,
        cost_center_id: formData.cost_center_id ? parseInt(formData.cost_center_id) : null,
        project_id: formData.project_id ? parseInt(formData.project_id) : null
      };

      if (isEdit) {
        await expensesAPI.update(id, payload);
        showToast(t('expenses.messages.updated'), 'success');
      } else {
        await expensesAPI.create(payload);
        showToast(t('expenses.messages.created'), 'success');
      }

      navigate('/expenses');
    } catch (error) {
      const message = error.response?.data?.detail || t('expenses.errors.saveFailed');
      showToast(message, 'error');
    } finally {
      setLoading(false);
    }
  };

  const handleChange = (e) => {
    const { name, value, type, checked } = e.target;
    setFormData(prev => ({
      ...prev,
      [name]: type === 'checkbox' ? checked : value
    }));
  };

  if (initialLoad && loading && isEdit) {
    return (
      <div className="workspace fade-in">
        <PageLoading />
      </div>
    );
  }

  return (
    <div className="workspace fade-in">
      {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
      {/* Header */}
      <div className="workspace-header">
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
                        <BackButton />
            <div>
              <h1 className="workspace-title">
                {isEdit ? t('expenses.editTitle') : t('expenses.newTitle')}
              </h1>
              <p className="text-muted small mb-0">{t('expenses.formSubtitle')}</p>
            </div>
          </div>
          <button
            className="btn btn-outline-secondary d-flex align-items-center gap-2"
            onClick={() => navigate('/expenses')}
          >
            {t('common.cancel')}
          </button>
        </div>
      </div>

      <form onSubmit={handleSubmit}>
        {/* Basic Information */}
        <div className="card mb-4">
          <div >
            <div className="d-flex align-items-center gap-2 mb-3">
              <div style={{ background: '#eff6ff', width: '32px', height: '32px', borderRadius: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <FileText size={18} color="#3b82f6" />
              </div>
              <h5 className="mb-0 fw-semibold">{t('expenses.sections.basic')}</h5>
            </div>

          <div className="form-row">
            <div className="form-group" style={{ flex: 1 }}>
              <CustomDatePicker
                label={t('expenses.fields.date')}
                selected={formData.expense_date}
                onChange={(val) => setFormData(prev => ({ ...prev, expense_date: val }))}
                required
                placeholder="YYYY/MM/DD"
              />
            </div>

            <FormField label={t('expenses.fields.type')} required style={{ flex: 1 }}>
              <select
                name="expense_type"
                className="form-input"
                value={formData.expense_type}
                onChange={handleChange}
                required
              >
                <option value="travel">{t('expenses.types.travel')}</option>
                <option value="meals">{t('expenses.types.meals')}</option>
                <option value="supplies">{t('expenses.types.supplies')}</option>
                <option value="transportation">{t('expenses.types.transportation')}</option>
                <option value="entertainment">{t('expenses.types.entertainment')}</option>
                <option value="materials">{t('expenses.types.materials')}</option>
                <option value="labor">{t('expenses.types.labor')}</option>
                <option value="services">{t('expenses.types.services')}</option>
                <option value="rent">{t('expenses.types.rent')}</option>
                <option value="utilities">{t('expenses.types.utilities')}</option>
                <option value="salaries">{t('expenses.types.salaries')}</option>
                <option value="other">{t('expenses.types.other')}</option>
              </select>
            </FormField>
          </div>

          <div className="form-row">
            <FormField label={t('expenses.fields.amount')} required style={{ flex: 1 }}>
              <input
                type="number"
                name="amount"
                className="form-input"
                value={formData.amount}
                onChange={handleChange}
                step="0.01"
                min="0"
                placeholder={`0.00 ${currency}`}
                required
              />
            </FormField>

            <FormField label={t('expenses.fields.vendor')} style={{ flex: 1 }}>
              <input
                type="text"
                name="vendor_name"
                className="form-input"
                value={formData.vendor_name}
                onChange={handleChange}
                placeholder={t('expenses.placeholders.vendor')}
              />
            </FormField>
          </div>

          <FormField label={t('expenses.fields.description')}>
            <textarea
              name="description"
              className="form-input"
              rows="3"
              value={formData.description}
              onChange={handleChange}
              placeholder={t('expenses.placeholders.description')}
            />
          </FormField>
          </div>
        </div>

        {/* Payment & Accounting */}
        <div className="card mb-4">
          <div >
            <div className="d-flex align-items-center gap-2 mb-3">
              <div style={{ background: '#dcfce7', width: '32px', height: '32px', borderRadius: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <CreditCard size={18} color="#16a34a" />
              </div>
              <h5 className="mb-0 fw-semibold">{t('expenses.sections.payment')}</h5>
            </div>

          <div className="form-row">
            <FormField label={t('expenses.fields.paymentMethod')} style={{ flex: 1 }}>
              <select
                name="payment_method"
                className="form-input"
                value={formData.payment_method}
                onChange={handleChange}
              >
                <option value="cash">{t('expenses.payment.cash')}</option>
                <option value="bank">{t('expenses.payment.bank')}</option>
                <option value="credit_card">{t('expenses.payment.creditCard')}</option>
              </select>
            </FormField>

            <FormField label={t('expenses.fields.treasury')} style={{ flex: 1 }}>
              <select
                name="treasury_id"
                className="form-input"
                value={formData.treasury_id}
                onChange={handleChange}
              >
                <option value="">{t('common.select')}</option>
                {treasuries
                  .filter(tr => !formData.payment_method || formData.payment_method === 'credit_card' || tr.account_type === (formData.payment_method === 'bank' ? 'bank' : 'cash'))
                  .map(tr => (
                  <option key={tr.id} value={tr.id}>{tr.name}</option>
                ))}
              </select>
            </FormField>
          </div>

          <div className="form-row">
            <FormField label={t('expenses.fields.account')} hint={t('expenses.help.autoAccount')} style={{ flex: 1 }}>
              <select
                name="expense_account_id"
                className="form-input"
                value={formData.expense_account_id}
                onChange={handleChange}
              >
                <option value="">{t('common.auto')}</option>
                {accounts.map(acc => (
                  <option key={acc.id} value={acc.id}>
                    {acc.account_number} - {acc.name}
                  </option>
                ))}
              </select>
            </FormField>

            <FormField label={t('expenses.fields.receiptNumber')} style={{ flex: 1 }}>
              <input
                type="text"
                name="receipt_number"
                className="form-input"
                value={formData.receipt_number}
                onChange={handleChange}
                placeholder={t('expenses.placeholders.receipt')}
              />
            </FormField>
          </div>
          </div>
        </div>

        {/* Organization */}
        <div className="card mb-4">
          <div >
            <div className="d-flex align-items-center gap-2 mb-3">
              <div style={{ background: '#e0f2fe', width: '32px', height: '32px', borderRadius: '8px', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>
                <FolderOpen size={18} color="#0284c7" />
              </div>
              <h5 className="mb-0 fw-semibold">{t('expenses.sections.organization')}</h5>
            </div>

          <div className="form-row">
            <FormField label={t('expenses.fields.costCenter')} style={{ flex: 1 }}>
              <select
                name="cost_center_id"
                className="form-input"
                value={formData.cost_center_id}
                onChange={handleChange}
              >
                <option value="">{t('common.select')}</option>
                {costCenters.map(cc => (
                  <option key={cc.id} value={cc.id}>{cc.center_name}</option>
                ))}
              </select>
            </FormField>

            <FormField label={t('expenses.fields.project')} style={{ flex: 1 }}>
              <select
                name="project_id"
                className="form-input"
                value={formData.project_id}
                onChange={handleChange}
              >
                <option value="">{t('common.select')}</option>
                {projects.map(p => (
                  <option key={p.id} value={p.id}>
                    {p.project_code} - {p.project_name}
                  </option>
                ))}
              </select>
            </FormField>
          </div>

          <div className="form-row">
            <FormField label={t('expenses.fields.category')} style={{ flex: 1 }}>
              <input
                type="text"
                name="category"
                className="form-input"
                value={formData.category}
                onChange={handleChange}
              />
            </FormField>

            {!isEdit && (
              <div className="form-group" style={{ flex: 1, display: 'flex', alignItems: 'center', paddingTop: '24px' }}>
                <input
                  type="checkbox"
                  name="requires_approval"
                  className="form-check-input"
                  id="requiresApproval"
                  checked={formData.requires_approval}
                  onChange={handleChange}
                  style={{ marginInlineEnd: '8px' }}
                />
                <label className="form-check-label" htmlFor="requiresApproval">
                  {t('expenses.fields.requiresApproval')}
                </label>
              </div>
            )}
          </div>
          </div>
        </div>

        {/* Actions */}
        <div className="card">
          <div className="d-flex justify-content-end gap-2">
            <button
              type="button"
              className="btn btn-outline-secondary"
              onClick={() => navigate('/expenses')}
              disabled={loading}
            >
              {t('common.cancel')}
            </button>
            <button
              type="submit"
              className="btn btn-primary d-flex align-items-center gap-2"
              disabled={loading}
            >
              {loading ? (
                <>
                  <Spinner size="sm"/>
                  {t('common.saving')}
                </>
              ) : (
                <>
                  <Save size={18} />
                  {t('common.save')}
                </>
              )}
            </button>
          </div>
        </div>
      </form>
    </div>
  );
}
