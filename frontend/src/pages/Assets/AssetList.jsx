import React, { useState, useEffect, useMemo } from 'react';
import { useTranslation } from 'react-i18next';
import { useNavigate } from 'react-router-dom';
import { Plus } from 'lucide-react';
import Decimal from 'decimal.js';
import { assetsAPI } from '../../utils/api';
import { getCurrency } from '../../utils/auth';
import { formatNumber } from '../../utils/format';
import { useBranch } from '../../context/BranchContext';
import BackButton from '../../components/common/BackButton';
import DataTable from '../../components/common/DataTable';
import SearchFilter from '../../components/common/SearchFilter';
import { formatShortDate } from '../../utils/dateUtils';

const AssetList = () => {
    const { t, i18n } = useTranslation();
    const navigate = useNavigate();
    const currency = getCurrency();
    const { currentBranch } = useBranch();
    const [assets, setAssets] = useState([]);
    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);
    const [filter, setFilter] = useState('');
    const [search, setSearch] = useState('');

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchAssets()
        }, 300)
        return () => clearTimeout(timer)
    }, [filter, currentBranch]);

    const fetchAssets = async () => {
        try {
            setLoading(true);
            const params = filter ? { status: filter } : {};
            if (currentBranch?.id) params.branch_id = currentBranch.id;
            const response = await assetsAPI.list(params);
            setAssets(response.data);
        } catch (error) {
            console.error("Failed to fetch assets", error);
        } finally {
            setLoading(false);
            setInitialLoad(false);
        }
    };

    const filteredAssets = useMemo(() => {
        if (!search) return assets;
        const q = search.toLowerCase();
        return assets.filter(a =>
            (a.code || '').toLowerCase().includes(q) ||
            (a.name || '').toLowerCase().includes(q)
        );
    }, [assets, search]);

    const columns = [
        {
            key: 'code',
            label: t('assets.code', 'Code'),
            render: (val) => <span className="badge rounded-pill bg-light text-dark border px-3">{val}</span>,
        },
        {
            key: 'name',
            label: t('assets.name', 'Name'),
            style: { fontWeight: 600, color: 'var(--text-dark)' },
        },
        {
            key: 'type',
            label: t('assets.type', 'Type'),
            render: (val) => (
                <span className="text-muted d-flex align-items-center gap-2">
                    <div style={{ width: 8, height: 8, borderRadius: '50%', backgroundColor: val === 'tangible' ? 'var(--primary)' : 'var(--warning)' }}></div>
                    {t(`assets.types.${val}`, val)}
                </span>
            ),
        },
        {
            key: 'purchase_date',
            label: t('assets.purchase_date', 'Purchase Date'),
            headerStyle: { textAlign: 'center' },
            style: { textAlign: 'center' },
            render: (val) => <span className="text-muted small">{formatShortDate(val)}</span>,
        },
        {
            key: 'cost',
            label: t('assets.cost', 'Cost'),
            headerStyle: { textAlign: 'end' },
            style: { textAlign: 'end', fontWeight: 'bold', color: 'var(--text-dark)' },
            render: (val, row) => <>{formatNumber(val)} {row.currency || currency}</>,
        },
        {
            key: 'status',
            label: t('common.status.title', 'Status'),
            headerStyle: { textAlign: 'center' },
            style: { textAlign: 'center' },
            render: (val) => (
                <span className={`badge ${val === 'active' ? 'bg-success-subtle text-success' : 'bg-secondary-subtle text-secondary'} border px-3`}>
                    {t(`status.${val}`, val)}
                </span>
            ),
        },
    ];

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div className="d-flex align-items-center justify-content-between w-100">
                    <div>
                        <h1 className="workspace-title">{t('assets.title', 'Fixed Assets')}</h1>
                        <p className="workspace-subtitle">{t('assets.subtitle', 'Manage company assets and depreciation')}</p>
                    </div>
                    <div className="header-actions" style={{ display: 'flex', gap: '8px', flexWrap: 'wrap' }}>
                        <button className="btn btn-outline-primary shadow-sm" onClick={() => navigate('/assets/reports')}>
                            📊 {i18n.t('common.reports')}
                        </button>
                        <button className="btn btn-secondary shadow-sm" onClick={() => navigate('/assets/management')}>
                            {i18n.t('asset.transfers_reval')}
                        </button>
                        <button className="btn btn-outline-secondary shadow-sm" onClick={() => navigate('/assets/leases')}>
                            📄 {i18n.t('reports.leases')}
                        </button>
                        <button className="btn btn-outline-secondary shadow-sm" onClick={() => navigate('/assets/impairment')}>
                            🔍 {i18n.t('accounting.impairment')}
                        </button>
                        <button className="btn btn-primary shadow-sm" onClick={() => navigate('/assets/new')}>
                            <Plus size={18} className={t('common.is_rtl') === 'true' ? 'ms-2' : 'me-2'} />
                            {t('assets.new', 'New Asset')}
                        </button>
                    </div>
                </div>
            </div>

            <div className="metrics-grid mb-4">
                <div className="metric-card">
                    <div className="metric-label">{t('assets.total_value', 'Total Asset Value')}</div>
                    <div className="metric-value text-primary">
                        {formatNumber(assets.reduce((sum, a) => sum.plus(new Decimal(a.cost || '0')), new Decimal('0')).toString())} <small>{currency}</small>
                    </div>
                </div>
                <div className="metric-card">
                    <div className="metric-label">{t('assets.active_count', 'Active Assets')}</div>
                    <div className="metric-value text-success">
                        {assets.filter(a => a.status === 'active').length}
                    </div>
                </div>
            </div>

            <SearchFilter
                value={search}
                onChange={setSearch}
                placeholder={t('common.search')}
                filters={[{
                    key: 'status',
                    label: t('common.status.title', 'Status'),
                    options: [
                        { value: 'active', label: t('status.active') },
                        { value: 'disposed', label: t('status.disposed') },
                    ],
                }]}
                filterValues={{ status: filter }}
                onFilterChange={(key, val) => setFilter(val)}
            />

            <DataTable
                columns={columns}
                data={filteredAssets}
                loading={loading}
                onRowClick={(row) => navigate(`/assets/${row.id}`)}
                emptyTitle={t('common.no_data')}
                emptyAction={{ label: t('assets.new', 'New Asset'), onClick: () => navigate('/assets/new') }}
            />
        </div>
    );
};

export default AssetList;
