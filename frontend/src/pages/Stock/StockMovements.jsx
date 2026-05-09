import { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { inventoryAPI } from '../../utils/api';
import CustomDatePicker from '../../components/common/CustomDatePicker';
import { formatShortDate, formatDateTime} from '../../utils/dateUtils';
import { formatNumber } from '../../utils/format';
import { Filter, Search, Warehouse, Activity, Calendar } from 'lucide-react';
import { useBranch } from '../../context/BranchContext';
import { useToast } from '../../context/ToastContext';
import BackButton from '../../components/common/BackButton';
import { Spinner } from '../../components/common/LoadingStates'

const StockMovements = () => {
    const { t } = useTranslation();
    const { currentBranch } = useBranch();
    const { showToast } = useToast();
    const [movements, setMovements] = useState([]);
    const [loading, setLoading] = useState(true);
    const [initialLoad, setInitialLoad] = useState(true);
    const [filters, setFilters] = useState({
        item_name: '',
        warehouse: '',
        transaction_type: '',
        start_date: '',
        end_date: ''
    });
    const [warehouses, setWarehouses] = useState([]);

    useEffect(() => {
        const fetchInitialData = async () => {
            try {
                const [wRes, mRes] = await Promise.all([
                    inventoryAPI.listWarehouses({ branch_id: currentBranch?.id }),
                    inventoryAPI.getStockMovements({ branch_id: currentBranch?.id })
                ]);
                setWarehouses(wRes.data);
                setMovements(mRes.data);
            } catch (err) {
                showToast(t('stock.reports.movements.error_load'), 'error');
            } finally {
                setLoading(false);
                setInitialLoad(false);
            }
        };
        const timer = setTimeout(() => {
            fetchInitialData();
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch]);

    const handleFilterChange = async (e) => {
        const { name, value } = e.target;
        const newFilters = { ...filters, [name]: value };
        setFilters(newFilters);

        try {
            setLoading(true);
            const res = await inventoryAPI.getStockMovements({ ...newFilters, branch_id: currentBranch?.id });
            setMovements(res.data);
        } catch (err) {
            showToast(t('stock.reports.movements.error_filter'), 'error');
        } finally {
            setLoading(false);
        }
    };

    const getTypeBadge = (type) => {
        const types = {
            'purchase_in': { label: t('stock.reports.movements.types.purchase_in'), color: 'rgba(16, 185, 129, 0.1)', text: '#10b981' },
            'sales_out': { label: t('stock.reports.movements.types.sales_out'), color: 'rgba(239, 68, 68, 0.1)', text: '#ef4444' },
            'transfer_out': { label: t('stock.reports.movements.types.transfer_out'), color: 'rgba(245, 158, 11, 0.1)', text: '#f59e0b' },
            'transfer_in': { label: t('stock.reports.movements.types.transfer_in'), color: 'rgba(37, 99, 235, 0.1)', text: '#2563eb' },
            'adjustment_in': { label: t('stock.reports.movements.types.adjustment_in'), color: 'rgba(79, 70, 229, 0.1)', text: '#4f46e5' },
            'adjustment_out': { label: t('stock.reports.movements.types.adjustment_out'), color: 'rgba(126, 34, 206, 0.1)', text: '#7e22ce' },
            'shipment_out': { label: t('stock.reports.movements.types.shipment_out'), color: 'rgba(234, 88, 12, 0.1)', text: '#ea580c' },
            'shipment_in': { label: t('stock.reports.movements.types.shipment_in'), color: 'rgba(101, 163, 13, 0.1)', text: '#65a30d' },
        };
        const style = types[type] || { label: type, color: '#f3f4f6', text: '#374151' };

        return (
            <span style={{
                background: style.color,
                color: style.text,
                padding: '4px 10px',
                borderRadius: '6px',
                fontSize: '11px',
                fontWeight: '600',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '4px',
                minWidth: '110px',
                justifyContent: 'center'
            }}>
                <Activity size={10} />
                {style.label}
            </span>
        );
    };

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div>
                    <h1 className="workspace-title">{t('stock.reports.movements.title')}</h1>
                    <p className="workspace-subtitle">{t('stock.reports.movements.subtitle')}</p>
                </div>
            </div>

            {/* Filters */}
            <div className="section-card mb-6">
                <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: '16px', alignItems: 'end' }}>
                    <div className="form-group mb-0">
                        <label className="form-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <Search size={14} className="text-muted" /> {t('stock.reports.movements.table.product')}
                        </label>
                        <input
                            type="text"
                            name="item_name"
                            placeholder={t('stock.reports.movements.filters.search_placeholder')}
                            className="form-input"
                            value={filters.item_name}
                            onChange={handleFilterChange}
                        />
                    </div>

                    <div className="form-group mb-0">
                        <label className="form-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <Warehouse size={14} className="text-muted" /> {t('stock.reports.movements.table.warehouse')}
                        </label>
                        <select
                            name="warehouse"
                            className="form-input"
                            value={filters.warehouse}
                            onChange={handleFilterChange}
                        >
                            <option value="">{t('stock.reports.movements.filters.all_warehouses')}</option>
                            {warehouses.map(w => (
                                <option key={w.id} value={w.id}>{w.name}</option>
                            ))}
                        </select>
                    </div>

                    <div className="form-group mb-0">
                        <label className="form-label" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <Filter size={14} className="text-muted" /> {t('stock.reports.movements.table.type')}
                        </label>
                        <select
                            name="transaction_type"
                            className="form-input"
                            value={filters.transaction_type}
                            onChange={handleFilterChange}
                        >
                            <option value="">{t('stock.reports.movements.filters.all_transactions')}</option>
                            <option value="purchase_in">{t('stock.reports.movements.types.purchase')}</option>
                            <option value="sales_out">{t('stock.reports.movements.types.sales')}</option>
                            <option value="transfer">{t('stock.reports.movements.types.transfer')}</option>
                            <option value="adjustment">{t('stock.reports.movements.types.adjustment')}</option>
                            <option value="shipment">{t('stock.reports.movements.types.shipment')}</option>
                        </select>
                    </div>

                    <div className="form-group mb-0">
                        <CustomDatePicker
                            label={<span><Calendar size={14} className="text-muted" style={{ verticalAlign: 'middle', marginLeft: '6px' }} /> {t('stock.reports.movements.filters.from_date')}</span>}
                            selected={filters.start_date}
                            onChange={(dateStr) => handleFilterChange({ target: { name: 'start_date', value: dateStr } })}
                        />
                    </div>

                    <div className="form-group mb-0">
                        <CustomDatePicker
                            label={<span><Calendar size={14} className="text-muted" style={{ verticalAlign: 'middle', marginLeft: '6px' }} /> {t('stock.reports.movements.filters.to_date')}</span>}
                            selected={filters.end_date}
                            onChange={(dateStr) => handleFilterChange({ target: { name: 'end_date', value: dateStr } })}
                        />
                    </div>
                </div>
            </div>

            {/* Data Table */}
            <div className="section-card section-card-flush" style={{ overflow: 'hidden' }}>
                {loading ? (
                    <div style={{ padding: '48px', textAlign: 'center' }}>
                        <Spinner size="sm"/>
                        <div className="mt-4 text-muted">{t('common.loading')}</div>
                    </div>
                ) : movements.length === 0 ? (
                    <div style={{ padding: '48px', textAlign: 'center' }}>
                        <Activity size={48} className="text-muted mb-4" />
                        <h3 className="text-secondary">{t('stock.reports.movements.empty')}</h3>
                    </div>
                ) : (
                    <div className="data-table-container">
                        <table className="data-table">
                            <thead>
                                <tr>
                                    <th style={{ width: '160px' }}>{t('stock.reports.movements.table.date')}</th>
                                    <th>{t('stock.reports.movements.table.type')}</th>
                                    <th>{t('stock.reports.movements.table.ref')}</th>
                                    <th>{t('stock.reports.movements.table.product')}</th>
                                    <th>{t('stock.reports.movements.table.warehouse')}</th>
                                    <th style={{ textAlign: 'left' }}>{t('stock.reports.movements.table.quantity')}</th>
                                    <th>{t('stock.reports.movements.table.user')}</th>
                                </tr>
                            </thead>
                            <tbody>
                                {movements.map((move, idx) => (
                                    <tr key={idx}>
                                        <td className="text-sm text-secondary font-mono">
                                            {formatShortDate(move.created_at)}
                                            <div style={{ fontSize: '10px', color: 'var(--text-muted)' }}>
                                                {formatDateTime(move.created_at)}
                                            </div>
                                        </td>
                                        <td>{getTypeBadge(move.transaction_type)}</td>
                                        <td className="font-mono text-sm text-primary">
                                            {move.reference_document || '-'}
                                        </td>
                                        <td>
                                            <div className="font-medium">{move.product_name}</div>
                                            <div className="text-xs text-muted mt-1">{move.product_code}</div>
                                        </td>
                                        <td>
                                            <span className="text-sm" style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                                                <Warehouse size={12} className="text-muted" />
                                                {move.warehouse_name}
                                            </span>
                                        </td>
                                        <td dir="ltr" style={{ textAlign: 'left' }} className={`font-bold ${move.quantity > 0 ? 'text-success' : 'text-danger'}`}>
                                            {move.quantity > 0 ? `+${formatNumber(move.quantity)}` : formatNumber(move.quantity)}
                                        </td>
                                        <td className="text-sm text-muted">{move.user_name}</td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </div>
        </div>
    );
};

export default StockMovements;
