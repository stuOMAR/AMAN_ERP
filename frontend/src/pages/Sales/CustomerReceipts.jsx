import { useState, useEffect } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { salesAPI } from '../../utils/api';
import { getCurrency } from '../../utils/auth';
import { useTranslation } from 'react-i18next';
import { useBranch } from '../../context/BranchContext';
import { useToast } from '../../context/ToastContext';
import { formatShortDate } from '../../utils/dateUtils';
import BackButton from '../../components/common/BackButton';
import { formatNumber } from '../../utils/format';
import { PageLoading } from '../../components/common/LoadingStates'


function CustomerReceipts() {
    const { t } = useTranslation();
    const { showToast } = useToast();
    const navigate = useNavigate();
    const location = useLocation();
    const { currentBranch } = useBranch();
    const currency = getCurrency();
    const isPaymentsRoute = location.pathname.includes('/sales/payments');
    const [vouchers, setVouchers] = useState([]);
    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);
    const [search, setSearch] = useState('');

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchVouchers();
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch, isPaymentsRoute]);

    const fetchVouchers = async () => {
        try {
            setLoading(true);
            const response = isPaymentsRoute
                ? await salesAPI.listPayments({ branch_id: currentBranch?.id })
                : await salesAPI.listReceipts({ branch_id: currentBranch?.id });
            const voucherType = isPaymentsRoute ? 'refund' : 'receipt';
            const unified = response.data
                .map(voucher => ({ ...voucher, type: voucherType }))
                .sort((a, b) => new Date(b.voucher_date) - new Date(a.voucher_date));

            setVouchers(unified);
        } catch (error) {
            showToast(t('sales.receipts.form.errors.fetch_failed'), 'error');
        } finally {
            setLoading(false);
            setInitialLoad(false);
        }
    };

    const filteredVouchers = vouchers.filter(v =>
        v.voucher_number.toLowerCase().includes(search.toLowerCase()) ||
        (v.customer_name && v.customer_name.toLowerCase().includes(search.toLowerCase()))
    );

    if (initialLoad) return <PageLoading />;

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                        <h1 className="workspace-title">{isPaymentsRoute ? t('sales.payments.title') : t('sales.receipts.title')}</h1>
                        <p className="workspace-subtitle">{isPaymentsRoute ? t('sales.payments.subtitle') : t('sales.receipts.subtitle')}</p>
                    </div>
                    <button className="btn btn-primary" onClick={() => navigate(isPaymentsRoute ? '/sales/payments/new' : '/sales/receipts/new')}>
                        + {isPaymentsRoute ? t('sales.payments.create_new') : t('sales.receipts.create_new')}
                    </button>
                </div>
            </div>

            <div className="mb-4">
                <input
                    type="text"
                    placeholder={isPaymentsRoute ? t('sales.payments.search_placeholder') : t('sales.receipts.search_placeholder')}
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    className="form-input w-full max-w-md"
                />
            </div>

            <div className="data-table-container">
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>{t('sales.receipts.table.voucher_number')}</th>
                            <th>{t('sales.receipts.table.type')}</th>
                            <th>{t('sales.receipts.table.date')}</th>
                            <th>{t('sales.receipts.table.customer')}</th>
                            <th>{t('sales.receipts.table.amount')}</th>
                            <th>{t('sales.receipts.table.payment_method')}</th>
                            <th>{t('sales.receipts.table.status')}</th>
                            <th>{t('sales.receipts.table.actions')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {filteredVouchers.length === 0 ? (
                            <tr>
                                <td colSpan="8" className="px-6 py-8 text-center text-muted">
                                    {isPaymentsRoute ? t('sales.payments.empty') : t('sales.receipts.empty')}
                                </td>
                            </tr>
                        ) : (
                            filteredVouchers.map((voucher) => (
                                <tr key={`${voucher.type}-${voucher.id}`} onClick={() => navigate(`/sales/${voucher.type === 'receipt' ? 'receipts' : 'payments'}/${voucher.id}`)} style={{ cursor: 'pointer' }}>
                                    <td className="font-medium text-primary">{voucher.voucher_number}</td>
                                    <td>
                                        <span className={`badge ${voucher.type === 'receipt' ? 'badge-success' : 'badge-danger'}`} style={{ opacity: 0.8 }}>
                                            {voucher.type === 'receipt' ? t('sales.receipts.form.type_receipt') : t('sales.payments.form.type_refund')}
                                        </span>
                                    </td>
                                    <td>{formatShortDate(voucher.voucher_date)}</td>
                                    <td>{voucher.customer_name}</td>
                                    <td className="font-bold">{formatNumber(voucher.amount)} {currency}</td>
                                    <td>
                                        {voucher.payment_method === 'cash' ? t('sales.receipts.payment_methods.cash') :
                                            voucher.payment_method === 'bank' ? t('sales.receipts.payment_methods.bank') :
                                                t('sales.receipts.payment_methods.check')}
                                    </td>
                                    <td>
                                        <span className={`badge ${voucher.status === 'posted' ? 'badge-success' : 'badge-secondary'}`}>
                                            {voucher.status === 'posted' ? t('sales.receipts.status.posted') : t('sales.receipts.status.draft')}
                                        </span>
                                    </td>
                                    <td>
                                        <button className="btn btn-secondary btn-sm" onClick={(e) => {
                                            e.stopPropagation();
                                            navigate(`/sales/${voucher.type === 'receipt' ? 'receipts' : 'payments'}/${voucher.id}`);
                                        }}>{t('sales.orders.table.actions')}</button>
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

export default CustomerReceipts;
