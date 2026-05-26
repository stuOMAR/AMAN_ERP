import React, { useEffect, useState, useMemo, useRef } from 'react';
import './POSInterface.css';
import './components/POSComponents.css';
import { useNavigate } from 'react-router-dom';
import api from '../../utils/api';
import { useTranslation } from 'react-i18next';
import { useToast } from '../../context/ToastContext';
import { getCurrency, logout } from '../../utils/auth';
import HeldOrders from './components/HeldOrders';
import POSReturns from './components/POSReturns';
import LazyImage from '../../components/common/LazyImage';
import { savePendingOrder } from './POSOfflineManager';
import { generateReceiptText } from './ThermalPrintSettings';
import {
    Search, RefreshCcw, Home, LogOut,
    ShoppingCart, Plus, Minus,
    Store, X, Wifi, WifiOff,
    Banknote, CreditCard as CardIcon, Split,
    UserCircle, Printer,
    Clock, LayoutGrid, ArrowRightLeft, Smartphone, Package, RotateCcw
} from 'lucide-react';
import { formatShortDate } from '../../utils/dateUtils';
import { formatNumber } from '../../utils/format';
import Decimal from 'decimal.js';

const parseDecimalInput = (value) => {
    if (value === null || value === undefined || value === '') return null;
    try {
        const decimal = new Decimal(value);
        return decimal.isFinite() ? decimal : null;
    } catch {
        return null;
    }
};

const decimalOrZero = (value) => parseDecimalInput(value) || new Decimal('0');
const decimalString = (value) => decimalOrZero(value).toString();
const fallbackUuid = () => {
    const seed = `${Date.now().toString(16)}${Math.random().toString(16).slice(2)}`.padEnd(32, '0').slice(0, 32);
    return `${seed.slice(0, 8)}-${seed.slice(8, 12)}-4${seed.slice(13, 16)}-8${seed.slice(17, 20)}-${seed.slice(20, 32)}`;
};
const newClientOperationId = () => (
    (typeof window !== 'undefined' && window.crypto?.randomUUID?.()) || fallbackUuid()
);

