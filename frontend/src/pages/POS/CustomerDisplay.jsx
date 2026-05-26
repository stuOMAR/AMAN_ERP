import { useState, useEffect, useRef } from 'react';
import { useTranslation } from 'react-i18next';
import DOMPurify from 'dompurify';
import { formatNumber } from '../../utils/format';
import { getCurrency } from '../../utils/auth';
import '../../components/ModuleStyles.css';
import BackButton from '../../components/common/BackButton';

// T2.7: HTML-escape user-controlled strings before injecting into the
// customer-display popup. Cart item names come from the products table
// (operator-editable) so a crafted product name like
// `<img src=x onerror=...>` would otherwise execute in the popup window
// where it can read the parent's localStorage / cookies.
function escapeHtml(value) {
    if (value === null || value === undefined) return '';
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

/**
 * POS-005: Customer Display + Cash Drawer Control
 * Shows a customer-facing display preview and cash drawer management
 * Uses BroadcastChannel API for live cart updates from POSInterface
 */

function CustomerDisplay() {
    const { t } = useTranslation();
    const currency = getCurrency();
    const displayWindowRef = useRef(null);
    const channelRef = useRef(null);

    const [config, setConfig] = useState({
        displayEnabled: false,
        showLogo: true,
        welcomeMessage: 'مرحباً بكم في أمان',
        thankYouMessage: 'شكراً لتعاملكم معنا',
        idleMessage: 'أجود المنتجات بأفضل الأسعار',
        fontSize: 'large',
        theme: 'dark',
        drawerMode: 'auto', // auto, manual, disabled
        drawerPin: 'pin2',
    });

    const [displayState, setDisplayState] = useState('welcome'); // welcome, scanning, total, thankYou
    const [currentItem, setCurrentItem] = useState(null);
    const [cartItems, setCartItems] = useState([]);
    const [total, setTotal] = useState(0);
    const [liveConnected, setLiveConnected] = useState(false);
    const [drawerLog, setDrawerLog] = useState([
        { time: '10:30:00', reason: 'بيع', amount: 97.75, user: 'أحمد' },
        { time: '09:15:00', reason: 'فتح الصندوق', amount: 500, user: 'محمد' },
    ]);

    // BroadcastChannel: receive live cart updates from POSInterface
    useEffect(() => {
        try {
            channelRef.current = new BroadcastChannel('pos_customer_display');
            setLiveConnected(true);

            channelRef.current.onmessage = (event) => {
                const data = event.data;
                if (data.type === 'cart_update') {
                    setCartItems(data.items || []);
                    setTotal(data.totals?.total || 0);
                    setDisplayState(data.items?.length > 0 ? 'scanning' : 'welcome');
                } else if (data.type === 'thankYou') {
                    setDisplayState('thankYou');
                    setTimeout(() => {
                        setCartItems([]);
                        setTotal(0);
                        setDisplayState('welcome');
                    }, 5000);
                } else if (data.type === 'idle') {
                    setCartItems([]);
                    setTotal(0);
                    setDisplayState('welcome');
                }

                // Auto-update the popup window if open
                if (displayWindowRef.current && !displayWindowRef.current.closed) {
                    updateDisplayWindow(displayWindowRef.current);
                }
            };
        } catch (e) {
            console.warn('BroadcastChannel not supported');
        }

        return () => { if (channelRef.current) channelRef.current.close(); };
    }, []);



    const openCustomerDisplay = () => {
        if (displayWindowRef.current && !displayWindowRef.current.closed) {
            displayWindowRef.current.focus();
            return;
        }
        const win = window.open('', 'customer_display', 'width=800,height=480,menubar=no,toolbar=no,location=no');
        displayWindowRef.current = win;
        updateDisplayWindow(win);
    };

    const updateDisplayWindow = (win) => {
        if (!win || win.closed) return;
        const isDark = config.theme === 'dark';
        const bg = isDark ? '#1a1a2e' : '#ffffff';
        const fg = isDark ? '#e0e0e0' : '#1a1a2e';
        const accent = '#4f46e5';

        // T2.7: Build content with HTML-escaped variables, then sanitize the
        // final body via DOMPurify before injection. We escape `cartItems[i].name`,
        // `config.welcomeMessage`, `config.idleMessage`, and `config.thankYouMessage`
        // because those values originate from operator input or the products table.
        const safeAccent = escapeHtml(accent);
        let content = '';
        if (displayState === 'welcome') {
            content = `
                <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;gap:20px;">
                    <div style="font-size:48px;">🛒</div>
                    <div style="font-size:32px;font-weight:700;color:${safeAccent}">${escapeHtml(config.welcomeMessage)}</div>
                    <div style="font-size:18px;opacity:0.7">${escapeHtml(config.idleMessage)}</div>
                </div>
            `;
        } else if (displayState === 'scanning') {
            const itemsHtml = cartItems.map(i => {
                const qty = i.qty || i.quantity || 1;
                const lineTotal = i.total;
                return `
                <div style="display:flex;justify-content:space-between;padding:8px 0;border-bottom:1px solid ${isDark ? '#333' : '#eee'}">
                    <span>${escapeHtml(i.name)} × ${escapeHtml(qty)}</span>
                    <span>${lineTotal ? escapeHtml(formatNumber(lineTotal)) + ' ' + escapeHtml(currency) : '—'}</span>
                </div>
            `;
            }).join('');
            content = `
                <div style="padding:30px;">
                    <div style="font-size:20px;font-weight:600;margin-bottom:20px;">${escapeHtml(t('pos.items_added', 'العناصر المُضافة'))}</div>
                    ${itemsHtml}
                    <div style="display:flex;justify-content:space-between;margin-top:20px;padding-top:16px;border-top:3px solid ${safeAccent};font-size:28px;font-weight:700;">
                        <span>${escapeHtml(t('pos.receipt.total', 'الإجمالي'))}</span>
                        <span style="color:${safeAccent}">${escapeHtml(formatNumber(total))} ${escapeHtml(currency)}</span>
                    </div>
                </div>
            `;
        } else if (displayState === 'total') {
            content = `
                <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;gap:16px;">
                    <div style="font-size:24px;opacity:0.7">${escapeHtml(t('pos.receipt.amount_due', 'المبلغ المستحق'))}</div>
                    <div style="font-size:64px;font-weight:700;color:${safeAccent}">${escapeHtml(formatNumber(total))} ${escapeHtml(currency)}</div>
                    <div style="font-size:18px;opacity:0.5">${escapeHtml(cartItems.length)} عناصر</div>
                </div>
            `;
        } else {
            content = `
                <div style="display:flex;flex-direction:column;align-items:center;justify-content:center;height:100vh;gap:20px;">
                    <div style="font-size:64px;">✅</div>
                    <div style="font-size:32px;font-weight:700;color:#10b981">${escapeHtml(config.thankYouMessage)}</div>
                </div>
            `;
        }

        // Write a static skeleton (DOCTYPE + head + style — no dynamic data),
        // then populate body via sanitized innerHTML. DOMPurify strips any
        // <script>, on*= handlers, javascript: URIs, etc.
        const safeBg = escapeHtml(bg);
        const safeFg = escapeHtml(fg);
        win.document.open();
        win.document.write(
            `<!DOCTYPE html><html dir="rtl"><head><title>شاشة العميل</title>` +
            `<style>*{margin:0;padding:0;box-sizing:border-box;} body{font-family:'Segoe UI',Tahoma,sans-serif;background:${safeBg};color:${safeFg};overflow:hidden;}</style>` +
            `</head><body></body></html>`
        );
        win.document.close();
        win.document.body.innerHTML = DOMPurify.sanitize(content, { ADD_ATTR: ['style'] });
    };

    useEffect(() => {
        if (displayWindowRef.current && !displayWindowRef.current.closed) {
            updateDisplayWindow(displayWindowRef.current);
        }
    }, [displayState, cartItems, config]);

    const handleOpenDrawer = () => {
        const now = new Date().toLocaleTimeString('ar-SA');
        setDrawerLog(prev => [{ time: now, reason: 'فتح يدوي', amount: 0, user: 'المستخدم' }, ...prev]);
    };

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">📺 {t('pos.customer_display.title', 'شاشة العميل ودرج النقود')}</h1>
                    <p className="workspace-subtitle">{t('pos.customer_display.subtitle', 'إعدادات العرض للعميل والتحكم بدرج النقود')}</p>
                </div>
                <div className="header-actions">
                    {liveConnected && (
                        <span style={{ display: 'inline-flex', alignItems: 'center', gap: 6, padding: '4px 12px', borderRadius: 20, background: 'rgba(16,185,129,0.12)', color: '#10b981', fontSize: 12, fontWeight: 600 }}>
                            🟢 {t('pos.customer_display.live', 'متصل مباشرة')}
                        </span>
                    )}
                    <button className="btn btn-primary" onClick={openCustomerDisplay}>📺 {t('pos.customer_display.open', 'فتح شاشة العميل')}</button>
                </div>
            </div>

            <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 16 }}>
                {/* Display Settings */}
                <div className="section-card">
                    <h3 className="section-title">{t('pos.customer_display.display_settings', 'إعدادات العرض')}</h3>
                    <div className="form-grid">
                        <div className="form-group">
                            <label className="form-label">{t('pos.customer_display.theme', 'السمة')}</label>
                            <select className="form-input" value={config.theme} onChange={e => setConfig(p => ({ ...p, theme: e.target.value }))}>
                                <option value="dark">{t('pos.customer_display.dark', 'داكنة')}</option>
                                <option value="light">{t('pos.customer_display.light', 'فاتحة')}</option>
                            </select>
                        </div>
                        <div className="form-group">
                            <label className="form-label">{t('pos.customer_display.welcome_msg', 'رسالة الترحيب')}</label>
                            <input className="form-input" value={config.welcomeMessage} onChange={e => setConfig(p => ({ ...p, welcomeMessage: e.target.value }))} />
                        </div>
                        <div className="form-group">
                            <label className="form-label">{t('pos.customer_display.thank_msg', 'رسالة الشكر')}</label>
                            <input className="form-input" value={config.thankYouMessage} onChange={e => setConfig(p => ({ ...p, thankYouMessage: e.target.value }))} />
                        </div>
                        <div className="form-group">
                            <label className="form-label">{t('pos.customer_display.idle_msg', 'رسالة الانتظار')}</label>
                            <input className="form-input" value={config.idleMessage} onChange={e => setConfig(p => ({ ...p, idleMessage: e.target.value }))} />
                        </div>
                    </div>
                </div>

                {/* Display State Preview */}
                <div className="section-card">
                    <h3 className="section-title">{t('pos.customer_display.preview', 'معاينة حالة العرض')}</h3>
                    <div style={{ display: 'flex', gap: 8, marginBottom: 12, flexWrap: 'wrap' }}>
                        {[
                            { key: 'welcome', label: 'ترحيب', icon: '👋' },
                            { key: 'scanning', label: 'مسح', icon: '📦' },
                            { key: 'total', label: 'إجمالي', icon: '💰' },
                            { key: 'thankYou', label: 'شكراً', icon: '✅' },
                        ].map(s => (
                            <button key={s.key} className={`btn ${displayState === s.key ? 'btn-primary' : 'btn-secondary'}`}
                                onClick={() => setDisplayState(s.key)}>
                                {s.icon} {s.label}
                            </button>
                        ))}
                    </div>
                    <div style={{
                        background: config.theme === 'dark' ? '#1a1a2e' : '#f8f8f8',
                        color: config.theme === 'dark' ? '#e0e0e0' : '#1a1a2e',
                        borderRadius: 12, padding: 20, minHeight: 200, textAlign: 'center',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        border: '2px solid #4f46e5'
                    }}>
                        {displayState === 'welcome' && (
                            <div>
                                <div style={{ fontSize: 36 }}>🛒</div>
                                <div style={{ fontSize: 22, fontWeight: 700, color: '#4f46e5', marginTop: 8 }}>{config.welcomeMessage}</div>
                                <div style={{ fontSize: 14, opacity: 0.7, marginTop: 4 }}>{config.idleMessage}</div>
                            </div>
                        )}
                        {displayState === 'scanning' && (
                            <div style={{ width: '100%', textAlign: 'right', padding: '0 10px' }}>
                                {cartItems.length === 0 ? (
                                    <div style={{ opacity: 0.5 }}>{t('pos.customer_display.no_items', 'لا توجد عناصر - سيتم التحديث تلقائياً من نقطة البيع')}</div>
                                ) : cartItems.map((item, i) => (
                                    <div key={i} style={{ display: 'flex', justifyContent: 'space-between', padding: '4px 0', borderBottom: '1px solid rgba(128,128,128,0.2)' }}>
                                        <span>{item.name} × {item.qty || item.quantity || 1}</span>
                                        <span>{formatNumber(item.total || (item.price * (item.qty || item.quantity || 1)))}</span>
                                    </div>
                                ))}
                                <div style={{ display: 'flex', justifyContent: 'space-between', marginTop: 8, fontWeight: 700, fontSize: 18, color: '#4f46e5' }}>
                                    <span>{t('pos.receipt.total')}</span><span>{formatNumber(total)} {currency}</span>
                                </div>
                            </div>
                        )}
                        {displayState === 'total' && (
                            <div>
                                <div style={{ fontSize: 14, opacity: 0.7 }}>{t('pos.receipt.amount_due')}</div>
                                <div style={{ fontSize: 42, fontWeight: 700, color: '#4f46e5' }}>{formatNumber(total)} {currency}</div>
                            </div>
                        )}
                        {displayState === 'thankYou' && (
                            <div>
                                <div style={{ fontSize: 36 }}>✅</div>
                                <div style={{ fontSize: 22, fontWeight: 700, color: '#10b981', marginTop: 8 }}>{config.thankYouMessage}</div>
                            </div>
                        )}
                    </div>
                </div>

                {/* Cash Drawer */}
                <div className="section-card">
                    <h3 className="section-title">💰 {t('pos.cash_drawer.title', 'درج النقود')}</h3>
                    <div className="form-grid">
                        <div className="form-group">
                            <label className="form-label">{t('pos.cash_drawer.mode', 'وضع الفتح')}</label>
                            <select className="form-input" value={config.drawerMode} onChange={e => setConfig(p => ({ ...p, drawerMode: e.target.value }))}>
                                <option value="auto">{t('pos.cash_drawer.auto', 'تلقائي بعد كل بيع نقدي')}</option>
                                <option value="manual">{t('pos.cash_drawer.manual', 'يدوي فقط')}</option>
                                <option value="disabled">{t('pos.cash_drawer.disabled', 'معطّل')}</option>
                            </select>
                        </div>
                        <div className="form-group">
                            <label className="form-label">{t('pos.cash_drawer.pin', 'منفذ الدرج')}</label>
                            <select className="form-input" value={config.drawerPin} onChange={e => setConfig(p => ({ ...p, drawerPin: e.target.value }))}>
                                <option value="pin2">Pin 2 (RJ11)</option>
                                <option value="pin5">Pin 5 (RJ11)</option>
                            </select>
                        </div>
                    </div>
                    <button className="btn btn-primary" style={{ marginTop: 12 }} onClick={handleOpenDrawer} disabled={config.drawerMode === 'disabled'}>
                        💰 {t('pos.cash_drawer.open_btn', 'فتح الدرج الآن')}
                    </button>
                </div>

                {/* Drawer Log */}
                <div className="section-card">
                    <h3 className="section-title">{t('pos.cash_drawer.log', 'سجل فتح الدرج')}</h3>
                    <table className="data-table">
                        <thead>
                            <tr>
                                <th>{t('common.time', 'الوقت')}</th>
                                <th>{t('pos.cash_drawer.reason', 'السبب')}</th>
                                <th>{t('common.amount', 'المبلغ')}</th>
                                <th>{t('common.user', 'المستخدم')}</th>
                            </tr>
                        </thead>
                        <tbody>
                            {drawerLog.map((log, i) => (
                                <tr key={i}>
                                    <td>{log.time}</td>
                                    <td>{log.reason}</td>
                                    <td>{log.amount > 0 ? formatNumber(log.amount) : '-'}</td>
                                    <td>{log.user}</td>
                                </tr>
                            ))}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
}

export default CustomerDisplay;
