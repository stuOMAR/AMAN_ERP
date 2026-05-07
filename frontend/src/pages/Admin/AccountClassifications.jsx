import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Layers, Edit, Eye, RefreshCw } from 'lucide-react';
import BackButton from '../../components/common/BackButton';
import '../../components/ModuleStyles.css';

const CATEGORIES = [
    'asset', 'liability', 'equity', 'revenue', 'expense',
    'contra_asset', 'contra_liability', 'contra_equity', 'contra_revenue', 'contra_expense',
];

const AccountClassifications = () => {
    const { t } = useTranslation();
    const [classifications, setClassifications] = useState([]);
    const [loading, setLoading] = useState(true);
    const [editRow, setEditRow] = useState(null);
    const [form, setForm] = useState({ statement_category: '', sign: 1, aggregation_hint: '' });
    const [error, setError] = useState('');

    useEffect(() => { fetchData(); }, []);

    const fetchData = async () => {
        try {
            setLoading(true);
            const res = await fetch('/api/admin/account-classifications');
            if (!res.ok) throw new Error('Failed to fetch');
            setClassifications(await res.json());
        } catch (e) {
            setError(e.message);
        } finally {
            setLoading(false);
        }
    };

    const handleSave = async () => {
        try {
            setError('');
            const res = await fetch('/api/admin/account-classifications', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    account_id: editRow.account_id,
                    statement_category: form.statement_category,
                    sign: parseInt(form.sign),
                    aggregation_hint: form.aggregation_hint || null,
                    valid_from: new Date().toISOString().split('T')[0],
                }),
            });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Save failed');
            }
            setEditRow(null);
            fetchData();
        } catch (e) {
            setError(e.message);
        }
    };

    const startEdit = (row) => {
        setEditRow(row);
        setForm({
            statement_category: row.statement_category,
            sign: row.sign,
            aggregation_hint: row.aggregation_hint || '',
        });
    };

    return (
        <div style={{ padding: 24, direction: 'rtl' }}>
            <BackButton />
            <h1 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Layers size={24} /> {t('account_classifications.title')}
            </h1>

            {error && <div style={{ color: '#ef4444', marginBottom: 12 }}>{error}</div>}

            <div style={{ marginBottom: 16 }}>
                <button onClick={fetchData} style={{ ...btnStyle, background: '#6b7280' }}>
                    <RefreshCw size={16} />
                </button>
            </div>

            {editRow && (
                <div style={{ background: '#f9fafb', padding: 16, borderRadius: 8, marginBottom: 16 }}>
                    <h3>{t('account_classifications.edit')} — Account #{editRow.account_id}</h3>
                    <select value={form.statement_category}
                        onChange={e => setForm({ ...form, statement_category: e.target.value })}
                        style={inputStyle}>
                        <option value="">{t('account_classifications.select_category')}</option>
                        {CATEGORIES.map(c => <option key={c} value={c}>{c}</option>)}
                    </select>
                    <select value={form.sign}
                        onChange={e => setForm({ ...form, sign: e.target.value })}
                        style={inputStyle}>
                        <option value={1}>+1</option>
                        <option value={-1}>-1</option>
                    </select>
                    <input placeholder={t('account_classifications.hint')} value={form.aggregation_hint}
                        onChange={e => setForm({ ...form, aggregation_hint: e.target.value })} style={inputStyle} />
                    <button onClick={handleSave} style={{ ...btnStyle, background: '#10b981' }}>{t('common.save')}</button>
                    <button onClick={() => setEditRow(null)} style={{ ...btnStyle, background: '#6b7280', marginRight: 8 }}>{t('common.cancel')}</button>
                </div>
            )}

            {loading ? <p>{t('common.loading')}</p> : (
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                        <tr style={{ borderBottom: '2px solid #e5e7eb' }}>
                            <th style={thStyle}>{t('account_classifications.account_id')}</th>
                            <th style={thStyle}>{t('account_classifications.category')}</th>
                            <th style={thStyle}>{t('account_classifications.sign')}</th>
                            <th style={thStyle}>{t('account_classifications.hint')}</th>
                            <th style={thStyle}>{t('account_classifications.active')}</th>
                            <th style={thStyle}>{t('common.actions')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {classifications.map(c => (
                            <tr key={c.id} style={{ borderBottom: '1px solid #e5e7eb' }}>
                                <td style={tdStyle}>{c.account_id}</td>
                                <td style={tdStyle}>{c.statement_category}</td>
                                <td style={tdStyle}>{c.sign > 0 ? '+1' : '-1'}</td>
                                <td style={tdStyle}>{c.aggregation_hint || '—'}</td>
                                <td style={tdStyle}>{c.is_active ? '✓' : '✗'}</td>
                                <td style={tdStyle}>
                                    <button onClick={() => startEdit(c)} style={iconBtn}><Edit size={14} /></button>
                                </td>
                            </tr>
                        ))}
                    </tbody>
                </table>
            )}
        </div>
    );
};

const btnStyle = { padding: '8px 16px', borderRadius: 6, border: 'none', color: '#fff', cursor: 'pointer', display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 14 };
const inputStyle = { padding: '8px 12px', border: '1px solid #d1d5db', borderRadius: 6, marginRight: 8, fontSize: 14, width: 180 };
const thStyle = { textAlign: 'left', padding: '8px 12px', fontWeight: 600 };
const tdStyle = { padding: '8px 12px' };
const iconBtn = { background: 'none', border: 'none', cursor: 'pointer', padding: 4, color: '#3b82f6' };

export default AccountClassifications;
