import { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { purchasesAPI } from '../../utils/api';
import { getCurrency } from '../../utils/auth';
import { useBranch } from '../../context/BranchContext';
import { useToast } from '../../context/ToastContext';
import { formatShortDate } from '../../utils/dateUtils';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'


function SupplierPayments() {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const { currentBranch } = useBranch();
    const { showToast } = useToast();
    const currency = getCurrency();
    const [payments, setPayments] = useState([]);
    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);
    const [search, setSearch] = useState('');

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchPayments()
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch]);

    const fetchPayments = async () => {
        try {
            const res = await purchasesAPI.listPayments({ branch_id: currentBranch?.id });
            setPayments(res.data);
        } catch (error) {
            showToast(t('buying.payments.error_loading'), 'error');
        } finally {
            setLoading(false);
            setInitialLoad(false);
        }
    };

    const filteredPayments = payments.filter(p =>
        p.voucher_number.toLowerCase().includes(search.toLowerCase()) ||
        (p.supplier_name && p.supplier_name.toLowerCase().includes(search.toLowerCase()))
    );

    if (initialLoad && loading) return <PageLoading />;

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                        <h1 className="workspace-title">{t('buying.payments.title')}</h1>
                        <p className="workspace-subtitle">{t('buying.payments.subtitle')}</p>
                    </div>
                    <button className="btn btn-primary bg-purple-600 hover:bg-purple-700" onClick={() => navigate('/buying/payments/new')}>
                        + {t('buying.payments.create_new')}
                    </button>
                </div>
            </div>

            <div className="mb-4">
                <input
                    type="text"
                    placeholder={t('buying.payments.search_placeholder')}
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    className="form-input w-full max-w-md"
                />
            </div>

            <div className="data-table-container">
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>{t('buying.payments.table.voucher_number')}</th>
                            <th>{t('buying.payments.table.date')}</th>
                            <th>{t('buying.payments.table.supplier')}</th>
                            <th>{t('buying.payments.table.amount')}</th>
                            <th>{t('buying.payments.table.payment_method')}</th>
                            <th>{t('buying.payments.table.status')}</th>
                            <th>{t('buying.payments.table.actions')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {filteredPayments.length === 0 ? (
                            <tr>
                                <td colSpan="7" className="px-6 py-8 text-center text-muted">
                                    {t('buying.payments.no_payments')}
                                </td>
                            </tr>
                        ) : (
                            filteredPayments.map((payment) => (
                                <tr key={payment.id} onClick={() => navigate(`/buying/payments/${payment.id}`)} style={{ cursor: 'pointer' }}>
                                    <td className="font-medium text-purple-700">{payment.voucher_number}</td>
                                    <td>{formatShortDate(payment.voucher_date)}</td>
                                    <td>{payment.supplier_name}</td>
                                    <td className="font-bold">{Number(payment.amount).toLocaleString()} {currency}</td>
                                    <td>
                                        {payment.payment_method === 'cash' ? t('buying.payments.form.payment_methods.cash') : payment.payment_method === 'bank' ? t('buying.payments.form.payment_methods.bank') : t('buying.payments.form.payment_methods.check')}
                                    </td>
                                    <td>
                                        <span className={`badge ${payment.status === 'posted' ? 'badge-success' : 'badge-secondary'}`}>
                                            {payment.status === 'posted' ? t('buying.payments.status.posted') : t('buying.payments.status.draft')}
                                        </span>
                                    </td>
                                    <td>
                                        <button className="btn btn-secondary btn-sm" onClick={(e) => {
                                            e.stopPropagation();
                                            navigate(`/buying/payments/${payment.id}`);
                                        }}>{t('common.actions')}</button>
                                    </td>
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            </div>
        </div>
    );
}

export default SupplierPayments;
