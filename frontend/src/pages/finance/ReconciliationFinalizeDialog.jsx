import React from 'react';
import { useTranslation } from 'react-i18next';
import { AlertTriangle, X } from 'lucide-react';

/**
 * Drift-report dialog shown when POST /reconciliation/{id}/finalize
 * returns a 409 with a structured drift report.
 *
 * Props:
 *   drift     — { gl_total, bank_total, difference, tolerance, unmatched_lines: [{id, description, amount}] }
 *   onClose   — callback to dismiss
 *   onProceed — optional callback to force-override (if user has authority)
 */
const ReconciliationFinalizeDialog = ({ drift, onClose, onProceed }) => {
    const { t } = useTranslation();

    if (!drift) return null;

    const fmt = (v) => Number(v ?? 0).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });

    return (
        <div style={overlayStyle}>
            <div style={dialogStyle}>
                <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 16 }}>
                    <h2 style={{ margin: 0, display: 'flex', alignItems: 'center', gap: 8, color: '#ef4444' }}>
                        <AlertTriangle size={20} /> {t('reconciliation.drift_title')}
                    </h2>
                    <button onClick={onClose} style={{ background: 'none', border: 'none', cursor: 'pointer', padding: 4 }}>
                        <X size={18} />
                    </button>
                </div>

                <table style={{ width: '100%', borderCollapse: 'collapse', marginBottom: 16 }}>
                    <tbody>
                        <tr style={{ borderBottom: '1px solid #e5e7eb' }}>
                            <td style={labelStyle}>{t('reconciliation.gl_total')}</td>
                            <td style={valueStyle}>{fmt(drift.gl_total)}</td>
                        </tr>
                        <tr style={{ borderBottom: '1px solid #e5e7eb' }}>
                            <td style={labelStyle}>{t('reconciliation.bank_total')}</td>
                            <td style={valueStyle}>{fmt(drift.bank_total)}</td>
                        </tr>
                        <tr style={{ borderBottom: '1px solid #e5e7eb' }}>
                            <td style={labelStyle}>{t('reconciliation.difference')}</td>
                            <td style={{ ...valueStyle, color: '#ef4444', fontWeight: 700 }}>{fmt(drift.difference)}</td>
                        </tr>
                        <tr>
                            <td style={labelStyle}>{t('reconciliation.tolerance')}</td>
                            <td style={valueStyle}>{fmt(drift.tolerance)}</td>
                        </tr>
                    </tbody>
                </table>

                {drift.unmatched_lines && drift.unmatched_lines.length > 0 && (
                    <>
                        <h3 style={{ marginBottom: 8 }}>{t('reconciliation.unmatched_lines')}</h3>
                        <div style={{ maxHeight: 200, overflowY: 'auto', border: '1px solid #e5e7eb', borderRadius: 6 }}>
                            <table style={{ width: '100%', borderCollapse: 'collapse' }}>
                                <thead>
                                    <tr style={{ borderBottom: '1px solid #e5e7eb' }}>
                                        <th style={thStyle}>{t('reconciliation.line_id')}</th>
                                        <th style={thStyle}>{t('reconciliation.description')}</th>
                                        <th style={thStyle}>{t('reconciliation.amount')}</th>
                                    </tr>
                                </thead>
                                <tbody>
                                    {drift.unmatched_lines.map(line => (
                                        <tr key={line.id} style={{ borderBottom: '1px solid #f3f4f6' }}>
                                            <td style={tdStyle}>{line.id}</td>
                                            <td style={tdStyle}>{line.description || '—'}</td>
                                            <td style={tdStyle}>{fmt(line.amount)}</td>
                                        </tr>
                                    ))}
                                </tbody>
                            </table>
                        </div>
                    </>
                )}

                <div style={{ display: 'flex', justifyContent: 'flex-end', gap: 8, marginTop: 16 }}>
                    <button onClick={onClose} style={cancelBtnStyle}>
                        {t('common.close')}
                    </button>
                    {onProceed && (
                        <button onClick={onProceed} style={proceedBtnStyle}>
                            {t('reconciliation.force_finalize')}
                        </button>
                    )}
                </div>
            </div>
        </div>
    );
};

const overlayStyle = {
    position: 'fixed', top: 0, left: 0, right: 0, bottom: 0,
    background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center',
    zIndex: 1000,
};
const dialogStyle = {
    background: '#fff', borderRadius: 12, padding: 24, maxWidth: 560, width: '90%',
    boxShadow: '0 20px 60px rgba(0,0,0,0.3)', direction: 'rtl',
};
const labelStyle = { padding: '8px 12px', fontWeight: 600, fontSize: 14, width: '40%' };
const valueStyle = { padding: '8px 12px', fontSize: 14, textAlign: 'left' };
const thStyle = { textAlign: 'left', padding: '6px 10px', fontWeight: 600, fontSize: 13, background: '#f9fafb' };
const tdStyle = { padding: '6px 10px', fontSize: 13 };
const cancelBtnStyle = { padding: '8px 16px', borderRadius: 6, border: '1px solid #d1d5db', background: '#fff', cursor: 'pointer', fontSize: 14 };
const proceedBtnStyle = { padding: '8px 16px', borderRadius: 6, border: 'none', background: '#f59e0b', color: '#fff', cursor: 'pointer', fontSize: 14 };

export default ReconciliationFinalizeDialog;
