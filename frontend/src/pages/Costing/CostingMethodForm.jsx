import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { costingLayerAPI } from '../../services/costing'
import BackButton from '../../components/common/BackButton'
import FormField from '../../components/common/FormField'
import { useToast } from '../../context/ToastContext'

function CostingMethodForm() {
    const { t } = useTranslation()
    const { showToast } = useToast()
    const [loading, setLoading] = useState(false)
    const [result, setResult] = useState(null)
    const [form, setForm] = useState({
        product_id: '',
        warehouse_id: '',
        new_method: 'fifo',
    })

    const handleSubmit = async (e) => {
        e.preventDefault()
        try {
            setLoading(true)
            const res = await costingLayerAPI.changeMethod({
                product_id: parseInt(form.product_id),
                warehouse_id: parseInt(form.warehouse_id),
                new_method: form.new_method,
            })
            setResult(res.data)
            showToast(t('costing.method_changed'), 'success')
        } catch (e) {
            showToast(e.response?.data?.detail || t('costing.change_error'), 'error')
        } finally {
            setLoading(false)
        }
    }

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <h1 className="workspace-title">{t('costing.change_method_title')}</h1>
            </div>

            <form onSubmit={handleSubmit} className="card" style={{ padding: 16 }}>
                <div className="form-row">
                    <FormField label={t('costing.product_id')} required>
                        <input className="form-input" type="number" required value={form.product_id}
                            onChange={e => setForm({ ...form, product_id: e.target.value })} />
                    </FormField>
                    <FormField label={t('costing.warehouse_id')} required>
                        <input className="form-input" type="number" required value={form.warehouse_id}
                            onChange={e => setForm({ ...form, warehouse_id: e.target.value })} />
                    </FormField>
                    <FormField label={t('costing.new_method')} required>
                        <select className="form-input" value={form.new_method} onChange={e => setForm({ ...form, new_method: e.target.value })}>
                            <option value="fifo">FIFO</option>
                            <option value="lifo">LIFO</option>
                        </select>
                    </FormField>
                </div>
                <button type="submit" className="btn btn-primary" disabled={loading}>
                    {loading ? t('common.saving') : t('costing.apply_change')}
                </button>
            </form>

            {result && (
                <div className="card" style={{ padding: 16, marginTop: 16 }}>
                    <h3>{t('costing.change_result')}</h3>
                    <p><strong>{t('costing.old_method')}:</strong> {result.old_method || 'WAC'}</p>
                    <p><strong>{t('costing.new_method')}:</strong> {result.new_method?.toUpperCase()}</p>
                    <p><strong>{t('costing.layers_created')}:</strong> {result.layers_created}</p>
                    <p>{result.message}</p>
                </div>
            )}
        </div>
    )
}

export default CostingMethodForm
