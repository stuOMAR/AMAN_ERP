import { useState, useEffect } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { inventoryAPI } from '../../utils/api';
import BackButton from '../../components/common/BackButton';
import { PageLoading } from '../../components/common/LoadingStates'

function WarehouseDetails() {
    const { t } = useTranslation();
    const { id } = useParams();
    const navigate = useNavigate();
    const [warehouse, setWarehouse] = useState(null);
    const [stock, setStock] = useState([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(null);
    const [search, setSearch] = useState('');

    useEffect(() => {
        fetchData();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [id]);

    const fetchData = async () => {
        setLoading(true);
        setError(null);
        try {
            const [whRes, stockRes] = await Promise.all([
                inventoryAPI.getWarehouse(id),
                inventoryAPI.getWarehouseSpecificStock(id)
            ]);

            setWarehouse(whRes.data);
            setStock(Array.isArray(stockRes.data) ? stockRes.data : []);
        } catch (err) {
            console.error('Failed to load warehouse details:', err);
            setError(t('stock.warehouses.details.error_loading'));
        } finally {
            setLoading(false);
        }
    };

    // Safe filter logic
    const filteredStock = stock.filter(item => {
        if (!search) return true;
        const term = search.toLowerCase();
        const name = (item.product_name || item.item_name || '').toString().toLowerCase();
        const code = (item.product_code || item.item_code || '').toString().toLowerCase();

        return name.includes(term) || code.includes(term);
    });

    if (loading) return <PageLoading />;
    if (error) return (
        <div className="p-8 text-center">
            <div className="text-red-600 mb-4">{error}</div>
            <button className="btn btn-primary" onClick={fetchData}>{t('common.retry')}</button>
            <button className="btn btn-secondary ml-2" onClick={() => navigate('/stock/warehouses')}>{t('common.back_to_list')}</button>
        </div>
    );
    if (!warehouse) return <div className="p-8 text-center">{t('stock.warehouses.details.not_found')}</div>;

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
                    <div>
                        <h1 className="workspace-title">{warehouse.name}</h1>
                        <p className="workspace-subtitle">{t('stock.warehouses.details.code')} {warehouse.code || '-'}</p>
                    </div>

                </div>
            </div>

            {/* F-31: surface the per-warehouse inventory GL account so users
                can verify which ledger picks up movements for this warehouse. */}
            <div className="card mb-6">
                <div className="flex justify-between items-center mb-2">
                    <h3 className="section-title">
                        {t('stock.warehouses.details.gl_section', 'الربط المحاسبي')}
                    </h3>
                </div>
                <div style={{ display: 'flex', gap: 24, flexWrap: 'wrap' }}>
                    <div>
                        <div className="text-muted" style={{ fontSize: 12 }}>
                            {t('branches.name')}
                        </div>
                        <div style={{ fontWeight: 600 }}>{warehouse.branch_name || '-'}</div>
                    </div>
                    <div>
                        <div className="text-muted" style={{ fontSize: 12 }}>
                            {t('stock.warehouses.details.inventory_account', 'حساب المخزون')}
                        </div>
                        <div style={{ fontWeight: 600 }}>
                            {warehouse.gl_inventory_account_id ? (
                                <>
                                    {warehouse.gl_inventory_account_code} —{' '}
                                    {warehouse.gl_inventory_account_name}
                                </>
                            ) : (
                                <span className="text-muted">
                                    {t('stock.warehouses.details.using_global_default',
                                        'يستخدم الحساب الافتراضي للشركة')}
                                </span>
                            )}
                        </div>
                    </div>
                </div>
            </div>

            <div className="card mb-6">
                <div className="flex justify-between items-center mb-4">
                    <h3 className="section-title">{t('stock.warehouses.details.inventory')}</h3>
                    <div className="text-sm text-gray-500">
                        {t('stock.warehouses.details.items_count')} {filteredStock.length}
                    </div>
                </div>

                <div className="mb-4">
                    <input
                        type="text"
                        placeholder={t('stock.warehouses.details.search_placeholder')}
                        value={search}
                        onChange={(e) => setSearch(e.target.value)}
                        className="form-input w-full max-w-md"
                    />
                </div>

                <div className="data-table-container">
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>{t('stock.warehouses.details.table.product_code')}</th>
                                <th>{t('stock.warehouses.details.table.product_name')}</th>
                                <th>{t('stock.warehouses.details.table.quantity')}</th>
                                <th>{t('stock.warehouses.details.table.unit')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {filteredStock.length === 0 ? (
                                <tr>
                                    <td colSpan="4" className="text-center py-8 text-gray-500">
                                        {search ? t('stock.warehouses.details.no_results') : t('stock.warehouses.details.empty_stock')}
                                    </td>
                                </tr>
                            ) : (
                                filteredStock.map((item, index) => (
                                    <tr key={item.id || index} className="hover:bg-gray-50">
                                        <td className="font-mono text-sm border-b p-3">{item.product_code || item.item_code || '-'}</td>
                                        <td className="font-medium border-b p-3 text-gray-900">{item.product_name || item.item_name || t('common.unnamed')}</td>
                                        <td className="font-bold text-primary border-b p-3" dir="ltr">{item.quantity}</td>
                                        <td className="text-gray-600 border-b p-3">{item.unit_name || item.unit || '-'}</td>
                                    </tr>
                                ))
                            )}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
}

export default WarehouseDetails;
