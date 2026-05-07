import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../../utils/api';
import { Plus, Minus, Loader2, CheckCircle, AlertCircle } from 'lucide-react';

const ProductionPartialCompletion = ({ moId, remainingQty, warehouseId }) => {
    const { t } = useTranslation();
    const [qty, setQty] = useState('');
    const [scrapLines, setScrapLines] = useState([]);
    const [byproductLines, setByproductLines] = useState([]);
    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState(null);
    const [error, setError] = useState(null);

    const addScrapLine = () => setScrapLines([...scrapLines, { item_id: '', qty: '', reason: '' }]);
    const removeScrapLine = (i) => setScrapLines(scrapLines.filter((_, idx) => idx !== i));
    const updateScrapLine = (i, field, value) => {
        const updated = [...scrapLines];
        updated[i] = { ...updated[i], [field]: value };
        setScrapLines(updated);
    };

    const addByproductLine = () => setByproductLines([...byproductLines, { item_id: '', qty: '', sales_value: '' }]);
    const removeByproductLine = (i) => setByproductLines(byproductLines.filter((_, idx) => idx !== i));
    const updateByproductLine = (i, field, value) => {
        const updated = [...byproductLines];
        updated[i] = { ...updated[i], [field]: value };
        setByproductLines(updated);
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        const qtyNum = parseFloat(qty);
        if (!qtyNum || qtyNum <= 0 || qtyNum > remainingQty) return;

        setLoading(true);
        setError(null);
        setResult(null);

        try {
            const payload = {
                qty: qtyNum,
                warehouse_id: warehouseId,
                scrap_lines: scrapLines.filter(s => s.item_id && s.qty).map(s => ({
                    item_id: parseInt(s.item_id),
                    qty: parseFloat(s.qty),
                    reason: s.reason,
                })),
                byproduct_lines: byproductLines.filter(b => b.item_id && b.qty).map(b => ({
                    item_id: parseInt(b.item_id),
                    qty: parseFloat(b.qty),
                    sales_value: b.sales_value ? parseFloat(b.sales_value) : undefined,
                })),
            };
            const res = await api.post(`/manufacturing/orders/${moId}/complete`, payload);
            setResult(res.data);
        } catch (err) {
            const detail = err.response?.data?.detail;
            setError(typeof detail === 'object' ? detail.message : detail || 'Completion failed');
        } finally {
            setLoading(false);
        }
    };

    if (result) {
        return (
            <div className="p-4 bg-green-50 rounded-lg space-y-2">
                <div className="flex items-center gap-2 text-green-700">
                    <CheckCircle size={18} />
                    <span className="font-medium">{t('Completion recorded')}</span>
                </div>
                <div className="text-sm text-green-600">
                    <p>Completed: {result.qty_completed}</p>
                    <p>Remaining: {result.remaining_qty}</p>
                    {result.wip_to_fg_je_id && <p>JE #{result.wip_to_fg_je_id}</p>}
                </div>
            </div>
        );
    }

    return (
        <form onSubmit={handleSubmit} className="space-y-4">
            <div>
                <label className="block text-sm font-medium mb-1">
                    {t('Quantity')} (max: {remainingQty})
                </label>
                <input
                    type="number"
                    value={qty}
                    onChange={e => setQty(e.target.value)}
                    min="0.0001"
                    max={remainingQty}
                    step="0.0001"
                    className="w-full border rounded-lg px-3 py-2 text-sm"
                    required
                />
            </div>

            {/* Scrap Lines */}
            <div>
                <div className="flex items-center justify-between mb-2">
                    <label className="text-sm font-medium">{t('Scrap Lines')}</label>
                    <button type="button" onClick={addScrapLine} className="text-blue-600 text-sm flex items-center gap-1">
                        <Plus size={14} /> {t('Add')}
                    </button>
                </div>
                {scrapLines.map((line, i) => (
                    <div key={i} className="flex gap-2 mb-2">
                        <input
                            placeholder="Item ID"
                            value={line.item_id}
                            onChange={e => updateScrapLine(i, 'item_id', e.target.value)}
                            className="flex-1 border rounded px-2 py-1 text-sm"
                        />
                        <input
                            placeholder="Qty"
                            type="number"
                            value={line.qty}
                            onChange={e => updateScrapLine(i, 'qty', e.target.value)}
                            className="w-24 border rounded px-2 py-1 text-sm"
                        />
                        <input
                            placeholder="Reason"
                            value={line.reason}
                            onChange={e => updateScrapLine(i, 'reason', e.target.value)}
                            className="flex-1 border rounded px-2 py-1 text-sm"
                        />
                        <button type="button" onClick={() => removeScrapLine(i)} className="text-red-500">
                            <Minus size={14} />
                        </button>
                    </div>
                ))}
            </div>

            {/* By-product Lines */}
            <div>
                <div className="flex items-center justify-between mb-2">
                    <label className="text-sm font-medium">{t('By-products')}</label>
                    <button type="button" onClick={addByproductLine} className="text-blue-600 text-sm flex items-center gap-1">
                        <Plus size={14} /> {t('Add')}
                    </button>
                </div>
                {byproductLines.map((line, i) => (
                    <div key={i} className="flex gap-2 mb-2">
                        <input
                            placeholder="Item ID"
                            value={line.item_id}
                            onChange={e => updateByproductLine(i, 'item_id', e.target.value)}
                            className="flex-1 border rounded px-2 py-1 text-sm"
                        />
                        <input
                            placeholder="Qty"
                            type="number"
                            value={line.qty}
                            onChange={e => updateByproductLine(i, 'qty', e.target.value)}
                            className="w-24 border rounded px-2 py-1 text-sm"
                        />
                        <input
                            placeholder="Sales Value"
                            type="number"
                            value={line.sales_value}
                            onChange={e => updateByproductLine(i, 'sales_value', e.target.value)}
                            className="w-32 border rounded px-2 py-1 text-sm"
                        />
                        <button type="button" onClick={() => removeByproductLine(i)} className="text-red-500">
                            <Minus size={14} />
                        </button>
                    </div>
                ))}
            </div>

            {error && (
                <div className="flex items-center gap-1 text-red-600 text-sm">
                    <AlertCircle size={14} />
                    <span>{error}</span>
                </div>
            )}

            <button
                type="submit"
                disabled={loading}
                className="w-full py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700
                           disabled:opacity-50 text-sm flex items-center justify-center gap-2"
            >
                {loading ? <Loader2 size={16} className="animate-spin" /> : null}
                {loading ? t('Processing...') : t('Complete Production')}
            </button>
        </form>
    );
};

export default ProductionPartialCompletion;