const POSInterface = () => {
    const { t, i18n } = useTranslation();
    const { showToast } = useToast();
    const navigate = useNavigate();
    const isRTL = i18n.dir() === 'rtl';

    // --- State ---
    const [session, setSession] = useState(null);
    const [products, setProducts] = useState([]);
    const [filteredProducts, setFilteredProducts] = useState([]);
    const [searchQuery, setSearchQuery] = useState('');
    const [loading, setLoading] = useState(true);
    const currency = getCurrency(); // Use the same method as other pages
    const [currentTime, setCurrentTime] = useState(new Date());

    // Modal states
    const [showHeldOrders, setShowHeldOrders] = useState(false);
    const [showReturns, setShowReturns] = useState(false);
    const [showCloseSession, setShowCloseSession] = useState(false);
    const [closingData, setClosingData] = useState({ cashCount: '', notes: '' });

    const [cart, setCart] = useState([]);
    const [customers, setCustomers] = useState([]);
    const [selectedCustomer, setSelectedCustomer] = useState(null);
    const [globalDiscount, setGlobalDiscount] = useState('');
    const [orderPreview, setOrderPreview] = useState(null);
    const [previewLoading, setPreviewLoading] = useState(false);

    const [showPaymentModal, setShowPaymentModal] = useState(false);
    const [paymentAmounts, setPaymentAmounts] = useState({ cash: '', card: '', mada: '' });
    const [submitting, setSubmitting] = useState(false);

    // --- Offline Mode (B7) ---
    const [isOnline, setIsOnline] = useState(navigator.onLine);
    const [offlinePendingCount, setOfflinePendingCount] = useState(0);

    // --- Customer Display Broadcast (B7) ---
    const broadcastRef = useRef(null);

    // --- Effects ---
    useEffect(() => {
        initPOS();
        fetchCustomers();
        const timer = setInterval(() => setCurrentTime(new Date()), 1000);

        // Offline detection
        const goOnline = () => { setIsOnline(true); showToast(t('pos.online_restored', 'تم استعادة الاتصال'), 'success'); };
        const goOffline = () => { setIsOnline(false); showToast(t('pos.offline_mode', 'وضع عدم الاتصال - سيتم حفظ الطلبات محلياً'), 'warning'); };
        window.addEventListener('online', goOnline);
        window.addEventListener('offline', goOffline);

        // BroadcastChannel for Customer Display
        try {
            broadcastRef.current = new BroadcastChannel('pos_customer_display');
        } catch (e) { /* BroadcastChannel not supported */ }

        return () => {
            clearInterval(timer);
            window.removeEventListener('online', goOnline);
            window.removeEventListener('offline', goOffline);
            if (broadcastRef.current) broadcastRef.current.close();
        };
    }, []);

    useEffect(() => {
        const productsArray = Array.isArray(products) ? products : [];
        if (!searchQuery) {
            setFilteredProducts(productsArray);
        } else {
            const lower = searchQuery.toLowerCase();
            const filtered = productsArray.filter(p =>
                (p.name || '').toLowerCase().includes(lower) ||
                (p.barcode && p.barcode.includes(lower)) ||
                (p.code && p.code.toLowerCase().includes(lower))
            );
            setFilteredProducts(filtered);
        }
    }, [searchQuery, products]);

    const buildOrderPayload = (payments = [], status = 'paid', preview = orderPreview, clientOrderId = null) => ({
        session_id: session?.id,
        ...(clientOrderId ? { client_order_id: clientOrderId } : {}),
        warehouse_id: session?.warehouse_id,
        customer_id: selectedCustomer?.id,
        items: cart.map(item => ({
            product_id: item.id,
            quantity: String(item.quantity),
            unit_price: String(item.price),
        })),
        discount_amount: decimalString(globalDiscount),
        paid_amount: '0',
        payments,
        status,
        submitted_grand_total: preview?.total_amount ? String(preview.total_amount) : null,
    });

    const fetchOrderPreview = async (payments = [], status = 'paid') => {
        if (!navigator.onLine || !session?.id || cart.length === 0) {
            setOrderPreview(null);
            return null;
        }
        const payload = buildOrderPayload(payments, status, null);
        const res = await api.post('/pos/orders/preview', payload);
        setOrderPreview(res.data);
        return res.data;
    };

    // --- Cart Totals ---
    const cartTotals = useMemo(() => ({
        subtotal: orderPreview?.subtotal ?? null,
        discount: orderPreview?.discount_amount ?? null,
        tax: orderPreview?.tax_amount ?? null,
        total: orderPreview?.total_amount ?? null,
        remaining: orderPreview?.remaining_amount ?? null,
    }), [orderPreview]);

    const hasPreviewTotals = Boolean(cartTotals.total);
    const displayMoney = (value) => (value === null || value === undefined || value === '' ? '—' : formatNumber(value));
    const previewLineTotal = (productId) => orderPreview?.lines?.find(line => line.product_id === productId)?.total ?? null;

    useEffect(() => {
        if (!isOnline || !session?.id || cart.length === 0) {
            setOrderPreview(null);
            return;
        }
        let cancelled = false;
        const timer = setTimeout(async () => {
            setPreviewLoading(true);
            try {
                const res = await api.post('/pos/orders/preview', buildOrderPayload([], 'paid', null));
                if (!cancelled) setOrderPreview(res.data);
            } catch (e) {
                if (!cancelled) setOrderPreview(null);
            } finally {
                if (!cancelled) setPreviewLoading(false);
            }
        }, 250);
        return () => {
            cancelled = true;
            clearTimeout(timer);
        };
    }, [isOnline, session?.id, session?.warehouse_id, selectedCustomer?.id, cart, globalDiscount]);

    useEffect(() => {
        if (!showPaymentModal || !isOnline || !session?.id || cart.length === 0) return;
        let cancelled = false;
        const payments = [];
        if (decimalOrZero(paymentAmounts.cash).gt(0)) payments.push({ method: "cash", amount: decimalString(paymentAmounts.cash) });
        if (decimalOrZero(paymentAmounts.card).gt(0)) payments.push({ method: "bank", amount: decimalString(paymentAmounts.card), reference: "card" });
        if (decimalOrZero(paymentAmounts.mada).gt(0)) payments.push({ method: "bank", amount: decimalString(paymentAmounts.mada), reference: "mada" });
        const timer = setTimeout(async () => {
            try {
                const res = await api.post('/pos/orders/preview', buildOrderPayload(payments, 'paid', null));
                if (!cancelled) setOrderPreview(res.data);
            } catch (e) {
                if (!cancelled) setOrderPreview(null);
            }
        }, 200);
        return () => {
            cancelled = true;
            clearTimeout(timer);
        };
    }, [showPaymentModal, paymentAmounts, isOnline, session?.id, session?.warehouse_id, selectedCustomer?.id, cart, globalDiscount]);

    // Broadcast cart changes to Customer Display
    useEffect(() => {
        if (broadcastRef.current) {
            broadcastRef.current.postMessage({
                type: cart.length > 0 ? 'cart_update' : 'idle',
                items: cart.map(item => ({
                    name: item.name,
                    price: item.price,
                    quantity: item.quantity,
                    total: previewLineTotal(item.id)
                })),
                totals: cartTotals,
                currency
            });
        }
    }, [cart, cartTotals]);

    // --- Actions ---
    const refreshSession = async () => {
        try {
            const sessionRes = await api.get('/pos/sessions/active');
            if (sessionRes.data) {
                setSession(sessionRes.data);
            }
        } catch (e) {
            showToast(t('common.error_occurred'), 'error');
        }
    };

    const initPOS = async () => {
        try {
            const sessionRes = await api.get('/pos/sessions/active');
            if (!sessionRes.data) {
                navigate('/pos');
                return;
            }
            setSession(sessionRes.data);

            const productsRes = await api.get('/pos/products', {
                params: { warehouse_id: sessionRes.data.warehouse_id }
            });

            const fetchedProducts = Array.isArray(productsRes.data) ? productsRes.data : [];
            setProducts(fetchedProducts);
            setFilteredProducts(fetchedProducts);
            setLoading(false);
        } catch (error) {
            showToast(t('common.error_occurred'), "error");
            navigate('/dashboard');
        }
    };

    const fetchCustomers = async () => {
        try {
            const res = await api.get('/sales/customers');
            setCustomers(res.data);
        } catch (e) { showToast(t('common.error_occurred'), 'error'); }
    }

    // --- Cart Logic ---
    const addToCart = (product) => {
        setCart(prev => {
            const existing = prev.find(item => item.id === product.id);
            if (existing) {
                return prev.map(item => item.id === product.id ? { ...item, quantity: item.quantity + 1 } : item);
            } else {
                return [...prev, { ...product, quantity: 1, discount: 0 }];
            }
        });
    };

    const removeFromCart = (productId) => {
        setCart(prev => prev.filter(item => item.id !== productId));
    };

    const updateQuantity = (productId, delta) => {
        setCart(prev => prev.map(item => {
            if (item.id === productId) {
                const newQty = Math.max(1, item.quantity + delta);
                return { ...item, quantity: newQty };
            }
            return item;
        }));
    };


    // --- Checkout Logic ---
    const openSplitPayment = () => {
        setPaymentAmounts({ cash: '', card: '', mada: '' });
        setShowPaymentModal(true);
    }

    const quickPay = async (method) => {
        if (!hasPreviewTotals) {
            showToast(t('common.error_occurred'), 'warning');
            return;
        }
        const finalMethod = method === 'cash' ? 'cash' : 'bank';
        try {
            await processOrder([{ method: finalMethod, amount: cartTotals.total, reference: method }]);
        } catch (e) { }
    }

    const processOrder = async (payments, status = "paid") => {
        if (cart.length === 0) return;
        if (submitting) return; // Prevent double-submit
        setSubmitting(true);

        try {
            const authoritativePreview = navigator.onLine ? await fetchOrderPreview(payments, status) : null;

            if (navigator.onLine && !authoritativePreview) {
                showToast(t('common.error_occurred'), "warning");
                return;
            }

            if (status === 'paid' && navigator.onLine && decimalOrZero(authoritativePreview.remaining_amount).gt(0)) {
                showToast(t('pos.paid_amount_less'), "warning");
                return;
            }

            const idempotencyKey = newClientOperationId();
            const submittedPreview = authoritativePreview || orderPreview;
            const orderData = buildOrderPayload(
                status === 'paid' ? payments : [],
                status,
                submittedPreview,
                idempotencyKey
            );

            // Offline fallback: save to IndexedDB when no connection
            if (!navigator.onLine) {
                await savePendingOrder({ orderData, idempotencyKey });
                setOfflinePendingCount(prev => prev + 1);
                showToast(t('pos.order_saved_offline', 'تم حفظ الطلب محلياً - سيتم مزامنته عند عودة الاتصال'), 'warning');
            } else {
                await api.post('/pos/orders', orderData, { headers: { 'Idempotency-Key': idempotencyKey } });
                showToast(status === 'paid' ? t('pos.order_completed') : t('common.saved'), "success");
            }

            // Broadcast "thankYou" state to customer display
            if (broadcastRef.current) {
                broadcastRef.current.postMessage({ type: 'thankYou' });
            }

            setCart([]);
            setGlobalDiscount('');
            setShowPaymentModal(false);
            setSelectedCustomer(null);

            // Refresh session totals and product stock
            refreshSession();
            return true;
        } catch (error) {
            showToast(t('common.error_save'), "error");
            throw error;
        } finally {
            setSubmitting(false);
        }
    }

    const handleSplitCheckout = async () => {
        const latestPreview = await fetchOrderPreview([
            ...(decimalOrZero(paymentAmounts.cash).gt(0) ? [{ method: "cash", amount: decimalString(paymentAmounts.cash) }] : []),
            ...(decimalOrZero(paymentAmounts.card).gt(0) ? [{ method: "bank", amount: decimalString(paymentAmounts.card), reference: "card" }] : []),
            ...(decimalOrZero(paymentAmounts.mada).gt(0) ? [{ method: "bank", amount: decimalString(paymentAmounts.mada), reference: "mada" }] : []),
        ]);
        if (!latestPreview || decimalOrZero(latestPreview.remaining_amount).gt(0)) {
            showToast(t('pos.paid_amount_less'), "warning");
            return;
        }
        const payments = [];
        if (decimalOrZero(paymentAmounts.cash).gt(0)) payments.push({ method: "cash", amount: decimalString(paymentAmounts.cash) });
        if (decimalOrZero(paymentAmounts.card).gt(0)) payments.push({ method: "bank", amount: decimalString(paymentAmounts.card), reference: "card" });
        if (decimalOrZero(paymentAmounts.mada).gt(0)) payments.push({ method: "bank", amount: decimalString(paymentAmounts.mada), reference: "mada" });
        await processOrder(payments);
    };

    const fillPaymentAmount = async (target) => {
        const payments = [];
        if (target !== 'cash' && decimalOrZero(paymentAmounts.cash).gt(0)) {
            payments.push({ method: "cash", amount: decimalString(paymentAmounts.cash) });
        }
        if (target !== 'card' && decimalOrZero(paymentAmounts.card).gt(0)) {
            payments.push({ method: "bank", amount: decimalString(paymentAmounts.card), reference: "card" });
        }
        if (target !== 'mada' && decimalOrZero(paymentAmounts.mada).gt(0)) {
            payments.push({ method: "bank", amount: decimalString(paymentAmounts.mada), reference: "mada" });
        }
        const preview = await fetchOrderPreview(payments);
        setPaymentAmounts(p => ({ ...p, [target]: preview?.remaining_amount || '' }));
    };

    const handleHold = async () => {
        await processOrder([], 'hold');
    }

    const handleCloseSession = async () => {
        if (!closingData.cashCount) {
            showToast(t('pos.enter_cash_count'), 'error');
            return;
        }

        try {
            await api.post(`/pos/sessions/${session.id}/close`, {
                cash_register_balance: String(closingData.cashCount),
                closing_balance: String(session?.expected_cash || '0'),
                notes: closingData.notes
            });

            showToast(t('pos.session_closed'), 'success');
            setTimeout(() => {
                navigate('/pos');
            }, 1500);
        } catch (error) {
            showToast(error.response?.data?.detail || t('common.error'), 'error');
        }
    }

    // --- Loading State ---
    if (loading) {
        return (
            <div className="pos-loading">
                <RefreshCcw className="pos-loading-spinner" size={40} />
            </div>
        );
    }

    return (
        <div className="pos-container" dir={isRTL ? 'rtl' : 'ltr'}>

            {/* ========== HEADER ========== */}
            <header className="pos-header">

                {/* Brand */}
                <div className="pos-header-brand">
                    <button
                        onClick={() => navigate('/dashboard')}
                        className="brand-icon"
                    >
                        <Home size={18} />
                    </button>
                    <div className="brand-text">
                        <h1>{t('pos.title')}</h1>
                        <span>{t('pos.new_order')}</span>
                    </div>
                </div>

                <div className="pos-header-divider" />

                {/* Info Items */}
                <div className="pos-header-info">
                    {/* Invoice No */}
                    <div className="pos-info-item">
                        <div className="info-icon">
                            <LayoutGrid size={16} />
                        </div>
                        <div className="info-content">
                            <span className="info-label">{t('pos.invoice_no')}</span>
                            <span className="info-value">
                                {session?.session_code ? `${session.session_code}-${(session.order_count || 0) + 1}` : `NEW-${(session?.order_count || 0) + 1}`}
                            </span>
                        </div>
                    </div>

                    {/* Date/Time */}
                    <div className="pos-info-item">
                        <div className="info-icon">
                            <Clock size={16} />
                        </div>
                        <div className="info-content">
                            <span className="info-label">{t('pos.invoice_date')}</span>
                            <span className="info-value">
                                {formatShortDate(currentTime)}
                            </span>
                        </div>
                    </div>

                    {/* Warehouse */}
                    <div className="pos-info-item">
                        <div className="info-icon">
                            <Store size={16} />
                        </div>
                        <div className="info-content">
                            <span className="info-label">{t('pos.branch')}</span>
                            <span className="info-value">{session?.warehouse_name}</span>
                        </div>
                    </div>
                </div>

                {/* Search - Center */}
                <div className="pos-header-search">
                    <div className="pos-search-input">
                        <Search className="search-icon" size={18} />
                        <input
                            type="text"
                            placeholder={t('pos.scan_hint')}
                            value={searchQuery}
                            onChange={e => setSearchQuery(e.target.value)}
                            autoFocus
                        />
                    </div>
                </div>

                {/* Actions */}
                <div className="pos-header-actions">
                    {/* Online/Offline Indicator */}
                    <div className={`pos-connection-badge ${isOnline ? 'online' : 'offline'}`} title={isOnline ? t('pos.online', 'متصل') : t('pos.offline_mode', 'غير متصل')}>
                        {isOnline ? <Wifi size={14} /> : <WifiOff size={14} />}
                        <span>{isOnline ? t('pos.online', 'متصل') : t('pos.offline_short', 'غير متصل')}</span>
                        {offlinePendingCount > 0 && <span className="pending-badge">{offlinePendingCount}</span>}
                    </div>

                    {/* Customer Select */}
                    <div className="pos-customer-select">
                        <UserCircle className="select-icon" size={18} />
                        <select
                            onChange={(e) => setSelectedCustomer(customers.find(c => c.id === parseInt(e.target.value)) || null)}
                            value={selectedCustomer?.id || ""}
                        >
                            <option value="">{t('pos.walk_in_customer')}</option>
                            {customers.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                        </select>
                    </div>

                    {/* Hold Orders Button */}
                    <button
                        className="pos-action-btn"
                        onClick={() => setShowHeldOrders(true)}
                        title={t('pos.held_orders')}
                    >
                        <Clock size={18} />
                        <span>{t('pos.held_orders')}</span>
                    </button>

                    {/* Returns Button */}
                    <button
                        className="pos-action-btn"
                        onClick={() => setShowReturns(true)}
                        title={t('pos.returns')}
                    >
                        <RotateCcw size={18} />
                        <span>{t('pos.returns')}</span>
                    </button>

                    <button
                        onClick={initPOS}
                        className="pos-action-btn"
                        title={t('common.refresh')}
                    >
                        <RefreshCcw size={18} />
                    </button>

                    <button
                        onClick={() => setShowCloseSession(true)}
                        className="pos-action-btn warning"
                        title={t('pos.close_session')}
                    >
                        <Store size={18} />
                        <span>{t('pos.close_session')}</span>
                    </button>

                    <button
                        onClick={logout}
                        className="pos-action-btn danger"
                        title={t('common.logout')}
                    >
                        <LogOut size={18} />
                        <span>{t('common.logout')}</span>
                    </button>
                </div>
            </header>

            {/* ========== MAIN CONTENT ========== */}
            <div className="pos-main">

                {/* ===== PRODUCTS AREA ===== */}
                <main className="pos-products">
                    <div className="pos-products-grid">
                        {filteredProducts.length === 0 ? (
                            <div className="pos-empty-state">
                                <div className="empty-icon">
                                    <Package size={40} />
                                </div>
                                <p>{t('pos.no_products_found')}</p>
                            </div>
                        ) : (
                            <div className="products-grid">
                                {filteredProducts.map(product => (
                                    <div
                                        key={product.id}
                                        onClick={() => addToCart(product)}
                                        className="product-card"
                                    >
                                        <div className="product-card-image">
                                            {product.image_url ? (
                                                <LazyImage
                                                    src={product.image_url}
                                                    alt={product.name}
                                                    style={{ width: '100%', height: '100%', objectFit: 'cover' }}
                                                />
                                            ) : (
                                                <span className="placeholder-text">{product.name.charAt(0)}</span>
                                            )}
                                            <div className="product-stock-badge">
                                                {product.stock_quantity || 0}
                                            </div>
                                            <div className="product-add-overlay">
                                                <div className="add-icon">
                                                    <Plus size={24} strokeWidth={3} />
                                                </div>
                                            </div>
                                        </div>
                                        <div className="product-card-content">
                                            <h3 className="product-card-name" title={product.name}>{product.name}</h3>
                                            <div className="product-card-price">
                                                <span className="price">{formatNumber(product.price)}</span>
                                                <span className="currency">{currency}</span>
                                            </div>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </main>

                {/* ===== CART SIDEBAR ===== */}
                <aside className="pos-cart">

                    {/* Cart Header */}
                    <div className="pos-cart-header">
                        <div className="pos-cart-header-info">
                            <div className="cart-icon">
                                <ShoppingCart size={22} />
                            </div>
                            <div className="cart-text">
                                <h2>{t('pos.cart')}</h2>
                                <p>{cart.reduce((a, c) => a + c.quantity, 0)} {t('pos.items')}</p>
                            </div>
                        </div>
                        <button
                            onClick={() => setCart([])}
                            disabled={!cart.length}
                            className="pos-cart-clear-btn"
                        >
                            {t('pos.clear_all')}
                        </button>
                    </div>

                    {/* Cart Items */}
                    <div className="pos-cart-items">
                        {cart.length === 0 ? (
                            <div className="cart-empty">
                                <div className="empty-icon">
                                    <ShoppingCart size={28} />
                                </div>
                                <p>{t('pos.cart_empty')}</p>
                            </div>
                        ) : cart.map(item => (
                            <div key={item.id} className="cart-item">
                                <div className="cart-item-info">
                                    <h4 className="cart-item-name">{item.name}</h4>
                                    <p className="cart-item-price">{formatNumber(item.price)} {currency}</p>
                                </div>

                                <div className="cart-item-qty">
                                    <button onClick={(e) => { e.stopPropagation(); updateQuantity(item.id, -1); }}><Minus size={14} /></button>
                                    <span>{item.quantity}</span>
                                    <button onClick={(e) => { e.stopPropagation(); updateQuantity(item.id, 1); }}><Plus size={14} /></button>
                                </div>

                                <div className="cart-item-total">
                                    <p className="total-amount">{displayMoney(previewLineTotal(item.id))}</p>
                                    <p className="total-currency">{currency}</p>
                                </div>

                                <button
                                    onClick={(e) => { e.stopPropagation(); removeFromCart(item.id); }}
                                    className="cart-item-remove"
                                >
                                    <X size={16} />
                                </button>
                            </div>
                        ))}
                    </div>

                    {/* Cart Footer */}
                    <div className="pos-cart-footer">
                        <div className="cart-totals">
                            <div className="cart-totals-row">
                                <span className="label">{t('pos.subtotal')}</span>
                                <span className="value">{displayMoney(cartTotals.subtotal)} {currency}</span>
                            </div>
                            <div className="cart-totals-row discount">
                                <span className="label">{t('pos.discount')}</span>
                                <div className="discount-actions">
                                    {decimalOrZero(globalDiscount).gt(0) ? (
                                        <>
                                            <span className="value">-{formatNumber(globalDiscount)} {currency}</span>
                                            <button onClick={() => setGlobalDiscount('')} className="discount-btn remove">{t('common.cancel')}</button>
                                        </>
                                    ) : (
                                        <button
                                            onClick={() => {
                                                const d = prompt(t('pos.enter_discount_value'));
                                                const val = parseDecimalInput(d);
                                                if (!val) return;
                                                if (val.lt(0)) {
                                                    showToast(t('pos.discount_negative'), 'warning');
                                                } else if (cartTotals.subtotal && val.gt(decimalOrZero(cartTotals.subtotal))) {
                                                    showToast(t('pos.discount_exceeds_total'), 'warning');
                                                } else {
                                                    setGlobalDiscount(val.toString());
                                                }
                                            }}
                                            className="discount-btn add"
                                        >
                                            + {t('common.add')}
                                        </button>
                                    )}
                                </div>
                            </div>
                            <div className="cart-totals-row">
                                <span className="label">{t('pos.tax')}</span>
                                <span className="value">{displayMoney(cartTotals.tax)} {currency}</span>
                            </div>
                        </div>

                        <div className="cart-grand-total">
                            <span className="label">{t('pos.total')}</span>
                            <div className="value">
                                <p className="amount">{previewLoading ? '...' : displayMoney(cartTotals.total)}</p>
                                <p className="currency">{currency}</p>
                            </div>
                        </div>

                        <div className="cart-payment-grid">
                            <button
                                onClick={() => quickPay('cash')}
                                disabled={!cart.length || submitting || !hasPreviewTotals}
                                className="payment-btn cash"
                            >
                                <Banknote size={18} /> {submitting ? '...' : t('pos.cash')}
                            </button>
                            <button
                                onClick={() => quickPay('card')}
                                disabled={!cart.length || submitting || !hasPreviewTotals}
                                className="payment-btn card"
                            >
                                <CardIcon size={18} /> {t('pos.payment_credit_card')}
                            </button>
                            <button
                                onClick={() => quickPay('mada')}
                                disabled={!cart.length || submitting || !hasPreviewTotals}
                                className="payment-btn mada"
                            >
                                <Smartphone size={16} /> {t('pos.payment_mada')}
                            </button>
                            <button
                                onClick={openSplitPayment}
                                disabled={!cart.length || submitting || !hasPreviewTotals}
                                className="payment-btn split"
                            >
                                <Split size={16} /> {t('pos.split_payment')}
                            </button>
                        </div>

                        <div className="cart-secondary-actions">
                            <button
                                onClick={handleHold}
                                disabled={!cart.length}
                                className="secondary-btn hold"
                            >
                                <Clock size={18} />
                                <span>{t('pos.hold_invoice')}</span>
                            </button>
                            <button
                                disabled={!cart.length || (isOnline && !hasPreviewTotals)}
                                onClick={() => {
                                    if (!orderPreview) {
                                        showToast(t('common.error_occurred'), 'warning');
                                        return;
                                    }
                                    const receiptOrder = {
                                        order_number: session?.session_code ? `${session.session_code}-${(session.order_count || 0) + 1}` : 'NEW',
                                        order_date: new Date().toISOString(),
                                        customer_name: selectedCustomer?.name,
                                        items: cart.map(item => ({
                                            product_name: item.name,
                                            quantity: item.quantity,
                                            unit_price: item.price,
                                            total: previewLineTotal(item.id),
                                        })),
                                        subtotal: cartTotals.subtotal,
                                        tax_amount: cartTotals.tax,
                                        discount: cartTotals.discount,
                                        total: cartTotals.total,
                                    };
                                    const text = generateReceiptText(receiptOrder, { currency });
                                    const cleanText = text.replace(/[\x1B\x1D][\x00-\xFF]/g, '').replace(/[\x00-\x09\x0B\x0C\x0E-\x1F]/g, '');
                                    const win = window.open('', '_blank', 'width=400,height=600');
                                    if (win) {
                                        win.document.open();
                                        win.document.write(
                                            `<!DOCTYPE html><html dir="rtl"><head><title>Receipt</title>` +
                                            `<style>body { font-family: 'Courier New', monospace; font-size: 12px; ` +
                                            `width: 300px; margin: auto; padding: 10px; white-space: pre-wrap; }</style>` +
                                            `</head><body></body></html>`
                                        );
                                        win.document.close();
                                        win.document.body.textContent = cleanText;
                                        setTimeout(() => { win.print(); }, 300);
                                    }
                                }}
                                className="secondary-btn print"
                            >
                                <Printer size={18} />
                                <span>{t('pos.print')}</span>
                            </button>
                            <button
                                onClick={initPOS}
                                className="secondary-btn new"
                            >
                                <Plus size={18} />
                                <span>{t('pos.new_invoice')}</span>
                            </button>
                        </div>
                    </div>
                </aside>
            </div>

            {/* ========== SPLIT PAYMENT MODAL ========== */}
            {showPaymentModal && (
                <div className="pos-modal-overlay" onClick={() => setShowPaymentModal(false)}>
                    <div className="pos-modal" onClick={e => e.stopPropagation()}>
                        <div className="pos-modal-header">
                            <div>
                                <h3>{t('pos.split_payment')}</h3>
                                <p>{t("pos.multi_payment")}</p>
                            </div>
                            <button onClick={() => setShowPaymentModal(false)} className="pos-modal-close">
                                <X size={20} />
                            </button>
                        </div>

                        <div className="pos-modal-body">
                            <div className="modal-remaining">
                                <p className="label">{t('pos.remaining_amount')}</p>
                                <p className="amount">
                                    <span className="currency">{currency}</span>
                                    {displayMoney(cartTotals.remaining)}
                                </p>
                            </div>

                            {/* Cash */}
                            <div className="modal-input-group">
                                <label>{t('pos.cash')}</label>
                                <div className="modal-input-row">
                                    <div className="modal-input-icon cash">
                                        <Banknote size={24} />
                                    </div>
                                    <input
                                        type="text"
                                        inputMode="decimal"
                                        value={paymentAmounts.cash}
                                        onChange={e => setPaymentAmounts({ ...paymentAmounts, cash: e.target.value })}
                                        onFocus={e => e.target.select()}
                                    />
                                    <button
                                        disabled={!hasPreviewTotals}
                                        onClick={() => fillPaymentAmount('cash')}
                                        className="modal-full-btn"
                                    >
                                        {t('pos.full')}
                                    </button>
                                </div>
                            </div>

                            {/* Credit Card */}
                            <div className="modal-input-group">
                                <label>{t('pos.payment_credit_card')}</label>
                                <div className="modal-input-row">
                                    <div className="modal-input-icon bank">
                                        <CardIcon size={24} />
                                    </div>
                                    <input
                                        type="text"
                                        inputMode="decimal"
                                        value={paymentAmounts.card}
                                        onChange={e => setPaymentAmounts({ ...paymentAmounts, card: e.target.value })}
                                        onFocus={e => e.target.select()}
                                    />
                                    <button
                                        disabled={!hasPreviewTotals}
                                        onClick={() => fillPaymentAmount('card')}
                                        className="modal-full-btn"
                                    >
                                        {t('pos.full')}
                                    </button>
                                </div>
                            </div>

                            {/* Mada */}
                            <div className="modal-input-group">
                                <label>{t('pos.payment_mada')}</label>
                                <div className="modal-input-row">
                                    <div className="modal-input-icon mada">
                                        <Smartphone size={24} />
                                    </div>
                                    <input
                                        type="text"
                                        inputMode="decimal"
                                        value={paymentAmounts.mada}
                                        onChange={e => setPaymentAmounts({ ...paymentAmounts, mada: e.target.value })}
                                        onFocus={e => e.target.select()}
                                    />
                                    <button
                                        disabled={!hasPreviewTotals}
                                        onClick={() => fillPaymentAmount('mada')}
                                        className="modal-full-btn"
                                    >
                                        {t('pos.full')}
                                    </button>
                                </div>
                            </div>

                            <button onClick={handleSplitCheckout} className="modal-confirm-btn" disabled={submitting || !hasPreviewTotals}>
                                <span>{submitting ? '...' : t('pos.confirm_payment')}</span>
                                <ArrowRightLeft size={20} />
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Held Orders Modal */}
            {showHeldOrders && (
                <HeldOrders
                    onResume={(orderData) => {
                        // Resume order - load items into cart
                        setCart(orderData.items.map(item => ({
                            id: item.product_id,
                            name: item.name,
                            price: item.unit_price,
                            quantity: item.quantity,
                            code: item.code,
                            barcode: item.barcode,
                        })));
                        setShowHeldOrders(false);
                    }}
                    onClose={() => setShowHeldOrders(false)}
                />
            )}

            {/* Returns Modal */}
            {showReturns && (
                <POSReturns
                    onClose={() => setShowReturns(false)}
                    onComplete={(returnData) => {
                        showToast(t('pos.return_success'), 'success');
                        setShowReturns(false);
                    }}
                />
            )}

            {/* Close Session Modal */}
            {showCloseSession && (
                <div className="held-orders-modal">
                    <div className="held-orders-content">
                        <div className="held-orders-header">
                            <h3><Store size={20} /> {t('pos.close_session')}</h3>
                            <button className="close-btn" onClick={() => setShowCloseSession(false)}>
                                <X size={20} />
                            </button>
                        </div>

                        <div style={{ padding: '20px' }}>
                            <div className="close-session-summary" style={{ marginBottom: '20px', padding: '16px', background: 'var(--base-200)', borderRadius: '12px' }}>
                                <h4 style={{ marginBottom: '12px', fontSize: '14px', fontWeight: '600' }}>{t('pos.session_summary')}</h4>
                                <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '13px' }}>
                                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                        <span>{t('pos.opening_balance')}:</span>
                                        <strong>{formatNumber(session?.opening_balance)} {currency}</strong>
                                    </div>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', borderTop: '1px solid var(--base-200)', paddingTop: '4px' }}>
                                        <span>{t('pos.total_actual_sales')}:</span>
                                        <strong style={{ fontWeight: '500' }}>{formatNumber(session?.total_sales || 0)} {currency}</strong>
                                    </div>
                                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                        <span>{t('pos.total_cash_sales')}:</span>
                                        <strong style={{ color: '#059669' }}>+{formatNumber(session?.total_cash || 0)} {currency}</strong>
                                    </div>
                                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                                        <span>{t('pos.total_bank_sales')}:</span>
                                        <strong style={{ color: '#2563eb' }}>{formatNumber(session?.total_bank || 0)} {currency}</strong>
                                    </div>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', color: session?.total_returns_cash > 0 ? 'var(--pos-danger)' : 'inherit' }}>
                                        <span>{t('pos.total_returns_cash')}:</span>
                                        <strong>-{formatNumber(session?.total_returns_cash || 0)} {currency}</strong>
                                    </div>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', paddingTop: '8px', borderTop: '2px solid var(--base-300)' }}>
                                        <span style={{ fontWeight: '700', fontSize: '14px' }}>{t('pos.expected_cash')}:</span>
                                        <strong style={{ color: 'var(--primary)', fontSize: '17px' }}>
                                            {formatNumber(session?.expected_cash || 0)} {currency}
                                        </strong>
                                    </div>
                                    <div style={{ fontSize: '11px', color: 'var(--base-content-secondary)', marginTop: '4px', textAlign: 'center' }}>
                                        * {t('pos.expected_cash_note')}
                                    </div>
                                </div>
                            </div>

                            <div style={{ marginBottom: '16px' }}>
                                <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>
                                    {t('pos.actual_cash_count')} *
                                </label>
                                <input
                                    type="text"
                                    inputMode="decimal"
                                    value={closingData.cashCount}
                                    onChange={(e) => setClosingData({ ...closingData, cashCount: e.target.value })}
                                    placeholder="0.00"
                                    className="close-session-input"
                                    style={{
                                        width: '100%',
                                        padding: '12px',
                                        border: '2px solid var(--base-300)',
                                        borderRadius: '10px',
                                        fontSize: '16px',
                                        textAlign: 'center',
                                        fontWeight: '600'
                                    }}
                                />
                            </div>

                            <div style={{ marginBottom: '20px' }}>
                                <label style={{ display: 'block', marginBottom: '8px', fontWeight: '600', fontSize: '14px' }}>
                                    {t('common.notes')}
                                </label>
                                <textarea
                                    value={closingData.notes}
                                    onChange={(e) => setClosingData({ ...closingData, notes: e.target.value })}
                                    placeholder={t('pos.closing_notes_placeholder')}
                                    rows="3"
                                    className="close-session-textarea"
                                    style={{
                                        width: '100%',
                                        padding: '12px',
                                        border: '2px solid var(--base-300)',
                                        borderRadius: '10px',
                                        fontSize: '14px',
                                        resize: 'vertical'
                                    }}
                                />
                            </div>

                            <button
                                onClick={handleCloseSession}
                                className="btn btn-primary"
                                style={{ width: '100%', padding: '14px', fontSize: '16px', fontWeight: '600' }}
                            >
                                {t('pos.confirm_close_session')}
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
};

export default POSInterface;
