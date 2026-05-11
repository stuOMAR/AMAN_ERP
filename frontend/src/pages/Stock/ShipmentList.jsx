import { useState, useEffect, useMemo } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { inventoryAPI } from '../../utils/api';
import { useBranch } from '../../context/BranchContext';
import { useToast } from '../../context/ToastContext';
import { formatShortDate } from '../../utils/dateUtils';
import BackButton from '../../components/common/BackButton';
import DataTable from '../../components/common/DataTable';
import SearchFilter from '../../components/common/SearchFilter';


const ShipmentList = () => {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const { currentBranch } = useBranch();
    const { showToast } = useToast();
    const [shipments, setShipments] = useState([]);
    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);
    const [search, setSearch] = useState('');
    const [statusFilter, setStatusFilter] = useState('');

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchShipments();
        }, 300)
        return () => clearTimeout(timer)
    }, [statusFilter, currentBranch]);

    const fetchShipments = async () => {
        try {
            setLoading(true);
            const res = await inventoryAPI.listShipments({ status_filter: statusFilter || undefined, branch_id: currentBranch?.id });
            setShipments(res.data);
        } catch (err) {
            showToast(t('stock.shipments.validation.error_load'), 'error');
        } finally {
            setLoading(false);
            setInitialLoad(false);
        }
    };

    const getStatusBadge = (status) => {
        const styles = {
            pending: { bg: '#FEF3C7', color: '#D97706', label: t('stock.shipments.status.pending') },
            dispatched: { bg: '#DBEAFE', color: '#2563EB', label: t('stock.shipments.status.dispatched', 'تم الشحن') },
            received: { bg: '#D1FAE5', color: '#059669', label: t('stock.shipments.status.received') },
            cancelled: { bg: '#FEE2E2', color: '#DC2626', label: t('stock.shipments.status.cancelled') }
        };
        const s = styles[status] || styles.pending;
        return (
            <span style={{
                background: s.bg,
                color: s.color,
                padding: '4px 12px',
                borderRadius: '12px',
                fontSize: '12px',
                fontWeight: '600'
            }}>
                {s.label}
            </span>
        );
    };

    const filteredShipments = useMemo(() => {
        if (!search) return shipments;
        const q = search.toLowerCase();
        return shipments.filter(s =>
            (s.shipment_ref || '').toLowerCase().includes(q) ||
            (s.source_warehouse || '').toLowerCase().includes(q) ||
            (s.destination_warehouse || '').toLowerCase().includes(q)
        );
    }, [shipments, search]);

    const columns = [
        {
            key: 'shipment_ref',
            label: t('stock.shipments.table.ref'),
            render: (val) => <span className="font-medium">{val}</span>,
        },
        {
            key: 'source_warehouse',
            label: t('stock.shipments.table.from'),
        },
        {
            key: 'destination_warehouse',
            label: t('stock.shipments.table.to'),
        },
        {
            key: 'item_count',
            label: t('stock.shipments.table.items'),
        },
        {
            key: 'status',
            label: t('stock.shipments.table.status'),
            render: (val) => getStatusBadge(val),
        },
        {
            key: 'created_at',
            label: t('stock.shipments.table.date'),
            render: (val) => <span className="text-muted">{formatShortDate(val)}</span>,
        },
        {
            key: '_actions',
            label: t('stock.shipments.table.actions'),
            width: '120px',
            render: (_, row) => (
                <Link
                    to={`/stock/shipments/${row.id}`}
                    className="btn btn-sm btn-secondary"
                    onClick={(e) => e.stopPropagation()}
                >
                    {t('stock.shipments.view')}
                </Link>
            ),
        },
    ];

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">📦 {t('stock.shipments.title')}</h1>
                    <p className="workspace-subtitle">{t('stock.shipments.subtitle')}</p>
                </div>
                <div className="header-actions">
                    <Link to="/stock/shipments/incoming" className="btn btn-secondary">
                        📥 {t('stock.shipments.incoming')}
                    </Link>
                    <Link to="/stock/shipments/new" className="btn btn-primary">
                        + {t('stock.shipments.new_shipment')}
                    </Link>
                </div>
            </div>

            <SearchFilter
                value={search}
                onChange={setSearch}
                placeholder={t('stock.shipments.search_placeholder', 'بحث بالمرجع أو المستودع...')}
                filters={[{
                    key: 'status',
                    label: t('stock.shipments.filter_status'),
                    options: [
                        { value: 'pending', label: t('stock.shipments.status.pending') },
                        { value: 'dispatched', label: t('stock.shipments.status.dispatched', 'تم الشحن') },
                        { value: 'received', label: t('stock.shipments.status.received') },
                        { value: 'cancelled', label: t('stock.shipments.status.cancelled') },
                    ],
                }]}
                filterValues={{ status: statusFilter }}
                onFilterChange={(key, val) => setStatusFilter(val)}
            />

            <DataTable
                columns={columns}
                data={filteredShipments}
                loading={loading}
                onRowClick={(row) => navigate(`/stock/shipments/${row.id}`)}
                emptyIcon="📦"
                emptyTitle={t('stock.shipments.empty')}
            />
        </div>
    );
};

export default ShipmentList;
