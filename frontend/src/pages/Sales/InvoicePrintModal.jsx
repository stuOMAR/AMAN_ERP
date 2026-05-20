import { useState, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import DOMPurify from 'dompurify';
import { formatNumber } from '../../utils/format';
import { formatShortDate } from '../../utils/dateUtils';
import { getCurrency } from '../../utils/auth';
import { Printer, X } from 'lucide-react';

/**
 * SALES-005: Multi-format Invoice Printing
 * Supports: A4, Thermal 80mm, Thermal 58mm, ZATCA-compliant
 */

const FORMATS = {
    a4: { label: 'A4', width: '210mm', icon: '📄' },
    thermal80: { label: '80mm', width: '80mm', icon: '🧾' },
    thermal58: { label: '58mm', width: '58mm', icon: '🧾' },
    zatca: { label: 'ZATCA', width: '210mm', icon: '🏛️' }
};

const isPositiveDecimalString = (value) => {
    if (value === null || value === undefined || value === '') return false;
    const normalized = String(value).trim();
    if (!/^\d+(\.\d+)?$/.test(normalized)) return false;
    const [intPart, fracPart = ''] = normalized.split('.');
    return /[1-9]/.test(`${intPart}${fracPart}`);
};

const InvoicePrintModal = ({ invoice, onClose }) => {
    const { t, i18n } = useTranslation();
    const [format, setFormat] = useState('a4');
    const printRef = useRef(null);
    const currency = getCurrency();
    const isRTL = i18n.language === 'ar';

    if (!invoice) return null;

    const handlePrint = () => {
        const content = printRef.current;
        if (!content) return;
        const win = window.open('', '_blank', 'width=800,height=600');
        if (!win) return;

        // SEC / TASK-029: build the print document using DOM APIs instead of
        // document.write with template-literal interpolation. User-controlled
        // values (invoice_number, customer_name, etc.) go into the DOM via
        // textContent / setAttribute, never concatenated into HTML strings.
        const doc = win.document;
        doc.open();
        doc.write('<!DOCTYPE html><html><head><meta charset="utf-8"></head><body></body></html>');
        doc.close();
        doc.documentElement.setAttribute('dir', isRTL ? 'rtl' : 'ltr');
        doc.title = String(invoice.invoice_number || '');

        const style = doc.createElement('style');
        const pageMargin = format.startsWith('thermal') ? '2mm' : '10mm';
        const embeddedStyles = content.querySelector('style')?.textContent || '';
        style.textContent =
            '* { margin: 0; padding: 0; box-sizing: border-box; } ' +
            "body { font-family: 'Segoe UI', Tahoma, sans-serif; direction: " +
            (isRTL ? 'rtl' : 'ltr') + '; } ' +
            '@page { size: ' + FORMATS[format].width + ' auto; margin: ' + pageMargin + '; } ' +
            '@media print { .no-print { display: none !important; } } ' +
            embeddedStyles;
        doc.head.appendChild(style);

        // SEC-C4a: Sanitize via DOMPurify. Even though React escapes its own
        // output, we defensively strip any HTML that may have been injected
        // via server-side data or a future bug.
        const wrapper = doc.createElement('div');
        wrapper.innerHTML = DOMPurify.sanitize(content.innerHTML, { USE_PROFILES: { html: true } });
        doc.body.appendChild(wrapper);

        setTimeout(() => { win.print(); win.close(); }, 300);
    };

    const lines = invoice.items || invoice.lines || [];
    const companyName = invoice.company_name || 'AMAN ERP';
    const companyVAT = invoice.company_vat || invoice.tax_id || '';

    const renderA4 = () => (
        <div style={{ padding: 32, fontFamily: "'Segoe UI', Tahoma, sans-serif", fontSize: 14, maxWidth: 800, margin: 'auto' }}>
            <style>{`.inv-tbl { width: 100%; border-collapse: collapse; margin: 16px 0; } .inv-tbl th, .inv-tbl td { border: 1px solid #ddd; padding: 8px 12px; text-align: ${isRTL ? 'right' : 'left'}; } .inv-tbl th { background: #f3f4f6; font-weight: 600; }`}</style>
            <div style={{ display: 'flex', justifyContent: 'space-between', borderBottom: '3px solid #2563eb', paddingBottom: 16, marginBottom: 24 }}>
                <div><h1 style={{ fontSize: 24, color: '#2563eb' }}>{companyName}</h1>{companyVAT && <p style={{ color: '#666' }}>{t('sales.print.vat_no', 'الرقم الضريبي')}: {companyVAT}</p>}</div>
                <div style={{ textAlign: isRTL ? 'left' : 'right' }}>
                    <h2 style={{ fontSize: 20 }}>{t('sales.invoices.title', 'فاتورة مبيعات')}</h2>
                    <p style={{ fontSize: 18, fontWeight: 700, color: '#2563eb' }}>{invoice.invoice_number}</p>
                </div>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 24, marginBottom: 24 }}>
                <div>
                    <h4 style={{ color: '#666', marginBottom: 4 }}>{t('sales.invoices.details.customer', 'العميل')}</h4>
                    <p style={{ fontWeight: 600 }}>{invoice.customer_name}</p>
                </div>
                <div style={{ textAlign: isRTL ? 'left' : 'right' }}>
                    <p>{t('sales.invoices.details.date', 'التاريخ')}: <strong>{formatShortDate(invoice.invoice_date)}</strong></p>
                    <p>{t('sales.invoices.details.due_date', 'تاريخ الاستحقاق')}: <strong>{invoice.due_date ? formatShortDate(invoice.due_date) : '-'}</strong></p>
                    {invoice.payment_method && <p>{t('sales.invoices.payment_method', 'طريقة الدفع')}: <strong>{invoice.payment_method}</strong></p>}
                </div>
            </div>
            <table className="inv-tbl">
                <thead><tr><th>#</th><th>{t('common.description', 'الوصف')}</th><th>{t('common.qty', 'الكمية')}</th><th>{t('common.unit_price', 'السعر')}</th><th>{t('common.tax', 'الضريبة')}</th><th>{t('common.total', 'الإجمالي')}</th></tr></thead>
                <tbody>
                    {lines.map((line, i) => (
                        <tr key={i}><td>{i + 1}</td><td>{line.description || line.product_name}</td><td>{line.quantity}</td><td>{formatNumber(line.unit_price)} {currency}</td><td>{line.tax_rate}%</td><td>{formatNumber(line.total)} {currency}</td></tr>
                    ))}
                </tbody>
            </table>
            <div style={{ display: 'flex', justifyContent: 'flex-end', marginTop: 16 }}>
                <div style={{ minWidth: 250, border: '1px solid #ddd', borderRadius: 8, padding: 16 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}><span>{t('common.subtotal', 'المجموع الفرعي')}</span><strong>{formatNumber(invoice.subtotal)} {currency}</strong></div>
                    {isPositiveDecimalString(invoice.discount) && <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8, color: '#dc2626' }}><span>{t('common.discount', 'الخصم')}</span><strong>-{formatNumber(invoice.discount)} {currency}</strong></div>}
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 8 }}><span>{t('common.tax', 'الضريبة')}</span><strong>{formatNumber(invoice.tax_amount)} {currency}</strong></div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', borderTop: '2px solid #2563eb', paddingTop: 8, fontSize: 18 }}><strong>{t('common.total', 'الإجمالي')}</strong><strong style={{ color: '#2563eb' }}>{formatNumber(invoice.total)} {currency}</strong></div>
                </div>
            </div>
            {invoice.notes && <div style={{ marginTop: 24, padding: 12, background: '#f9fafb', borderRadius: 8 }}><strong>{t('common.notes', 'ملاحظات')}:</strong> {invoice.notes}</div>}
        </div>
    );

    const renderThermal = (width) => {
        const isSmall = width === '58mm';
        const fs = isSmall ? 10 : 12;
        return (
            <div style={{ padding: isSmall ? 4 : 8, fontFamily: "'Courier New', monospace", fontSize: fs, width: width === '80mm' ? 300 : 220, margin: 'auto' }}>
                <style>{`.th-tbl { width: 100%; border-collapse: collapse; } .th-tbl td { padding: 2px 0; font-size: ${fs}px; } .th-sep { border-top: 1px dashed #000; margin: 4px 0; }`}</style>
                <div style={{ textAlign: 'center', marginBottom: 8 }}>
                    <strong style={{ fontSize: fs + 2 }}>{companyName}</strong>
                    {companyVAT && <div style={{ fontSize: fs - 2 }}>{t('sales.print.vat_no', 'الرقم الضريبي')}: {companyVAT}</div>}
                </div>
                <div className="th-sep" />
                <div style={{ textAlign: 'center', fontWeight: 700 }}>{t('sales.invoices.title', 'فاتورة')} {invoice.invoice_number}</div>
                <div style={{ fontSize: fs - 1 }}>{formatShortDate(invoice.invoice_date)}</div>
                <div style={{ fontSize: fs - 1 }}>{invoice.customer_name}</div>
                <div className="th-sep" />
                <table className="th-tbl">
                    <tbody>
                        {lines.map((line, i) => (
                            <tr key={i}>
                                <td style={{ maxWidth: isSmall ? 110 : 160, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{line.description || line.product_name}</td>
                                <td style={{ textAlign: 'center' }}>{line.quantity}x</td>
                                <td style={{ textAlign: isRTL ? 'left' : 'right' }}>{formatNumber(line.total)}</td>
                            </tr>
                        ))}
                    </tbody>
                </table>
                <div className="th-sep" />
                <table className="th-tbl"><tbody>
                    <tr><td>{t('common.subtotal', 'المجموع')}</td><td style={{ textAlign: isRTL ? 'left' : 'right' }}>{formatNumber(invoice.subtotal)}</td></tr>
                    {isPositiveDecimalString(invoice.tax_amount) && <tr><td>{t('common.tax', 'الضريبة')}</td><td style={{ textAlign: isRTL ? 'left' : 'right' }}>{formatNumber(invoice.tax_amount)}</td></tr>}
                    {isPositiveDecimalString(invoice.discount) && <tr><td>{t('common.discount', 'الخصم')}</td><td style={{ textAlign: isRTL ? 'left' : 'right' }}>-{formatNumber(invoice.discount)}</td></tr>}
                </tbody></table>
                <div className="th-sep" />
                <div style={{ display: 'flex', justifyContent: 'space-between', fontWeight: 700, fontSize: fs + 2 }}>
                    <span>{t('common.total', 'الإجمالي')}</span><span>{formatNumber(invoice.total)} {currency}</span>
                </div>
                <div className="th-sep" />
                <div style={{ textAlign: 'center', fontSize: fs - 2, marginTop: 8 }}>{t('sales.print.thank_you', 'شكراً لتعاملكم معنا')}</div>
            </div>
        );
    };

    const renderZATCA = () => (
        <div style={{ padding: 32, fontFamily: "'Segoe UI', Tahoma, sans-serif", fontSize: 14, maxWidth: 800, margin: 'auto' }}>
            <style>{`.inv-tbl { width: 100%; border-collapse: collapse; margin: 16px 0; } .inv-tbl th, .inv-tbl td { border: 1px solid #ddd; padding: 8px 12px; text-align: ${isRTL ? 'right' : 'left'}; } .inv-tbl th { background: #f3f4f6; font-weight: 600; }`}</style>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', borderBottom: '3px solid #1e3a5f', paddingBottom: 16, marginBottom: 16 }}>
                <div><h1 style={{ fontSize: 22, color: '#1e3a5f' }}>{companyName}</h1><p style={{ color: '#666' }}>{t('sales.print.vat_no', 'الرقم الضريبي')}: {companyVAT || 'N/A'}</p></div>
                <div style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: 12, color: '#1e3a5f', fontWeight: 700 }}>{t('sales.print.zatca_simplified', 'فاتورة ضريبية مبسطة')}</div>
                    <div style={{ fontSize: 10, color: '#666' }}>Simplified Tax Invoice</div>
                </div>
                <div style={{ textAlign: isRTL ? 'left' : 'right' }}>
                    <p style={{ fontSize: 16, fontWeight: 700 }}>{invoice.invoice_number}</p>
                    <p>{formatShortDate(invoice.invoice_date)}</p>
                </div>
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16, marginBottom: 16, padding: 12, background: '#f8fafc', borderRadius: 8 }}>
                <div><strong>{t('sales.print.seller', 'البائع')}:</strong> {companyName}<br />{t('sales.print.vat_no')}: {companyVAT || '-'}</div>
                <div><strong>{t('sales.print.buyer', 'المشتري')}:</strong> {invoice.customer_name}<br />{invoice.customer_vat && <>{t('sales.print.vat_no')}: {invoice.customer_vat}</>}</div>
            </div>
            <table className="inv-tbl">
                <thead><tr><th>#</th><th>{t('common.description', 'الوصف')}</th><th>{t('common.qty', 'الكمية')}</th><th>{t('common.unit_price', 'سعر الوحدة')}</th><th>{t('common.tax_rate', 'نسبة الضريبة')}</th><th>{t('common.tax', 'الضريبة')}</th><th>{t('common.total', 'الإجمالي')}</th></tr></thead>
                <tbody>
                    {lines.map((line, i) => {
                        return <tr key={i}><td>{i + 1}</td><td>{line.description || line.product_name}</td><td>{line.quantity}</td><td>{formatNumber(line.unit_price)}</td><td>{line.tax_rate || 0}%</td><td>{formatNumber(line.tax_amount)}</td><td>{formatNumber(line.total)}</td></tr>;
                    })}
                </tbody>
            </table>
            <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                <div style={{ minWidth: 280, border: '2px solid #1e3a5f', borderRadius: 8, padding: 16 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}><span>{t('sales.print.taxable_amount', 'المبلغ الخاضع للضريبة')}</span><strong>{formatNumber(invoice.taxable_amount)} {currency}</strong></div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}><span>{t('sales.print.vat_amount', 'مبلغ الضريبة')}</span><strong>{formatNumber(invoice.tax_amount)} {currency}</strong></div>
                    <div style={{ display: 'flex', justifyContent: 'space-between', borderTop: '2px solid #1e3a5f', paddingTop: 8, fontSize: 18 }}><strong>{t('sales.print.total_with_vat', 'الإجمالي شامل الضريبة')}</strong><strong style={{ color: '#1e3a5f' }}>{formatNumber(invoice.total)} {currency}</strong></div>
                </div>
            </div>
            <div style={{ marginTop: 24, padding: 12, background: '#f0f9ff', borderRadius: 8, border: '1px solid #bae6fd', fontSize: 11, textAlign: 'center' }}>
                <strong>{t('sales.print.zatca_notice', 'هذه الفاتورة صادرة وفقاً لمتطلبات هيئة الزكاة والضريبة والجمارك')}</strong>
            </div>
        </div>
    );

    const renderContent = () => {
        switch (format) {
            case 'thermal80': return renderThermal('80mm');
            case 'thermal58': return renderThermal('58mm');
            case 'zatca': return renderZATCA();
            default: return renderA4();
        }
    };

    return (
        <div className="modal-backdrop" onClick={onClose}>
            <div className="modal-dialog modal-lg" onClick={e => e.stopPropagation()} style={{ maxWidth: format.startsWith('thermal') ? 400 : 900, maxHeight: '90vh', overflow: 'auto' }}>
                <div className="modal-header">
                    <h3>{t('sales.print.title', 'طباعة الفاتورة')}</h3>
                    <button className="btn-icon" onClick={onClose}><X size={20} /></button>
                </div>
                <div style={{ padding: '12px 16px', borderBottom: '1px solid var(--border-color)', display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                    {Object.entries(FORMATS).map(([key, val]) => (
                        <button key={key} className={`btn ${format === key ? 'btn-primary' : 'btn-outline'}`} onClick={() => setFormat(key)} style={{ display: 'flex', gap: 4, alignItems: 'center' }}>
                            {val.icon} {val.label}
                        </button>
                    ))}
                    <div style={{ flex: 1 }} />
                    <button className="btn btn-primary" onClick={handlePrint}><Printer size={16} /> {t('common.print', 'طباعة')}</button>
                </div>
                <div className="modal-body" style={{ background: '#f3f4f6', padding: 16, maxHeight: '60vh', overflow: 'auto' }}>
                    <div ref={printRef} style={{ background: '#fff', borderRadius: 8, padding: 8, boxShadow: '0 1px 3px rgba(0,0,0,0.1)' }}>
                        {renderContent()}
                    </div>
                </div>
            </div>
        </div>
    );
};

export default InvoicePrintModal;
