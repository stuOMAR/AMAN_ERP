import React, { useState, useEffect } from 'react';
import { useTranslation } from 'react-i18next';
import { Key, RotateCw, Trash2, RefreshCw, Plus, Shield } from 'lucide-react';
import BackButton from '../../components/common/BackButton';
import '../../components/ModuleStyles.css';

const IntegrationCredentials = () => {
    const { t } = useTranslation();
    const [credentials, setCredentials] = useState([]);
    const [loading, setLoading] = useState(true);
    const [showCreate, setShowCreate] = useState(false);
    const [form, setForm] = useState({ integration: '', name: '', secret: '' });
    const [error, setError] = useState('');

    useEffect(() => { fetchCredentials(); }, []);

    const fetchCredentials = async () => {
        try {
            setLoading(true);
            const res = await fetch('/api/admin/credentials');
            if (!res.ok) throw new Error('Failed to fetch');
            setCredentials(await res.json());
        } catch (e) {
            setError(e.message);
        } finally {
            setLoading(false);
        }
    };

    const handleCreate = async () => {
        try {
            setError('');
            const res = await fetch('/api/admin/credentials', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(form),
            });
            if (!res.ok) {
                const data = await res.json();
                throw new Error(data.detail || 'Create failed');
            }
            setShowCreate(false);
            setForm({ integration: '', name: '', secret: '' });
            fetchCredentials();
        } catch (e) {
            setError(e.message);
        }
    };

    const handleRotate = async (id) => {
        const newSecret = prompt(t('credentials.new_secret_prompt'));
        if (!newSecret) return;
        try {
            const res = await fetch(`/api/admin/credentials/${id}/rotate`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ new_secret: newSecret }),
            });
            if (!res.ok) throw new Error('Rotation failed');
            fetchCredentials();
        } catch (e) {
            setError(e.message);
        }
    };

    const handleSoftDelete = async (id) => {
        if (!window.confirm(t('credentials.confirm_delete'))) return;
        try {
            await fetch(`/api/admin/credentials/${id}/soft-delete`, { method: 'POST' });
            fetchCredentials();
        } catch (e) {
            setError(e.message);
        }
    };

    const handleRestore = async (id) => {
        try {
            await fetch(`/api/admin/credentials/${id}/restore`, { method: 'POST' });
            fetchCredentials();
        } catch (e) {
            setError(e.message);
        }
    };

    const statusColor = (s) => ({
        active: '#10b981', rotating: '#f59e0b', soft_deleted: '#ef4444'
    }[s] || '#6b7280');

    return (
        <div style={{ padding: 24, direction: 'rtl' }}>
            <BackButton />
            <h1 style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Key size={24} /> {t('credentials.title')}
            </h1>

            {error && <div style={{ color: '#ef4444', marginBottom: 12 }}>{error}</div>}

            <div style={{ marginBottom: 16 }}>
                <button onClick={() => setShowCreate(!showCreate)} style={{ ...btnStyle, background: '#3b82f6' }}>
                    <Plus size={16} /> {t('credentials.create')}
                </button>
                <button onClick={fetchCredentials} style={{ ...btnStyle, background: '#6b7280', marginRight: 8 }}>
                    <RefreshCw size={16} />
                </button>
            </div>

            {showCreate && (
                <div style={{ background: '#f9fafb', padding: 16, borderRadius: 8, marginBottom: 16 }}>
                    <input placeholder={t('credentials.integration')} value={form.integration}
                        onChange={e => setForm({ ...form, integration: e.target.value })} style={inputStyle} />
                    <input placeholder={t('credentials.name')} value={form.name}
                        onChange={e => setForm({ ...form, name: e.target.value })} style={inputStyle} />
                    <input placeholder={t('credentials.secret')} type="password" value={form.secret}
                        onChange={e => setForm({ ...form, secret: e.target.value })} style={inputStyle} />
                    <button onClick={handleCreate} style={{ ...btnStyle, background: '#10b981' }}>
                        {t('common.save')}
                    </button>
                </div>
            )}

            {loading ? <p>{t('common.loading')}</p> : (
                <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                    <thead>
                        <tr style={{ borderBottom: '2px solid #e5e7eb' }}>
                            <th style={thStyle}>{t('credentials.integration')}</th>
                            <th style={thStyle}>{t('credentials.name')}</th>
                            <th style={thStyle}>{t('credentials.status')}</th>
                            <th style={thStyle}>{t('credentials.failures')}</th>
                            <th style={thStyle}>{t('common.actions')}</th>
                        </tr>
                    </thead>
                    <tbody>
                        {credentials.map(c => (
                            <tr key={c.id} style={{ borderBottom: '1px solid #e5e7eb' }}>
                                <td style={tdStyle}>{c.integration}</td>
                                <td style={tdStyle}>{c.name}</td>
                                <td style={tdStyle}>
                                    <span style={{ color: statusColor(c.status), fontWeight: 600 }}>
                                        {c.status}
                                    </span>
                                </td>
                                <td style={tdStyle}>{c.consecutive_failures || 0}</td>
                                <td style={tdStyle}>
                                    {c.status !== 'soft_deleted' && (
                                        <>
                                            <button onClick={() => handleRotate(c.id)} title={t('credentials.rotate')} style={iconBtn}>
                                                <RotateCw size={14} />
                                            </button>
                                            <button onClick={() => handleSoftDelete(c.id)} title={t('credentials.delete')} style={iconBtn}>
                                                <Trash2 size={14} />
                                            </button>
                                        </>
                                    )}
                                    {c.status === 'soft_deleted' && (
                                        <button onClick={() => handleRestore(c.id)} title={t('credentials.restore')} style={iconBtn}>
                                            <RefreshCw size={14} />
                                        </button>
                                    )}
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
const inputStyle = { padding: '8px 12px', border: '1px solid #d1d5db', borderRadius: 6, marginRight: 8, fontSize: 14, width: 200 };
const thStyle = { textAlign: 'left', padding: '8px 12px', fontWeight: 600 };
const tdStyle = { padding: '8px 12px' };
const iconBtn = { background: 'none', border: 'none', cursor: 'pointer', padding: 4, color: '#3b82f6' };

export default IntegrationCredentials;
