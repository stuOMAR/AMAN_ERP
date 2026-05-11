import React, { useState, useEffect } from 'react';
import { useNavigate, Link } from 'react-router-dom';
import { salesAPI } from '../../utils/api';
import { getCurrency } from '../../utils/auth';
import { useTranslation } from 'react-i18next';
import { formatShortDate } from '../../utils/dateUtils';
import { useBranch } from '../../context/BranchContext';
import { useToast } from '../../context/ToastContext';
import BackButton from '../../components/common/BackButton';
import { formatNumber } from '../../utils/format';
import { PageLoading } from '../../components/common/LoadingStates'

const SalesReturns = () => {
    const { t } = useTranslation();
    const { showToast } = useToast();
    const navigate = useNavigate();
    const { currentBranch } = useBranch();
    const currency = getCurrency();
    const [returns, setReturns] = useState([]);
    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchReturns();
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch]);

    const fetchReturns = async () => {
        try {
            const response = await salesAPI.listReturns({ branch_id: currentBranch?.id });
            setReturns(response.data);
        } catch (error) {
            showToast(t('common.error'), 'error');
        } finally {
            setLoading(false);
            setInitialLoad(false);
        }
    };

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">↩️ {t('sales.returns.title')}</h1>
                    <p className="workspace-subtitle">{t('sales.returns.subtitle')}</p>
                </div>
                <div className="header-actions">
                    <Link to="/sales/returns/new" className="btn btn-primary">
                        + {t('sales.returns.create_new')}
                    </Link>
                    <Link to="/sales" className="btn btn-secondary">
                        {t('sales.returns.back')}
                    </Link>
                </div>
            </div>

            <div className="card">
                <table className="data-table">
                    <thead>
                        <tr>
                            <th>{t('sales.returns.table.number')}</th>
                            <th>{t('sales.returns.table.customer')}</th>
                            <th>{t('sales.returns.table.date')}</th>
                            <th>{t('sales.returns.table.total')}</th>
                            <th>{t('sales.returns.table.status')}</th>
                            <th>{t('sales.returns.table.actions')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {loading ? (
                            <tr>
                                <td colSpan="6" className="text-center py-8 text-muted"><PageLoading /></td>
                            </tr>
                        ) : returns.length === 0 ? (
                            <tr>
                                <td colSpan="6" className="text-center py-8 text-muted">{t('sales.returns.empty')}</td>
                            </tr>
                        ) : (
                            returns.map((ret) => (
                                <tr key={ret.id}>
                                    <td className="font-medium text-primary">{ret.return_number}</td>
                                    <td>{ret.customer_name}</td>
                                    <td>{formatShortDate(ret.return_date)}</td>
                                    <td className="font-bold">
                                        {formatNumber(ret.total)} <small>{currency}</small>
                                    </td>
                                    <td>
                                        <span className={`status-badge ${ret.status}`}>
                                            {ret.status === 'approved' ? t('sales.returns.status.approved') :
                                                ret.status === 'draft' ? t('sales.returns.status.draft') :
                                                    ret.status === 'cancelled' ? t('sales.returns.status.cancelled') : ret.status}
                                        </span>
                                    </td>
                                    <td>
                                        <button
                                            onClick={() => navigate(`/sales/returns/${ret.id}`)}
                                            className="btn-icon"
                                            title={t('sales.returns.table.actions')}
                                        >
                                            👁️
                                        </button>
                                    </td>
                                </tr>
                            ))
                        )}
                    </tbody>
                </table>
            </div>
        </div>
    );
};

export default SalesReturns;
