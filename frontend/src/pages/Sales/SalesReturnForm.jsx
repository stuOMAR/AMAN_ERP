import React, { useState, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { salesAPI, inventoryAPI } from '../../utils/api';
import { getCurrency } from '../../utils/auth';
import { useTranslation } from 'react-i18next';
import CustomDatePicker from '../../components/common/CustomDatePicker';
import { useBranch } from '../../context/BranchContext';
import { formatNumber } from '../../utils/format';
import { useToast } from '../../context/ToastContext';
import { formatShortDate } from '../../utils/dateUtils';
import BackButton from '../../components/common/BackButton';
import FormField from '../../components/common/FormField';
import useInvoiceCalc from '../../hooks/useInvoiceCalc';


const SalesReturnForm = () => {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const currency = getCurrency();
    const { currentBranch } = useBranch();
    const { showToast } = useToast();
    const [loading, setLoading] = useState(false);
    const [initialLoad, setInitialLoad] = useState(true);
    const [customers, setCustomers] = useState([]);
    const [products, setProducts] = useState([]);
    const [warehouses, setWarehouses] = useState([]);
    const [invoices, setInvoices] = useState([]);
    const [selectedInvoiceInfo, setSelectedInvoiceInfo] = useState(null);

    const [formData, setFormData] = useState({
        customer_id: '',
        party_site_id: '',
        warehouse_id: '',
        invoice_id: '',
        return_date: new Date().toISOString().split('T')[0],
        items: [],
        notes: '',
        refund_method: 'credit',
        refund_amount: 0,
        bank_account_id: '',
        check_number: '',
        check_date: ''
    });

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchInitialData();
        }, 300)
        return () => clearTimeout(timer)
    }, []);

    const fetchInitialData = async () => {
        try {
            const [custRes, prodRes, whRes, priceRes] = await Promise.all([
                salesAPI.listCustomers(),
                inventoryAPI.listProducts(),
                inventoryAPI.listWarehouses(),
                inventoryAPI.getBranchPrices(currentBranch?.id)
            ]);
            setCustomers(custRes.data);
            setProducts(prodRes.data);
            setWarehouses(whRes.data);
            
            // Store branch prices for auto-fill
            window.__branchPrices = priceRes.data?.prices || {};
            window.__branchCurrency = priceRes.data?.currency || currency;
        } catch (error) {
            showToast(t('sales.orders.form.errors.fetch_failed'), 'error');
        } finally {
            setInitialLoad(false);
        }
    };

    const handleCustomerChange = async (e) => {
        const customerId = e.target.value;
        setFormData({ ...formData, customer_id: customerId, party_site_id: '', invoice_id: '', items: [] });
        setInvoices([]);
        setSelectedInvoiceInfo(null);

        if (customerId) {
            try {
                // Fetch existing invoices for this customer
                const res = await salesAPI.listInvoices({ customer_id: customerId });
                setInvoices(res.data);
            } catch (error) {
                showToast(t('common.error'), 'error');
            }
        }
    };

    const handleInvoiceChange = async (e) => {
        const invoiceId = e.target.value;
        const selectedInvoice = invoices.find(inv => inv.id === parseInt(invoiceId));

        let newItems = [];
        let notesRef = formData.notes;

        if (invoiceId && selectedInvoice) {
            try {
                const res = await salesAPI.getInvoice(invoiceId);
                const invoiceDetails = res.data;

                // Map invoice items to return items
                newItems = invoiceDetails.items.map(item => {
                    const quantity = Number(item.quantity) || 0;
                    const unitPrice = Number(item.unit_price) || 0;
                    const discount = Number(item.discount) || 0;
                    const discountPercent = (quantity * unitPrice) > 0 ? (discount / (quantity * unitPrice)) * 100 : 0;
                    const taxRate = Number(item.tax_rate) || 0;

                    const taxable = (quantity * unitPrice) - discount;
                    const total = taxable * (1 + taxRate / 100);

                    return {
                        product_id: item.product_id || '',
                        description: item.description || '',
                        quantity: quantity,
                        max_quantity: quantity, // Store original quantity
                        unit_price: unitPrice,
                        tax_rate: taxRate,
                        discount: discount,
                        discount_percent: discountPercent,
                        reason: '',
                        unit: item.unit || '',
                        total: total
                    };
                });

                notesRef = `${t('sales.returns.form.auto_note')} #${invoiceDetails.invoice_number}`;
                setSelectedInvoiceInfo(invoiceDetails);
            } catch (error) {
                showToast(t('common.error'), 'error');
                setSelectedInvoiceInfo(null);
            }
        } else {
            setSelectedInvoiceInfo(null);
        }

        setFormData(prev => ({
            ...prev,
            invoice_id: invoiceId,
            items: newItems,
            notes: notesRef
        }));
    };

    const DISCRETE_UNITS = ['قطعة', 'علبة', 'كرتون', 'piece', 'box', 'carton', 'unit'];
    const isDiscreteUnit = (unit) => DISCRETE_UNITS.includes((unit || '').trim().toLowerCase()) || DISCRETE_UNITS.includes((unit || '').trim());

    const addItem = () => {
        setFormData({ ...formData, items: [...formData.items, { product_id: '', description: '', quantity: 1, max_quantity: 999999, unit_price: 0, tax_rate: 0, discount: 0, discount_percent: 0, reason: '', unit: '' }] })
    };

    const removeItem = (index) => {
        if (formData.items.length <= 1) return;
        const newItems = formData.items.filter((_, i) => i !== index);
        setFormData({ ...formData, items: newItems });
    };

    const updateItem = (index, field, value) => {
        const newItems = formData.items.map((item, i) => {
            if (i === index) {
                let newValue = value;

                // Validate quantity
                if (field === 'quantity') {
                    if (newValue > item.max_quantity) {
                        showToast(`${t('sales.returns.form.errors.max_quantity')} (${item.max_quantity})`, 'error');
                        newValue = item.max_quantity;
                    }
                }

                const updated = { ...item, [field]: newValue };

                // Fetch product details
                if (field === 'product_id') {
                    const product = products.find(p => p.id === parseInt(value));
                    if (product) {
                        updated.description = product.item_name;
                        // Use branch price if available, otherwise use product default
                        const branchPrices = window.__branchPrices || {};
                        const priceInfo = branchPrices[parseInt(value)];
                        updated.unit_price = priceInfo ? priceInfo.price : (product.selling_price || 0);
                        updated.unit = product.unit || 'قطعة';
                        updated.tax_rate = null // Resolved by backend engine;
                    }
                }

                // Calculate discount logic
                const qty = Number(field === 'quantity' ? newValue : updated.quantity) || 0;
                const price = Number(field === 'unit_price' ? newValue : updated.unit_price) || 0;
                let discount = Number(updated.discount) || 0;
                let discountPercent = Number(updated.discount_percent) || 0;

                if (field === 'discount_percent') {
                    discountPercent = Number(newValue) || 0;
                    discount = (qty * price) * (discountPercent / 100);
                    updated.discount = discount;
                } else if (field === 'quantity' || field === 'unit_price') {
                    discount = (qty * price) * (discountPercent / 100);
                    updated.discount = discount;
                }

                updated.discount_percent = discountPercent;
                updated.discount = discount;

                return updated;
            }
            return item;
        });
        setFormData({ ...formData, items: newItems });
    };

    const calculateTotals = () => {
        let subtotal = 0;
        let totalDiscount = 0;
        let tax = 0;

        formData.items.forEach(item => {
            const qty = Number(item.quantity) || 0;
            const price = Number(item.unit_price) || 0;
            const discount = Number(item.discount) || 0;
            const taxRate = Number(item.tax_rate) || 0;

            const linePrice = qty * price;
            const taxable = linePrice - discount;
            const lineTax = taxable * (taxRate / 100);

            subtotal += linePrice;
            totalDiscount += discount;
            tax += lineTax;
        });

        const total = (subtotal - totalDiscount) + tax;

        // Auto-sync refund_amount with total if refund method is not 'credit'
        if (formData.refund_method !== 'credit' && formData.refund_amount !== total) {
            setFormData(prev => ({ ...prev, refund_amount: total }));
        }

        return { subtotal: subtotal - totalDiscount, tax, total };
    };

    const handleSubmit = async (e) => {
        e.preventDefault();
        if (formData.items.length === 0) {
            showToast(t('sales.returns.form.errors.no_items'), 'error');
            return;
        }
        if (!formData.warehouse_id) {
            showToast(t('sales.invoices.form.error_warehouse') || t('common.required'), 'error');
            return;
        }

        try {
            setLoading(true);

            // Clean up payload - convert empty strings to null for optional fields
            const payload = {
                ...formData,
                customer_id: parseInt(formData.customer_id) || null,
                party_site_id: formData.party_site_id ? parseInt(formData.party_site_id) : null,
                warehouse_id: formData.warehouse_id ? parseInt(formData.warehouse_id) : null,
                invoice_id: formData.invoice_id ? parseInt(formData.invoice_id) : null,
                items: formData.items.map(item => ({
                    ...item,
                    product_id: item.product_id ? parseInt(item.product_id) : null,
                    quantity: String(item.quantity || 0),
                    unit_price: String(item.unit_price || 0),
                    tax_rate: String(item.tax_rate || 0),
                    discount: String(item.discount || 0),
                })),
                bank_account_id: formData.bank_account_id ? parseInt(formData.bank_account_id) : null,
                check_number: formData.check_number || null,
                check_date: formData.check_date || null,
                refund_amount: formData.refund_method !== 'credit' ? String(formData.refund_amount || 0) : 0,
                branch_id: currentBranch?.id
            };

            const res = await salesAPI.createReturn(payload);
            navigate(`/sales/returns/${res.data.id}`);
        } catch (error) {
            showToast(t('common.error'), 'error');
        } finally {
            setLoading(false);
        }
    };

    const { subtotal, tax, total } = calculateTotals();

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <div className="header-title">
                    <h1 className="workspace-title">↩️ {t('sales.returns.form.create_title')}</h1>
                </div>
            </div>

            <form onSubmit={handleSubmit} className="card">
                <div className="grid grid-cols-1 md:grid-cols-3 gap-6 mb-6">
                    <FormField label={t('sales.returns.form.customer')}>
                        <select
                            required
                            value={formData.customer_id}
                            onChange={handleCustomerChange}
                            className="form-input"
                        >
                            <option value="">{t('sales.returns.form.customer_placeholder')}</option>
                            {customers.map(c => <option key={c.id} value={c.id}>{c.name}</option>)}
                        </select>
                    </FormField>

                    <FormField label={t('sales.invoices.form.warehouse')}>
                        <select
                            required
                            value={formData.warehouse_id}
                            onChange={(e) => setFormData({ ...formData, warehouse_id: e.target.value })}
                            className="form-input"
                        >
                            <option value="">{t('common.select')}</option>
                            {warehouses.map(w => <option key={w.id} value={w.id}>{w.name || w.warehouse_name}</option>)}
                        </select>
                    </FormField>

                    <div className="form-group">
                        <label className="form-label">{t('sales.returns.form.invoice')}</label>
                        <select
                            value={formData.invoice_id}
                            onChange={handleInvoiceChange}
                            className="form-input"
                            disabled={!formData.customer_id || invoices.length === 0}
                        >
                            <option value="">{t('sales.returns.form.invoice_placeholder')}</option>
                            {invoices.map(inv => (
                                <option key={inv.id} value={inv.id}>
                                    #{inv.invoice_number} ({formatShortDate(inv.invoice_date)}) - {formatNumber(inv.total)} {currency}
                                </option>
                            ))}
                        </select>
                        {formData.customer_id && invoices.length === 0 && (
                            <small className="text-gray-400 block mt-1">{t('sales.returns.form.no_invoices')}</small>
                        )}

                        {selectedInvoiceInfo && (
                            <div className={`mt-3 p-4 rounded-xl border-2 shadow-lg animate-fade-in ${selectedInvoiceInfo.status === 'paid'
                                ? 'bg-green-50 border-green-300 text-green-900'
                                : selectedInvoiceInfo.status === 'partial'
                                    ? 'bg-orange-50 border-orange-300 text-orange-900 animate-pulse-orange'
                                    : 'bg-red-50 border-red-300 text-red-900 animate-pulse-red'
                                }`}>
                                <div className="flex items-center gap-3 mb-3 pb-2 border-b border-current border-opacity-20">
                                    <span className="text-3xl">
                                        {selectedInvoiceInfo.status === 'paid' ? '✅' : selectedInvoiceInfo.status === 'partial' ? '⚠️' : '🚨'}
                                    </span>
                                    <div>
                                        <h4 className="font-black text-lg leading-tight">
                                            {selectedInvoiceInfo.status === 'paid' ? t('sales.returns.form.alerts.paid') :
                                                selectedInvoiceInfo.status === 'partial' ? t('sales.returns.form.alerts.partial') :
                                                    t('sales.returns.form.alerts.unpaid')}
                                        </h4>
                                        <p className="text-sm opacity-90 font-medium">
                                            {selectedInvoiceInfo.status === 'paid' ? t('sales.returns.form.alerts.paid_msg') : t('sales.returns.form.alerts.unpaid_msg')}
                                        </p>
                                    </div>
                                </div>

                                <div className="space-y-3">
                                    <div className="flex justify-between items-center text-sm border-b border-current border-opacity-5 pb-1">
                                        <span className="opacity-70">{t('sales.returns.form.alerts.total_invoice')}:</span>
                                        <span className="font-bold">{formatNumber(selectedInvoiceInfo.total)} {currency}</span>
                                    </div>

                                    {(selectedInvoiceInfo.status === 'partial' || selectedInvoiceInfo.status === 'paid') && (
                                        <div className="flex justify-between items-center text-sm text-green-700 border-b border-current border-opacity-5 pb-1">
                                            <span className="opacity-70 font-bold">{t('sales.returns.form.alerts.paid_amount')}:</span>
                                            <span className="font-black text-base">{formatNumber(selectedInvoiceInfo.paid_amount || 0)} {currency}</span>
                                        </div>
                                    )}

                                    {selectedInvoiceInfo.status !== 'paid' && (
                                        <div className={`flex justify-between items-center text-base px-4 py-3 rounded-xl mt-2 border ${selectedInvoiceInfo.status === 'partial' ? 'bg-orange-100 border-orange-200' : 'bg-red-100 border-red-200'
                                            }`}>
                                            <span className="font-black">{t('sales.returns.form.alerts.remaining_amount')}:</span>
                                            <span className="font-black text-2xl">
                                                {formatNumber(selectedInvoiceInfo.total - (selectedInvoiceInfo.paid_amount || 0))} {currency}
                                            </span>
                                        </div>
                                    )}
                                </div>
                            </div>
                        )}
                    </div>

                    <FormField>
                        <CustomDatePicker
                            label={t('sales.returns.form.return_date')}
                            selected={formData.return_date}
                            onChange={(dateStr) => setFormData({ ...formData, return_date: dateStr })}
                            required
                        />
                    </FormField>
                </div>

                <div className="mb-6">
                    <div className="flex justify-between items-center mb-4">
                        <h2 className="text-lg font-bold">{t('sales.returns.form.items_title')}</h2>
                        <button type="button" onClick={addItem} className="btn btn-secondary text-sm">
                            + {t('sales.returns.form.add_item')}
                        </button>
                    </div>

                <div className="invoice-items-container" style={{ margin: '24px 0', border: '1px solid var(--border-color)', borderRadius: '8px', overflow: 'hidden' }}>
                        <table className="data-table">
                            <thead style={{ background: '#fef2f2' }}>
                                <tr>
                                    <th style={{ width: '25%' }}>{t('sales.quotations.form.items.product')}</th>
                                    <th style={{ width: '8%' }}>{t('sales.quotations.form.items.quantity')}</th>
                                    <th style={{ width: '12%' }}>{t('sales.quotations.form.items.price')}</th>
                                    <th style={{ width: '10%' }}>{t('sales.invoices.form.items.discount')} (%)</th>
                                    <th style={{ width: '8%' }}>{t('sales.quotations.form.items.tax')}</th>
                                    <th style={{ width: '12%' }}>{t('sales.quotations.form.items.total')}</th>
                                    <th style={{ width: '20%' }}>{t('sales.returns.details.reason')}</th>
                                    <th style={{ width: '5%' }}></th>
                                </tr>
                            </thead>
                            <tbody>
                                {formData.items.length === 0 ? (
                                    <tr>
                                        <td colSpan="7" className="text-center py-4 text-muted">{t('sales.returns.form.no_items')}</td>
                                    </tr>
                                ) : (
                                    formData.items.map((item, index) => (
                                        <tr key={index}>
                                            <td>
                                                <select
                                                    required
                                                    value={item.product_id}
                                                    onChange={(e) => updateItem(index, 'product_id', e.target.value)}
                                                    className="form-input"
                                                >
                                                    <option value="">{t('sales.returns.form.product_placeholder')}</option>
                                                    {products.map(p => <option key={p.id} value={p.id}>{p.item_name}</option>)}
                                                </select>
                                                {item.description && <div className="text-xs text-gray-500 mt-1">{item.description}</div>}
                                            </td>
                                            <td>
                                                <input
                                                    type="number"
                                                    min={isDiscreteUnit(item.unit) ? "1" : "0.01"}
                                                    step={isDiscreteUnit(item.unit) ? "1" : "any"}
                                                    value={item.quantity}
                                                    onChange={(e) => {
                                                        let val = Number(e.target.value) || 0;
                                                        if (isDiscreteUnit(item.unit)) val = Math.round(val);
                                                        updateItem(index, 'quantity', val);
                                                    }}
                                                    className="form-input text-center"
                                                />
                                            </td>
                                            <td>
                                                <input
                                                    type="number"
                                                    min="0"
                                                    step="any"
                                                    value={item.unit_price}
                                                    onChange={(e) => updateItem(index, 'unit_price', Number(e.target.value) || 0)}
                                                    className="form-input text-center"
                                                />
                                            </td>
                                            <td>
                                                <input
                                                    type="number"
                                                    min="0"
                                                    max="100"
                                                    step="0.01"
                                                    value={item.discount_percent}
                                                    onChange={(e) => updateItem(index, 'discount_percent', Number(e.target.value) || 0)}
                                                    className="form-input text-center"
                                                />
                                            </td>
                                            <td>
                                                <input
                                                    type="number"
                                                    min="0"
                                                    step="any"
                                                    value={item.tax_rate}
                                                    onChange={(e) => updateItem(index, 'tax_rate', Number(e.target.value) || 0)}
                                                    className="form-input text-center"
                                                />
                                            </td>
                                            <td className="font-bold">
                                                {formatNumber((item.quantity * item.unit_price - item.discount) * (1 + item.tax_rate / 100))}
                                            </td>
                                            <td>
                                                <input
                                                    type="text"
                                                    placeholder={t('sales.returns.form.reason_placeholder')}
                                                    value={item.reason}
                                                    onChange={(e) => updateItem(index, 'reason', e.target.value)}
                                                    className="form-input"
                                                />
                                            </td>
                                            <td>
                                                <button
                                                    type="button"
                                                    onClick={() => removeItem(index)}
                                                    className="text-red-500 hover:text-red-700 font-bold px-2"
                                                    title={t('common.delete_item')}
                                                >
                                                    ✕
                                                </button>
                                            </td>
                                        </tr>
                                    ))
                                )}
                            </tbody>
                        </table>
                    </div>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-8 items-start mb-6">
                    <FormField label={t('sales.returns.form.refund_method')}>
                        <div style={{ display: 'flex', gap: '15px', flexWrap: 'wrap', padding: '10px 0' }}>
                            <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
                                <input
                                    type="radio"
                                    name="refund_method"
                                    value="credit"
                                    checked={formData.refund_method === 'credit'}
                                    onChange={(e) => setFormData({ ...formData, refund_method: e.target.value })}
                                />
                                <span>{t('sales.returns.form.methods.credit')}</span>
                            </label>
                            <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
                                <input
                                    type="radio"
                                    name="refund_method"
                                    value="cash"
                                    checked={formData.refund_method === 'cash'}
                                    onChange={(e) => setFormData({ ...formData, refund_method: e.target.value })}
                                />
                                <span>{t('sales.returns.form.methods.cash')}</span>
                            </label>
                            <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
                                <input
                                    type="radio"
                                    name="refund_method"
                                    value="bank"
                                    checked={formData.refund_method === 'bank'}
                                    onChange={(e) => setFormData({ ...formData, refund_method: e.target.value })}
                                />
                                <span>{t('sales.returns.form.methods.bank')}</span>
                            </label>
                            <label style={{ display: 'flex', alignItems: 'center', gap: '6px', cursor: 'pointer' }}>
                                <input
                                    type="radio"
                                    name="refund_method"
                                    value="check"
                                    checked={formData.refund_method === 'check'}
                                    onChange={(e) => setFormData({ ...formData, refund_method: e.target.value })}
                                />
                                <span>{t('sales.returns.form.methods.check')}</span>
                            </label>
                        </div>

                        {formData.refund_method !== 'credit' && (
                            <div style={{ marginTop: '15px', padding: '15px', background: 'var(--bg-tertiary)', borderRadius: '8px' }}>
                                <FormField label={t('sales.returns.form.refund_amount')} style={{ marginBottom: '10px' }}>
                                    <input
                                        type="number"
                                        step="0.01"
                                        value={formData.refund_amount}
                                        onChange={(e) => setFormData({ ...formData, refund_amount: Number(e.target.value) || 0 })}
                                        className="form-input"
                                    />
                                </FormField>

                                {formData.refund_method === 'check' && (
                                    <>
                                        <FormField label={t('sales.returns.form.check_number')} style={{ marginBottom: '10px' }}>
                                            <input
                                                type="text"
                                                value={formData.check_number}
                                                onChange={(e) => setFormData({ ...formData, check_number: e.target.value })}
                                                className="form-input"
                                                placeholder="CH-12345"
                                            />
                                        </FormField>
                                        <FormField>
                                            <CustomDatePicker
                                                label={t('sales.returns.form.check_date')}
                                                selected={formData.check_date}
                                                onChange={(dateStr) => setFormData({ ...formData, check_date: dateStr })}
                                            />
                                        </FormField>
                                    </>
                                )}
                            </div>
                        )}
                    </FormField>
                </div>

                <div className="grid grid-cols-1 md:grid-cols-2 gap-8 items-start">
                    <FormField label={t('sales.returns.form.notes')}>
                        <textarea
                            rows="4"
                            value={formData.notes}
                            onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
                            className="form-input"
                            placeholder={t('sales.returns.form.notes_placeholder')}
                        ></textarea>
                    </FormField>

                    <div style={{
                        width: '340px',
                        padding: '24px',
                        background: 'var(--bg-secondary)',
                        borderRadius: '12px',
                        border: '1px solid var(--border-color)',
                        marginRight: 'auto'
                    }}>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
                            <span style={{ color: 'var(--text-secondary)' }}>{t('sales.quotations.details.subtotal')}</span>
                            <span>{formatNumber(subtotal)} <small>{currency}</small></span>
                        </div>
                        <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '12px' }}>
                            <span style={{ color: 'var(--text-secondary)' }}>{t('sales.quotations.details.tax')}</span>
                            <span>{formatNumber(tax)} <small>{currency}</small></span>
                        </div>

                        <div style={{ borderTop: '1px solid var(--border-color)', margin: '16px 0' }}></div>

                        <div style={{
                            display: 'flex',
                            justifyContent: 'space-between',
                            fontWeight: 'bold',
                            fontSize: '20px',
                            color: 'var(--primary)',
                            marginBottom: '24px'
                        }}>
                            <span>{t('sales.quotations.details.grand_total')}</span>
                            <span>{formatNumber(total)} <small>{currency}</small></span>
                        </div>

                        <div className="form-actions" style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
                            <button
                                type="submit"
                                className="btn btn-primary"
                                style={{ width: '100%', padding: '12px' }}
                                disabled={loading}
                            >
                                {loading ? t('sales.returns.form.saving') : t('sales.returns.form.save_btn')}
                            </button>
                            <button
                                type="button"
                                className="btn btn-secondary"
                                style={{ width: '100%' }}
                                onClick={() => navigate('/sales/returns')}
                            >
                                {t('sales.returns.form.cancel')}
                            </button>
                        </div>
                    </div>
                </div>
            </form>
        </div>
    );
};

export default SalesReturnForm;
