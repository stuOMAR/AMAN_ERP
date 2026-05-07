import React, { useState } from 'react';
import { useTranslation } from 'react-i18next';
import api from '../../utils/api';
import { FileText, Loader2, CheckCircle, AlertCircle } from 'lucide-react';

const OrderToInvoiceAction = ({ orderId, orderState, onCreated }) => {
    const { t } = useTranslation();
    const [loading, setLoading] = useState(false);
    const [result, setResult] = useState(null);
    const [error, setError] = useState(null);

    const handleConvert = async () => {
        if (orderState !== 'confirmed') return;

        setLoading(true);
        setError(null);
        setResult(null);

        // Generate client-side UUID for idempotency
        const idempotencyKey = crypto.randomUUID();

        try {
            const res = await api.post(`/sales/orders/${orderId}/invoice`, {}, {
                headers: { 'Idempotency-Key': idempotencyKey },
            });
            setResult(res.data);
            onCreated?.(res.data);
        } catch (err) {
            const detail = err.response?.data?.detail;
            setError(typeof detail === 'object' ? detail.message : detail || 'Conversion failed');
        } finally {
            setLoading(false);
        }
    };

    if (result) {
        return (
            <div className="flex items-center gap-2 text-green-600 text-sm">
                <CheckCircle size={16} />
                <span>Invoice #{result.id} — {result.state}</span>
            </div>
        );
    }

    return (
        <div>
            <button
                onClick={handleConvert}
                disabled={loading || orderState !== 'confirmed'}
                className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg
                           hover:bg-blue-700 disabled:opacity-50 disabled:cursor-not-allowed text-sm"
            >
                {loading ? <Loader2 size={16} className="animate-spin" /> : <FileText size={16} />}
                {loading ? t('Converting...') : t('Convert to Invoice')}
            </button>
            {error && (
                <div className="flex items-center gap-1 mt-2 text-red-600 text-sm">
                    <AlertCircle size={14} />
                    <span>{error}</span>
                </div>
            )}
        </div>
    );
};

export default OrderToInvoiceAction;
