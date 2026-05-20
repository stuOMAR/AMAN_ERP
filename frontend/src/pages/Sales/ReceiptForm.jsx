import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { salesAPI } from '../../utils/api';
import { getCurrency } from '../../utils/auth';
import { useTranslation } from 'react-i18next';
import CustomDatePicker from '../../components/common/CustomDatePicker';
import { useBranch } from '../../context/BranchContext';
import { formatNumber } from '../../utils/format';
import { useToast } from '../../context/ToastContext';
import { formatShortDate } from '../../utils/dateUtils';
import BackButton from '../../components/common/BackButton';
import FormField from '../../components/common/FormField';
import Decimal from 'decimal.js';


function ReceiptForm() {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const location = useLocation();
    const { currentBranch } = useBranch();
    const { showToast } = useToast();
    const currency = getCurrency();
    const isPaymentsRoute = location.pathname.includes('/sales/payments');
    const [loading, setLoading] = useState(false);
    const [customers, setCustomers] = useState([]);
    const [selectedCustomer, setSelectedCustomer] = useState(null);
    const [outstandingInvoices, setOutstandingInvoices] = useState([]);
    const [allocationPreview, setAllocationPreview] = useState(null);
    const [formData, setFormData] = useState({
        customer_id: '',
        party_site_id: '',
        voucher_date: new Date().toISOString().split('T')[0],
        amount: '',
        voucher_type: isPaymentsRoute ? 'refund' : 'receipt',
        payment_method: '',
        bank_account_id: null,
        check_number: '',
        check_date: '',
        reference: '',
        notes: '',
        allocations: []
    });

    const moneyOrDash = (value) => value !== null && value !== undefined && value !== '' ? formatNumber(value) : '—';
    const toDecimal = (value) => {
        try {
            return new Decimal(value || '0');
        } catch {
            return new Decimal('0');
        }
    };
    const isPositiveDecimal = (value) => toDecimal(value).gt(0);
    const isNegativeDecimal = (value) => toDecimal(value).lt(0);
    const previewTotalAllocated = allocationPreview?.total_allocated ?? null;
    const previewUnallocated = allocationPreview?.unallocated_amount ?? null;
    const isOverAllocated = allocationPreview?.over_allocated === true;

    useEffect(() => {
        fetchInitialData();
    }, []);

    const fetchInitialData = async () => {
        try {
            const res = await salesAPI.listCustomers();
            setCustomers(res.data);

            // Check if we have a prefilled invoice from state
            if (location.state?.fromInvoice) {
                const inv = location.state.fromInvoice;
                const customer = res.data.find(c => c.id === parseInt(inv.customer_id));
                setSelectedCustomer(customer);

                // If it's a sales return invoice, default to refund
                const isReturn = inv.invoice_type === 'sales_return';
                setFormData(prev => ({
                    ...prev,
                    customer_id: inv.customer_id,
                    voucher_type: isReturn ? 'refund' : 'receipt',
                    amount: '',
                    notes: `${t('sales.receipts.form.notes_auto')} ${inv.invoice_number}`
                }));

                // Fetch outstanding invoices for this customer
                const outstandingRes = await salesAPI.getOutstandingInvoices(inv.customer_id, { branch_id: currentBranch?.id });
                setOutstandingInvoices(outstandingRes.data);

                const previewRes = await salesAPI.previewReceiptAllocation({
                    customer_id: inv.customer_id ? parseInt(inv.customer_id, 10) : null,
                    voucher_date: new Date().toISOString().split('T')[0],
                    amount: '0',
                    branch_id: currentBranch?.id || null,
                    voucher_type: isReturn ? 'refund' : 'receipt',
                    currency,
                    allocations: [],
                    fill_invoice_id: inv.id,
                });
                const preview = previewRes.data;
                setAllocationPreview(preview);
                setFormData(prev => ({
                    ...prev,
                    amount: preview.amount ?? '',
                    allocations: preview.allocations || [],
                }));
            }
        } catch (error) {
            showToast(t('sales.receipts.form.errors.fetch_failed'), 'error');
        }
    };

    const buildPreviewPayload = (data = formData, options = {}) => {
        const payload = {
            customer_id: data.customer_id ? parseInt(data.customer_id, 10) : null,
            voucher_date: data.voucher_date,
            amount: String(data.amount || '0'),
            branch_id: currentBranch?.id || null,
            voucher_type: data.voucher_type,
            currency,
            allocations: (data.allocations || []).map(a => ({
                invoice_id: parseInt(a.invoice_id, 10),
                allocated_amount: String(a.allocated_amount || '0'),
            })),
            auto_allocate: options.auto_allocate === true,
            pay_all: options.pay_all === true,
            fill_invoice_id: options.fill_invoice_id || null,
        };
        if (data.exchange_rate) {
            payload.exchange_rate = String(data.exchange_rate);
        }
        return payload;
    };

    const requestAllocationPreview = async (data = formData, options = {}, applyResult = false) => {
        if (!data.customer_id) {
            setAllocationPreview(null);
            return null;
        }
        const res = await salesAPI.previewReceiptAllocation(buildPreviewPayload(data, options));
        const preview = res.data;
        setAllocationPreview(preview);
        if (applyResult) {
            setFormData(prev => ({
                ...prev,
                amount: preview.amount ?? prev.amount,
                allocations: preview.allocations || [],
            }));
        }
        return preview;
    };

    const handleCustomerChange = async (e) => {
        const customerId = e.target.value;
        const customer = customers.find(c => c.id === parseInt(customerId));
        setSelectedCustomer(customer);

        setFormData({ ...formData, customer_id: customerId, allocations: [] });
        setAllocationPreview(null);

        if (customerId) {
            try {
                const res = await salesAPI.getOutstandingInvoices(customerId, { branch_id: currentBranch?.id });
                setOutstandingInvoices(res.data);
            } catch (error) {
                showToast(t('common.error'), 'error');
            }
        } else {
            setOutstandingInvoices([]);
        }
    };

    const handleAllocationChange = (invoiceId, amount) => {
        const existing = formData.allocations.find(a => a.invoice_id === invoiceId);
        if (existing) {
            setFormData({
                ...formData,
                allocations: formData.allocations.map(a =>
                    a.invoice_id === invoiceId ? { ...a, allocated_amount: amount } : a
                )
            });
        } else {
            setFormData({
                ...formData,
                allocations: [...formData.allocations, { invoice_id: invoiceId, allocated_amount: amount }]
            });
        }
    };

    const handleAmountChange = (e) => {
        const nextForm = { ...formData, amount: e.target.value };
        setFormData(nextForm);
        if (outstandingInvoices.length > 0) {
            requestAllocationPreview(nextForm, { auto_allocate: true }, true).catch(() => {
                showToast(t('common.error'), 'error');
            });
        }
    };

    const handleAutoAllocate = () => {
        if (isPositiveDecimal(formData.amount) && outstandingInvoices.length > 0) {
            requestAllocationPreview(formData, { auto_allocate: true }, true).catch(() => {
                showToast(t('common.error'), 'error');
            });
        }
    };

    // Receive/Pay all outstanding
    const handleReceiveAll = () => {
        const targetType = formData.voucher_type === 'receipt' ? 'sales' : 'sales_return';
        const relevantInvoices = outstandingInvoices.filter(inv => inv.invoice_type === targetType);

        if (relevantInvoices.length > 0) {
            requestAllocationPreview(formData, { pay_all: true }, true).catch(() => {
                showToast(t('common.error'), 'error');
            });
        }
    };

    const handleQuickFill = (invoiceId) => {
        requestAllocationPreview(formData, { fill_invoice_id: invoiceId }, true).catch(() => {
            showToast(t('common.error'), 'error');
        });
    };

    useEffect(() => {
        if (!formData.customer_id) {
            setAllocationPreview(null);
            return undefined;
        }
        const timer = setTimeout(() => {
            requestAllocationPreview(formData).catch(() => {
                setAllocationPreview(null);
            });
        }, 300);
        return () => clearTimeout(timer);
    }, [formData.customer_id, formData.amount, formData.allocations, formData.voucher_type, formData.voucher_date, currentBranch, currency]);

    const handleSubmit = async (e) => {
        e.preventDefault();

        if (!formData.customer_id) {
            showToast(t('sales.receipts.form.errors.customer_required'), 'error');
            return;
        }
        if (!isPositiveDecimal(formData.amount)) {
            showToast(t('sales.receipts.form.errors.amount_required'), 'error');
            return;
        }
        if (isOverAllocated) {
            showToast(t('sales.receipts.form.errors.allocation_error'), 'error');
            return;
        }
        if (!formData.payment_method) {
            showToast(t('sales.receipts.form.errors.payment_method_required'), 'error');
            return;
        }

        setLoading(true);
        try {
            const preview = await requestAllocationPreview(formData);
            if (preview?.over_allocated) {
                showToast(t('sales.receipts.form.errors.allocation_error'), 'error');
                setLoading(false);
                return;
            }
            const sanitizedData = {
                ...formData,
                amount: String(preview?.amount || formData.amount || '0'),
                customer_id: parseInt(formData.customer_id),
                branch_id: currentBranch?.id,
                party_site_id: formData.party_site_id ? parseInt(formData.party_site_id) : null,
                bank_account_id: formData.bank_account_id ? parseInt(formData.bank_account_id) : null,
                check_date: formData.check_date || null,
                check_number: formData.check_number || null,
                reference: formData.reference || null,
                notes: formData.notes || null,
                allocations: (preview?.allocations || formData.allocations).filter(a => isPositiveDecimal(a.allocated_amount)).map(a => ({
                    invoice_id: parseInt(a.invoice_id),
                    allocated_amount: String(a.allocated_amount)
                }))
            };

            if (formData.voucher_type === 'receipt') {
                await salesAPI.createReceipt(sanitizedData);
            } else {
                await salesAPI.createPayment(sanitizedData);
            }

            showToast(t('sales.receipts.form.errors.create_success'), 'success');
            navigate(formData.voucher_type === 'refund' ? '/sales/payments' : '/sales/receipts');
        } catch (error) {
            showToast(t('sales.receipts.form.errors.create_failed') + ': ' + (error.response?.data?.detail || error.message), 'error');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="workspace fade-in">
            <div className="workspace-header">
                <BackButton />
                <h1 className="workspace-title">
                    {formData.voucher_type === 'receipt' ? t('sales.receipts.form.create_title') : t('sales.payments.form.create_title')}
                </h1>
                <p className="workspace-subtitle">
                    {formData.voucher_type === 'receipt' ? t('sales.receipts.form.create_subtitle') : t('sales.payments.form.create_subtitle')}
                </p>
            </div>

            <form onSubmit={handleSubmit}>
                <div className="space-y-6">
                    {/* Voucher Type Toggle */}
                    <div className="card" style={{ padding: '24px', background: formData.voucher_type === 'receipt' ? '#ecfdf5' : '#fef2f2', border: `1px solid ${formData.voucher_type === 'receipt' ? '#10b981' : '#fecaca'}`, borderRadius: '12px' }}>
                        <div style={{ display: 'flex', gap: '40px', alignItems: 'center', justifyContent: 'center' }}>
                            <label className="form-label" style={{ marginBottom: 0, fontSize: '1.1rem', fontWeight: 'bold' }}>{t('buying.payments.form.type_label')}</label>
                            <label style={{ display: 'flex', alignItems: 'center', gap: '12px', cursor: 'pointer', padding: '12px 24px', background: formData.voucher_type === 'receipt' ? 'white' : 'transparent', borderRadius: '8px', border: formData.voucher_type === 'receipt' ? '2px solid #10b981' : '2px solid transparent' }}>
                                <input
                                    type="radio"
                                    name="voucher_type"
                                    value="receipt"
                                    checked={formData.voucher_type === 'receipt'}
                                    onChange={() => setFormData(prev => ({ ...prev, voucher_type: 'receipt', allocations: [] }))}
                                    style={{ width: '20px', height: '20px' }}
                                />
                                <span style={{ fontWeight: 'bold', fontSize: '1.2rem', color: '#059669' }}>{t('sales.receipts.form.type_receipt')}</span>
                            </label>
                            <label style={{ display: 'flex', alignItems: 'center', gap: '12px', cursor: 'pointer', padding: '12px 24px', background: formData.voucher_type === 'refund' ? 'white' : 'transparent', borderRadius: '8px', border: formData.voucher_type === 'refund' ? '2px solid #dc2626' : '2px solid transparent' }}>
                                <input
                                    type="radio"
                                    name="voucher_type"
                                    value="refund"
                                    checked={formData.voucher_type === 'refund'}
                                    onChange={() => setFormData(prev => ({ ...prev, voucher_type: 'refund', allocations: [] }))}
                                    style={{ width: '20px', height: '20px' }}
                                />
                                <span style={{ fontWeight: 'bold', fontSize: '1.2rem', color: '#dc2626' }}>{t('sales.payments.form.type_refund')}</span>
                            </label>
                        </div>
                    </div>
                    {/* Basic Info Card */}
                    <div className="card">
                        <h3 className="section-title">{t('sales.receipts.form.basic_info')}</h3>
                        <div className="grid grid-cols-2 gap-4 mt-4">
                            <FormField label={t('sales.receipts.form.customer')} required>
                                <select
                                    required
                                    value={formData.customer_id}
                                    onChange={handleCustomerChange}
                                    className="form-input"
                                    disabled={!!location.state?.fromInvoice}
                                >
                                    <option value="">{t('sales.receipts.form.customer_placeholder')}</option>
                                    {customers.map(c => (
                                        <option key={c.id} value={c.id}>{c.name}</option>
                                    ))}
                                </select>
                            </FormField>

                            <FormField>
                                <CustomDatePicker
                                    label={t('sales.receipts.form.date')}
                                    selected={formData.voucher_date}
                                    onChange={(dateStr) => setFormData({ ...formData, voucher_date: dateStr })}
                                    required
                                />
                            </FormField>
                        </div>

                        {/* Customer Info Display (from CustomerPaymentForm) */}
                        {selectedCustomer && (
                            <div className="mt-4 p-4 bg-blue-50 rounded-lg border border-blue-200">
                                <div className="grid grid-cols-2 gap-4">
                                    <div>
                                        <span className="text-sm text-gray-600">{t('sales.payments.form.customer_info.name')}: </span>
                                        <span className="font-bold">{selectedCustomer.name}</span>
                                    </div>
                                    <div>
                                        <span className="text-sm text-gray-600">{t('sales.payments.form.customer_info.current_balance')}: </span>
                                        <span className={`font-bold ${isNegativeDecimal(selectedCustomer.current_balance) ? 'text-green-600' : 'text-red-600'}`}>
                                            {formatNumber(selectedCustomer.current_balance)} {currency}
                                            {isNegativeDecimal(selectedCustomer.current_balance) && ` (${t('sales.payments.form.customer_info.credit_label')})`}
                                        </span>
                                    </div>
                                </div>
                            </div>
                        )}
                    </div>


                    {/* Allocation Grid */}
                    <div className="card">
                        <div className="flex justify-between items-center mb-4">
                            <h3 className="section-title">{t('sales.receipts.form.allocation_title')}</h3>
                            <div className="flex items-center gap-4">
                                <div className="text-sm text-gray-500">
                                    {t('sales.receipts.form.total_allocated')}: <span className="font-bold text-primary">{moneyOrDash(previewTotalAllocated)} {currency}</span>
                                </div>
                                {outstandingInvoices.length > 0 && (
                                    <div style={{ display: 'flex', gap: '8px' }}>
                                        <button
                                            type="button"
                                            onClick={handleReceiveAll}
                                            className="btn btn-sm bg-blue-600 text-white hover:bg-blue-700"
                                        >
                                            💰 {t('sales.receipts.form.receive_all')}
                                        </button>
                                        {isPositiveDecimal(formData.amount) && (
                                            <button
                                                type="button"
                                                onClick={handleAutoAllocate}
                                                className="btn btn-sm btn-secondary"
                                            >
                                                🔄 {t('sales.receipts.form.auto_allocate')}
                                            </button>
                                        )}
                                    </div>
                                )}
                            </div>
                        </div>

                        {outstandingInvoices.filter(inv => formData.voucher_type === 'receipt' ? inv.invoice_type === 'sales' : inv.invoice_type === 'sales_return').length === 0 ? (
                            <div className="p-8 text-center text-gray-400 bg-gray-50 rounded-lg border-2 border-dashed">
                                {formData.customer_id ? (formData.voucher_type === 'receipt' ? t('sales.receipts.form.no_invoices') : t('sales.payments.form.no_returns')) : t('sales.receipts.form.select_customer_hint')}
                            </div>
                        ) : (
                            <div className="overflow-x-auto">
                                <table className="data-table">
                                    <thead>
                                        <tr>
                                            <th>{t('sales.receipts.form.table.invoice_number')}</th>
                                            <th>{t('sales.receipts.form.table.date')}</th>
                                            <th style={{ width: '100px' }}>{t('sales.receipts.form.table.total')}</th>
                                            <th style={{ width: '100px' }}>{t('sales.receipts.form.table.remaining')}</th>
                                            <th style={{ width: '250px' }}>{t('sales.receipts.form.table.allocated')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {outstandingInvoices.filter(inv => formData.voucher_type === 'receipt' ? inv.invoice_type === 'sales' : inv.invoice_type === 'sales_return').map(inv => (
                                            <tr key={inv.id}>
                                                <td className="font-medium text-primary">{inv.invoice_number}</td>
                                                <td>{formatShortDate(inv.invoice_date)}</td>
                                                <td>
                                                    {formatNumber(inv.total)}
                                                    <small className="mx-1 text-muted">{inv.currency || currency}</small>
                                                </td>
                                                <td className="font-bold text-red-600">
                                                    {formatNumber(inv.remaining_balance)}
                                                    <small className="mx-1 text-muted">{inv.currency || currency}</small>
                                                    {inv.exchange_rate && inv.exchange_rate !== 1 && (
                                                        <div className="text-[10px] text-gray-500 font-normal">
                                                            Rate: {formatNumber(inv.exchange_rate, 4)}
                                                        </div>
                                                    )}
                                                </td>
                                                <td>
                                                    <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
                                                        <input
                                                            type="text"
                                                            inputMode="decimal"
                                                            max={inv.remaining_balance}
                                                            placeholder="0.00"
                                                            value={formData.allocations.find(a => a.invoice_id === inv.id)?.allocated_amount || ''}
                                                            onChange={(e) => handleAllocationChange(inv.id, e.target.value)}
                                                            className="form-input border-blue-200 focus:border-blue-500"
                                                            style={{ flex: 1, minWidth: '80px' }}
                                                        />
                                                        <button
                                                            type="button"
                                                            onClick={() => handleQuickFill(inv.id)}
                                                            className="btn btn-sm bg-green-100 text-green-700 hover:bg-green-200 border border-green-300"
                                                            title={t('sales.receipts.form.table.quick_fill')}
                                                            style={{ padding: '4px 8px', fontSize: '11px', whiteSpace: 'nowrap', flexShrink: 0 }}
                                                        >
                                                            ✓ {t('sales.receipts.form.table.quick_fill')}
                                                        </button>
                                                    </div>
                                                </td>
                                            </tr>
                                        ))}
                                    </tbody>
                                </table>
                            </div>
                        )}
                    </div>

                    {/* Footer Totals & Payment (Matched to InvoiceForm) */}
                    <div style={{ display: 'flex', gap: '32px', alignItems: 'flex-start', marginTop: '24px' }}>
                        <div style={{ flex: 1 }}>
                            <h4 style={{ marginBottom: '12px' }}>{t('sales.receipts.form.payment_info')}</h4>

                            <div className="grid grid-cols-2 gap-4">
                                <div className="form-group">
                                    <label className="form-label">{formData.voucher_type === 'receipt' ? t('sales.receipts.form.received_amount') : t('sales.payments.form.amount_paid')} *</label>
                                    <div className="relative">
                                        <input
                                            type="text"
                                            inputMode="decimal"
                                            required
                                            value={formData.amount}
                                            onChange={handleAmountChange}
                                            className="form-input"
                                        />
                                        <span className="absolute left-3 top-2 text-gray-400">{currency}</span>
                                    </div>
                                </div>

                                <FormField label={t('sales.receipts.form.payment_method')} required style={{ marginTop: '8px' }}>
                                    <div style={{ display: 'flex', gap: '16px' }}>
                                        <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                                            <input
                                                type="radio"
                                                name="payment_method"
                                                value="cash"
                                                checked={formData.payment_method === 'cash'}
                                                onChange={(e) => setFormData({ ...formData, payment_method: e.target.value })}
                                            />
                                            <span style={{ fontSize: '14px' }}>{t('sales.receipts.payment_methods.cash')}</span>
                                        </label>
                                        <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                                            <input
                                                type="radio"
                                                name="payment_method"
                                                value="bank"
                                                checked={formData.payment_method === 'bank'}
                                                onChange={(e) => setFormData({ ...formData, payment_method: e.target.value })}
                                            />
                                            <span style={{ fontSize: '14px' }}>{t('sales.receipts.payment_methods.bank')}</span>
                                        </label>
                                        <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                                            <input
                                                type="radio"
                                                name="payment_method"
                                                value="check"
                                                checked={formData.payment_method === 'check'}
                                                onChange={(e) => setFormData({ ...formData, payment_method: e.target.value })}
                                            />
                                            <span style={{ fontSize: '14px' }}>{t('sales.receipts.payment_methods.check')}</span>
                                        </label>
                                    </div>
                                </FormField>
                            </div>

                            {formData.payment_method === 'check' && (
                                <div className="grid grid-cols-2 gap-4 mt-2 p-4 bg-gray-50 rounded-lg">
                                    <FormField label={t('sales.receipts.form.check_number')}>
                                        <input
                                            type="text"
                                            value={formData.check_number}
                                            onChange={(e) => setFormData({ ...formData, check_number: e.target.value })}
                                            className="form-input"
                                        />
                                    </FormField>
                                    <FormField>
                                        <CustomDatePicker
                                            label={t('sales.receipts.form.check_date')}
                                            selected={formData.check_date}
                                            onChange={(dateStr) => setFormData({ ...formData, check_date: dateStr })}
                                        />
                                    </FormField>
                                </div>
                            )}

                            <FormField label={t('sales.receipts.form.notes')} className="mt-4">
                                <textarea
                                    rows="2"
                                    value={formData.notes}
                                    onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
                                    className="form-input"
                                    placeholder={t('sales.receipts.form.notes_placeholder')}
                                />
                            </FormField>
                        </div>

                        <div style={{ width: '300px', padding: '24px', background: 'var(--bg-secondary)', borderRadius: '8px' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                                <span>{formData.voucher_type === 'receipt' ? t('sales.receipts.form.summary.received') : t('sales.payments.form.summary.amount_paid')}</span>
                                <span>{currency} {moneyOrDash(formData.amount)}</span>
                            </div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                                <span>{t('sales.receipts.form.summary.allocated')}</span>
                                <span>{currency} {moneyOrDash(previewTotalAllocated)}</span>
                            </div>

                            {formData.voucher_type === 'refund' && selectedCustomer && isNegativeDecimal(selectedCustomer.current_balance) && (
                                <>
                                    <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                                        <span>{t('sales.payments.form.summary.credit_balance')}</span>
                                        <span className="text-green-600">
                                            {currency} {formatNumber(selectedCustomer.current_balance)}
                                        </span>
                                    </div>
                                </>
                            )}
                            <div style={{ borderTop: '1px solid var(--border-color)', margin: '12px 0' }}></div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                                <span style={{ fontWeight: 'bold' }}>{t('sales.receipts.form.summary.remaining')}</span>
                                <span style={{ fontWeight: 'bold', fontSize: '1.2rem' }} className={isPositiveDecimal(previewUnallocated) ? 'text-orange-600' : ''}>
                                    {currency} {moneyOrDash(previewUnallocated)}
                                </span>
                            </div>

                            <button
                                type="submit"
                                className="btn btn-primary"
                                style={{ width: '100%', marginTop: '24px', padding: '12px' }}
                                disabled={loading}
                            >
                                {loading ? t('sales.receipts.form.saving') : (formData.voucher_type === 'receipt' ? t('sales.receipts.form.save_btn') : t('sales.payments.form.save_btn'))}
                            </button>
                            <button
                                type="button"
                                className="btn btn-secondary mt-2"
                                style={{ width: '100%' }}
                                onClick={() => navigate('/sales/receipts')}
                            >
                                {t('sales.receipts.form.cancel')}
                            </button>

                            {isPositiveDecimal(previewUnallocated) && (
                                <div className="mt-4 p-3 bg-orange-50 border border-orange-200 rounded text-[10px] text-orange-800">
                                    <span className="font-bold">{t('sales.receipts.form.summary.advance_payment_note')}</span>
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            </form>
        </div>
    );
}

export default ReceiptForm;
