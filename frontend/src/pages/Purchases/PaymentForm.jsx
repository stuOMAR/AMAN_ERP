import React, { useState, useEffect } from 'react';
import { useNavigate, useLocation } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { purchasesAPI, inventoryAPI, currenciesAPI, treasuryAPI } from '../../utils/api';
import { getCurrency } from '../../utils/auth';
import CustomDatePicker from '../../components/common/CustomDatePicker';
import { useBranch } from '../../context/BranchContext';
import { useToast } from '../../context/ToastContext';
import { formatShortDate } from '../../utils/dateUtils';
import BackButton from '../../components/common/BackButton';
import FormField from '../../components/common/FormField';
import { formatNumber } from '../../utils/format';

function PaymentForm() {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const location = useLocation();
    const baseCurrency = getCurrency();
    const { currentBranch } = useBranch();
    const { showToast } = useToast();
    const [recordCurrency, setRecordCurrency] = useState(baseCurrency);
    const [exchangeRate, setExchangeRate] = useState('1');
    const [transactionRate, setTransactionRate] = useState(''); // Rate between Record and Treasury
    const [loading, setLoading] = useState(false);
    const [initialLoad, setInitialLoad] = useState(true);
    const [suppliers, setSuppliers] = useState([]);
    const [currenciesList, setCurrenciesList] = useState([]);
    const [outstandingInvoices, setOutstandingInvoices] = useState([]);
    const [treasuryAccounts, setTreasuryAccounts] = useState([]);
    const [paymentPreview, setPaymentPreview] = useState(null);
    const [previewLoading, setPreviewLoading] = useState(false);
    const [formData, setFormData] = useState({
        supplier_id: '',
        party_site_id: '',
        voucher_date: new Date().toISOString().split('T')[0],
        amount: '',
        voucher_type: 'payment', // 'payment' or 'refund'
        payment_method: '',
        bank_account_id: null,
        check_number: '',
        check_date: '',
        reference: '',
        notes: '',
        allocations: []
    });

    const hasNonZeroDecimalInput = (value) => {
        const normalized = String(value || '').trim();
        return /^\d*(?:\.\d*)?$/.test(normalized) && !/^0*(?:\.0*)?$/.test(normalized);
    };

    const moneyOrDash = (value) => value !== null && value !== undefined && value !== '' ? formatNumber(value) : '—';

    const selectedTreasury = formData.bank_account_id
        ? treasuryAccounts.find(acc => String(acc.id) === String(formData.bank_account_id))
        : null;
    const previewLineByInvoiceId = new Map((paymentPreview?.lines || []).map(line => [line.invoice_id, line]));
    const totalAllocated = paymentPreview?.total_allocated ?? null;
    const unallocatedAmount = paymentPreview?.unallocated_amount ?? null;

    const buildPreviewPayload = (nextForm = formData, options = {}) => ({
        supplier_id: nextForm.supplier_id ? parseInt(nextForm.supplier_id, 10) : null,
        voucher_date: nextForm.voucher_date,
        amount: String(nextForm.amount || '0'),
        branch_id: currentBranch?.id || null,
        voucher_type: nextForm.voucher_type || 'payment',
        currency: recordCurrency,
        exchange_rate: String(exchangeRate || '1'),
        treasury_account_id: nextForm.bank_account_id ? parseInt(nextForm.bank_account_id, 10) : null,
        bank_account_id: nextForm.bank_account_id ? parseInt(nextForm.bank_account_id, 10) : null,
        transaction_rate: transactionRate ? String(transactionRate) : null,
        allocations: (nextForm.allocations || [])
            .filter(a => hasNonZeroDecimalInput(a.allocated_amount))
            .map(a => ({
                invoice_id: parseInt(a.invoice_id, 10),
                allocated_amount: String(a.allocated_amount),
            })),
        ...options,
    });

    const refreshPaymentPreview = async (nextForm = formData, options = {}) => {
        if (!currentBranch?.id) return null;
        setPreviewLoading(true);
        try {
            const res = await purchasesAPI.previewPayment(buildPreviewPayload(nextForm, options));
            const result = res.data;
            setPaymentPreview(result);
            if (result?.transaction_rate) setTransactionRate(result.transaction_rate);
            return result;
        } catch (error) {
            setPaymentPreview(null);
            showToast(t('common.error'), 'error');
            return null;
        } finally {
            setPreviewLoading(false);
        }
    };

    const handleVoucherDateChange = async (dateStr) => {
        const nextForm = { ...formData, voucher_date: dateStr };
        setFormData(nextForm);
        await refreshPaymentPreview(nextForm);
    };

    const handleVoucherTypeChange = async (voucherType) => {
        const nextForm = { ...formData, voucher_type: voucherType, allocations: [] };
        setFormData(nextForm);
        const result = await refreshPaymentPreview(nextForm);
        if (result) {
            setFormData(prev => ({ ...prev, allocations: result.allocations || [] }));
        }
    };

    useEffect(() => {
        const timer = setTimeout(() => {
            fetchInitialData()
        }, 300)
        return () => clearTimeout(timer)
    }, [currentBranch]);

    const fetchInitialData = async () => {
        try {
            const res = await inventoryAPI.listSuppliers({ branch_id: currentBranch?.id });
            setSuppliers(res.data);

            const currRes = await currenciesAPI.list();
            setCurrenciesList(currRes.data);

            const treasRes = await treasuryAPI.listAccounts(currentBranch?.id);
            setTreasuryAccounts(treasRes.data);

            // Check if we have a prefilled invoice from state
            if (location.state?.fromInvoice) {
                const inv = location.state.fromInvoice;
                const nextForm = {
                    ...formData,
                    supplier_id: inv.supplier_id,
                    amount: String(inv.remaining_balance || ''),
                    notes: t('buying.payments.form.prefilled_note', { number: inv.invoice_number }) || `سداد فاتورة مشتريات رقم ${inv.invoice_number}`
                };
                setFormData(nextForm);

                // Fetch outstanding invoices for this supplier to show the grid
                const outstandingRes = await purchasesAPI.getOutstandingInvoices(inv.supplier_id, { branch_id: currentBranch?.id });
                setOutstandingInvoices(outstandingRes.data);

                const result = await refreshPaymentPreview(nextForm, { fill_invoice_id: inv.id });
                if (result) {
                    setFormData(prev => ({
                        ...prev,
                        amount: result.amount || prev.amount,
                        allocations: result.allocations || [],
                    }));
                }
            }
        } catch (error) {
            showToast(t('common.error'), 'error');
        } finally {
            setInitialLoad(false);
        }
    };

    const handleSupplierChange = async (e) => {
        const supplierId = e.target.value;
        const nextForm = { ...formData, supplier_id: supplierId, allocations: [] };
        setFormData(nextForm);
        setPaymentPreview(null);

        if (supplierId) {
            try {
                const res = await purchasesAPI.getOutstandingInvoices(supplierId, { branch_id: currentBranch?.id });
                setOutstandingInvoices(res.data);

                // Set currency from supplier data
                const selectedSupp = suppliers.find(s => s.id == supplierId);
                const nextCurrency = selectedSupp?.currency || baseCurrency;
                const currencyData = currenciesList.find(c => c.code === nextCurrency);
                const nextRate = currencyData ? String(currencyData.current_rate || '1') : '1';
                setRecordCurrency(nextCurrency);
                setExchangeRate(nextRate);
                setTransactionRate('');

                const result = await refreshPaymentPreview(nextForm, { auto_allocate: true, currency: nextCurrency, exchange_rate: nextRate, transaction_rate: null });
                if (result) {
                    setFormData(prev => ({ ...prev, allocations: result.allocations || [] }));
                }
            } catch (error) {
                showToast(t('common.error'), 'error');
            }
        } else {
            setOutstandingInvoices([]);
            setPaymentPreview(null);
        }
    };

    const handleTreasuryChange = async (e) => {
        const treasuryId = e.target.value;
        const nextForm = { ...formData, bank_account_id: treasuryId };
        setFormData(nextForm);
        setTransactionRate('');
        await refreshPaymentPreview(nextForm, { transaction_rate: null });
    };

    const handleRecordCurrencyChange = async (newCurrency) => {
        let shouldClear = false;
        if (formData.allocations.length > 0) {
            if (!window.confirm(t('buying.payments.form.validation.confirm_currency_change'))) {
                return;
            }
            shouldClear = true;
        }

        setRecordCurrency(newCurrency);
        setTransactionRate('');
        const nextForm = { ...formData, allocations: shouldClear ? [] : formData.allocations };
        if (shouldClear) setFormData(nextForm);

        // Fetch exchange rate for the new currency
        try {
            const currencyData = currenciesList.find(c => c.code === newCurrency);
            const newVRate = currencyData ? String(currencyData.current_rate || '1') : '1';
            setExchangeRate(newVRate);
            await refreshPaymentPreview(nextForm, { currency: newCurrency, exchange_rate: newVRate, transaction_rate: null });
        } catch (error) {
            showToast(t('common.error'), 'error');
            setExchangeRate('1');
        }
    };

    const handleAllocationChange = async (invoiceId, amount) => {
        const val = amount;

        const existing = formData.allocations.find(a => a.invoice_id === invoiceId);
        let nextForm;
        if (existing) {
            nextForm = {
                ...formData,
                allocations: formData.allocations.map(a =>
                    a.invoice_id === invoiceId ? { ...a, allocated_amount: val } : a
                )
            };
        } else {
            nextForm = {
                ...formData,
                allocations: [...formData.allocations, { invoice_id: invoiceId, allocated_amount: val }]
            };
        }
        setFormData(nextForm);
        await refreshPaymentPreview(nextForm);
    };

    const handleAmountChange = async (e) => {
        const newAmount = e.target.value;
        const nextForm = { ...formData, amount: newAmount };
        setFormData(nextForm);

        if (outstandingInvoices.length > 0) {
            const result = await refreshPaymentPreview(nextForm, { auto_allocate: true });
            if (result) {
                setFormData(prev => ({ ...prev, amount: newAmount, allocations: result.allocations || [] }));
            }
        } else {
            await refreshPaymentPreview(nextForm);
        }
    };

    const handleAutoAllocate = async () => {
        const result = await refreshPaymentPreview(formData, { auto_allocate: true });
        if (result) {
            setFormData(prev => ({ ...prev, allocations: result.allocations || [] }));
        }
    };

    // Pay all outstanding invoices in full (filtered by currency)
    const handlePayAll = async () => {
        if (outstandingInvoices.length > 0) {
            const filteredInvoices = outstandingInvoices.filter(inv =>
                (inv.invoice_type === (formData.voucher_type === 'payment' ? 'purchase' : 'purchase_return'))
            );

            if (filteredInvoices.length === 0) {
                showToast(t('buying.payments.form.validation.no_invoices_matching_currency') || `لا توجد فواتير مطابقة لعملة السند (${recordCurrency})`, 'error');
                return;
            }

            const result = await refreshPaymentPreview(formData, { pay_all: true });
            if (result) {
                setFormData(prev => ({
                    ...prev,
                    amount: result.amount || prev.amount,
                    allocations: result.allocations || [],
                }));
            }
        }
    };

    // Quick fill a single invoice with its full remaining balance
    const handleQuickFill = async (invoiceId) => {
        const result = await refreshPaymentPreview(formData, { fill_invoice_id: invoiceId });
        if (result) {
            setFormData(prev => ({ ...prev, allocations: result.allocations || [] }));
        }
    };

    const handleSubmit = async (e) => {
        e.preventDefault();

        if (!formData.supplier_id) {
            showToast(t('buying.payments.form.validation.select_supplier'), 'error');
            return;
        }

        if (!hasNonZeroDecimalInput(formData.amount)) {
            showToast(t('buying.payments.form.validation.invalid_amount'), 'error');
            return;
        }

        if (paymentPreview?.over_allocated) {
            showToast(t('buying.payments.form.validation.allocation_exceeded'), 'error');
            return;
        }

        if (!formData.payment_method) {
            showToast(t('buying.payments.form.validation.payment_method_required'), 'error');
            return;
        }

        setLoading(true);
        try {
            const sanitizedData = {
                ...formData,
                amount: String(formData.amount || '0'),
                supplier_id: parseInt(formData.supplier_id),
                branch_id: currentBranch?.id,
                bank_account_id: formData.bank_account_id ? parseInt(formData.bank_account_id) : null,
                check_date: formData.check_date || null,
                check_number: formData.check_number || null,
                reference: formData.reference || null,
                notes: formData.notes || null,
                allocations: formData.allocations.filter(a => hasNonZeroDecimalInput(a.allocated_amount)).map(a => ({
                    invoice_id: parseInt(a.invoice_id),
                    allocated_amount: String(a.allocated_amount)
                })),
                currency: recordCurrency,
                exchange_rate: String(exchangeRate || '1'),
                treasury_account_id: formData.bank_account_id ? parseInt(formData.bank_account_id) : null,
                transaction_rate: transactionRate ? String(transactionRate) : null
            };

            await purchasesAPI.createPayment(sanitizedData);
            showToast(t('buying.payments.form.validation.success'), 'success');
            navigate('/buying/payments');
        } catch (error) {
            showToast(t('buying.payments.form.error_saving') + (error.response?.data?.detail || error.message), 'error');
        } finally {
            setLoading(false);
        }
    };

    return (
        <div className="workspace fade-in">
            {loading && !initialLoad && <div style={{position:'fixed',top:10,right:10,zIndex:1000,background:'var(--bg-card)',padding:'8px 16px',borderRadius:8,boxShadow:'0 2px 8px rgba(0,0,0,0.15)',fontSize:13}}>جاري التحميل...</div>}
            <div className="workspace-header">
                <BackButton />
                <h1 className="workspace-title">{formData.voucher_type === 'payment' ? t('buying.payments.form.create_title') : t('buying.payments.form.create_refund_title')}</h1>
                <p className="workspace-subtitle">{formData.voucher_type === 'payment' ? t('buying.payments.form.create_subtitle') : t('buying.payments.form.create_refund_subtitle')}</p>
            </div>

            <form onSubmit={handleSubmit}>
                <div className="space-y-6">
                    {/* Basic Info Card */}
                    <div className="card">
                        <h3 className="section-title text-purple-700">{t('buying.payments.form.basic_info')}</h3>
                        <div className="grid grid-cols-2 gap-4 mt-4">
                            <div className="grid grid-cols-2 gap-4 mb-4">
                                <FormField label={t('buying.payments.form.supplier')}>
                                    <select
                                        required
                                        value={formData.supplier_id}
                                        onChange={handleSupplierChange}
                                        className="form-input"
                                        disabled={!!location.state?.fromInvoice}
                                    >
                                        <option value="">{t('buying.payments.form.supplier_placeholder')}</option>
                                        {suppliers.map(s => (
                                            <option key={s.id} value={s.id}>{s.name}</option>
                                        ))}
                                    </select>
                                </FormField>

                                <div className="form-group">
                                    <CustomDatePicker
                                        label={t('buying.payments.form.date')}
                                        selected={formData.voucher_date}
                                        onChange={handleVoucherDateChange}
                                        required
                                    />
                                </div>
                            </div>

                            <FormField label={t('buying.payments.form.payment_currency')}>
                                <select
                                    value={recordCurrency}
                                    onChange={(e) => handleRecordCurrencyChange(e.target.value)}
                                    className="form-input"
                                >
                                    {currenciesList.map(c => (
                                        <option key={c.code} value={c.code}>{c.code} - {c.name}</option>
                                    ))}
                                </select>
                            </FormField>
                        </div>
                    </div>

                    {/* Voucher Type Toggle */}
                    <div className="card" style={{ padding: '16px', background: formData.voucher_type === 'refund' ? '#ecfdf5' : '#fef2f2', border: `1px solid ${formData.voucher_type === 'refund' ? '#10b981' : '#fecaca'}` }}>
                        <div style={{ display: 'flex', gap: '24px', alignItems: 'center' }}>
                            <label className="form-label" style={{ marginBottom: 0 }}>{t('buying.payments.form.type_label')}</label>
                            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                                <input
                                    type="radio"
                                    name="voucher_type"
                                    value="payment"
                                    checked={formData.voucher_type === 'payment'}
                                    onChange={() => handleVoucherTypeChange('payment')}
                                />
                                <span style={{ fontWeight: formData.voucher_type === 'payment' ? 'bold' : 'normal', color: '#dc2626' }}>{t('buying.payments.form.type_payment')}</span>
                            </label>
                            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                                <input
                                    type="radio"
                                    name="voucher_type"
                                    value="refund"
                                    checked={formData.voucher_type === 'refund'}
                                    onChange={() => handleVoucherTypeChange('refund')}
                                />
                                <span style={{ fontWeight: formData.voucher_type === 'refund' ? 'bold' : 'normal', color: '#059669' }}>{t('buying.payments.form.type_refund')}</span>
                            </label>
                        </div>
                    </div>

                    {/* Allocation Grid */}
                    <div className="card">
                        <div className="flex justify-between items-center mb-4">
                            <h3 className="section-title text-purple-700">{t('buying.payments.form.allocation_title')}</h3>
                            <div className="flex items-center gap-4">
                                <div className="text-sm text-gray-500">
                                    {t('buying.payments.form.allocated_total')} <span className="font-bold text-purple-700">{moneyOrDash(totalAllocated)} {recordCurrency}</span>
                                </div>
                                {outstandingInvoices.length > 0 && (
                                    <div style={{ display: 'flex', gap: '8px' }}>
                                        <button
                                            type="button"
                                            onClick={handlePayAll}
                                            className="btn btn-sm bg-purple-600 text-white hover:bg-purple-700"
                                        >
                                            {t('buying.payments.form.pay_all')}
                                        </button>
                                        {paymentPreview?.can_auto_allocate && (
                                            <button
                                                type="button"
                                                onClick={handleAutoAllocate}
                                                className="btn btn-sm btn-secondary"
                                            >
                                                {t('buying.payments.form.auto_allocate')}
                                            </button>
                                        )}
                                    </div>
                                )}
                            </div>
                        </div>

                        {outstandingInvoices.filter(inv => formData.voucher_type === 'payment' ? ['purchase', 'purchase_debit_note'].includes(inv.invoice_type) : ['purchase_return', 'purchase_credit_note'].includes(inv.invoice_type)).length === 0 ? (
                            <div className="p-8 text-center text-gray-400 bg-gray-50 rounded-lg border-2 border-dashed">
                                {formData.supplier_id ? (formData.voucher_type === 'payment' ? t('buying.payments.form.empty_invoices') : t('buying.payments.form.empty_returns')) : t('buying.payments.form.select_supplier_first')}
                            </div>
                        ) : (
                            <div className="overflow-x-auto">
                                <table className="data-table">
                                    <thead>
                                        <tr>
                                            <th>{t('buying.payments.table.invoice_number')}</th>
                                            <th>{t('buying.payments.table.date')}</th>
                                            <th>{t('buying.payments.table.currency')}</th>
                                            <th>{t('buying.payments.table.total')}</th>
                                            <th>{formData.voucher_type === 'payment' ? t('buying.payments.table.remaining_payment') : t('buying.payments.table.remaining_refund')}</th>
                                            <th style={{ width: '150px' }}>{formData.voucher_type === 'payment' ? t('buying.payments.table.allocated_amount') : t('buying.payments.table.refunded_amount')}</th>
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {outstandingInvoices.filter(inv => formData.voucher_type === 'payment' ? ['purchase', 'purchase_debit_note'].includes(inv.invoice_type) : ['purchase_return', 'purchase_credit_note'].includes(inv.invoice_type)).map(inv => (
                                            <tr key={inv.id} style={{ opacity: (inv.currency || baseCurrency) !== recordCurrency ? 0.6 : 1 }}>
                                                <td className="font-medium text-purple-700">{inv.invoice_number}</td>
                                                <td>{formatShortDate(inv.invoice_date)}</td>
                                                <td>
                                                    <span className={`badge ${(inv.currency || baseCurrency) === recordCurrency ? 'badge-primary' : 'badge-secondary'}`}>
                                                        {inv.currency || baseCurrency}
                                                    </span>
                                                </td>
                                                <td>{formatNumber(inv.total)}</td>
                                                <td className="font-bold text-red-600">{formatNumber(inv.remaining_balance)}</td>
                                                <td>
                                                    <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
                                                        <input
                                                            type="text"
                                                            inputMode="decimal"
                                                            step="0.01"
                                                            min="0"
                                                            placeholder="0.00"
                                                            value={formData.allocations.find(a => a.invoice_id === inv.id)?.allocated_amount || ''}
                                                            onChange={(e) => handleAllocationChange(inv.id, e.target.value)}
                                                            className="form-input border-purple-200 focus:border-purple-500"
                                                            style={{ flex: 1 }}
                                                        />
                                                        <button
                                                            type="button"
                                                            onClick={() => handleQuickFill(inv.id)}
                                                            className="btn btn-sm bg-green-100 text-green-700 hover:bg-green-200 border border-green-300"
                                                            title={t('buying.payments.table.quick_fill')}
                                                            style={{ padding: '4px 8px', fontSize: '12px' }}
                                                        >
                                                            {t('buying.payments.table.all')}
                                                        </button>
                                                    </div>
                                                    {recordCurrency !== (inv.currency || baseCurrency) && previewLineByInvoiceId.get(inv.id)?.invoice_currency_amount && (
                                                        <div className="text-[10px] text-gray-500 mt-1">
                                                            {t('common.equivalent')}: {formatNumber(previewLineByInvoiceId.get(inv.id).invoice_currency_amount)} {inv.currency || baseCurrency}
                                                        </div>
                                                    )}
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
                            <h4 style={{ marginBottom: '12px' }} className="text-purple-800">{t('buying.payments.form.payment_info')}</h4>

                            <div className="grid grid-cols-2 gap-4">
                                <FormField label={formData.voucher_type === 'payment' ? t('buying.payments.form.amount_paid') : t('buying.payments.form.amount_received')}>
                                    <div className="relative">
                                        <input
                                            type="text"
                                            inputMode="decimal"
                                            required
                                            step="0.01"
                                            min="0.01"
                                            value={formData.amount}
                                            onChange={handleAmountChange}
                                            className="form-input border-purple-200"
                                        />
                                        <span className="absolute left-3 top-2 text-gray-400">{recordCurrency}</span>
                                    </div>
                                </FormField>

                                <FormField label={t('buying.payments.form.payment_method')} style={{ marginTop: '8px' }}>
                                    <div style={{ display: 'flex', gap: '16px' }}>
                                        <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                                            <input
                                                type="radio"
                                                name="payment_method"
                                                value="cash"
                                                checked={formData.payment_method === 'cash'}
                                                onChange={(e) => setFormData({ ...formData, payment_method: e.target.value })}
                                            />
                                            <span style={{ fontSize: '14px' }}>{t('buying.payments.form.payment_methods.cash')}</span>
                                        </label>
                                        <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                                            <input
                                                type="radio"
                                                name="payment_method"
                                                value="bank"
                                                checked={formData.payment_method === 'bank'}
                                                onChange={(e) => setFormData({ ...formData, payment_method: e.target.value })}
                                            />
                                            <span style={{ fontSize: '14px' }}>{t('buying.payments.form.payment_methods.bank')}</span>
                                        </label>
                                        <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                                            <input
                                                type="radio"
                                                name="payment_method"
                                                value="check"
                                                checked={formData.payment_method === 'check'}
                                                onChange={(e) => setFormData({ ...formData, payment_method: e.target.value })}
                                            />
                                            <span style={{ fontSize: '14px' }}>{t('buying.payments.form.payment_methods.check')}</span>
                                        </label>
                                    </div>
                                </FormField>

                                {(formData.payment_method === 'cash' || formData.payment_method === 'bank') && (
                                    <div className="mt-4 p-4 bg-gray-50 rounded-lg border border-gray-100">
                                        <div className="grid grid-cols-[140px_1fr] gap-x-4 gap-y-4 items-center">

                                            {/* ROW 1: Bank/Cash Account */}
                                            <label className="text-sm font-medium text-gray-700">
                                                {formData.payment_method === 'cash' ? (t('buying.payments.form.cash_account')) : (t('buying.payments.form.bank_account'))}
                                            </label>
                                            <select
                                                required
                                                value={formData.bank_account_id || ''}
                                                onChange={handleTreasuryChange}
                                                className="form-input border-purple-200 w-full"
                                            >
                                                <option value="">{formData.payment_method === 'cash' ? (t('buying.payments.form.select_cash')) : (t('buying.payments.form.select_bank'))}</option>
                                                {treasuryAccounts
                                                    .filter(acc => formData.payment_method === 'cash' ? acc.account_type === 'cash' : acc.account_type === 'bank')
                                                    .map(acc => (
                                                        <option key={acc.id} value={acc.id}>
                                                            {acc.name} ({acc.currency})
                                                        </option>
                                                    ))
                                                }
                                            </select>

                                            {/* ROW 2: Transaction Rate (Treasury -> Voucher) - Conditional */}
                                            {formData.bank_account_id && treasuryAccounts.find(acc => acc.id == formData.bank_account_id)?.currency !== recordCurrency && (
                                                <>
                                                    <label className="text-sm font-medium text-purple-700">
                                                        {treasuryAccounts.find(acc => acc.id == formData.bank_account_id)?.currency === baseCurrency
                                                            ? (t('buying.payments.form.exchange_rate'))
                                                            : (t('buying.payments.form.transaction_rate'))}
                                                    </label>
                                                    <div className="relative">
                                                        <input
                                                            type="text"
                                                            inputMode="decimal"
                                                            step="0.000001"
                                                            value={transactionRate}
                                                            onChange={(e) => {
                                                                const newTRate = e.target.value;
                                                                setTransactionRate(newTRate);
                                                                refreshPaymentPreview(formData, { transaction_rate: newTRate ? newTRate : null });
                                                            }}
                                                            className="form-input form-input-sm w-full font-mono text-center border-purple-300 focus:border-purple-500 pr-16"
                                                            style={{ paddingRight: '4rem' }}
                                                        />
                                                        <span className="absolute left-3 top-1/2 -translate-y-1/2 text-xs text-gray-500 font-medium pointer-events-none select-none bg-gray-100 px-1 rounded">
                                                            {treasuryAccounts.find(acc => acc.id == formData.bank_account_id)?.currency} / {recordCurrency}
                                                        </span>
                                                    </div>
                                                </>
                                            )}

                                            {/* ROW 3: Document Accounting Rate - Conditional */}
                                            {recordCurrency !== baseCurrency && (
                                                !formData.bank_account_id ||
                                                (treasuryAccounts.find(acc => acc.id == formData.bank_account_id)?.currency !== recordCurrency &&
                                                    treasuryAccounts.find(acc => acc.id == formData.bank_account_id)?.currency !== baseCurrency)
                                            ) && (
                                                    <>
                                                        <label className="text-sm font-medium text-gray-600">
                                                            {t('buying.payments.form.document_exchange_rate')}
                                                        </label>
                                                        <div className="relative">
                                                            <input
                                                                type="text"
                                                                inputMode="decimal"
                                                                step="0.000001"
                                                                value={exchangeRate}
                                                                onChange={(e) => {
                                                                    setExchangeRate(e.target.value);
                                                                    setTransactionRate('');
                                                                    refreshPaymentPreview(formData, { exchange_rate: e.target.value, transaction_rate: null });
                                                                }}
                                                                className="form-input form-input-sm w-full font-mono text-center border-gray-300 pr-12"
                                                                style={{ paddingRight: '3rem' }}
                                                            />
                                                            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-xs text-gray-400 font-medium pointer-events-none select-none bg-gray-50 px-1 rounded">{baseCurrency}</span>
                                                        </div>
                                                    </>
                                                )}

                                            {/* ROW 4: Equivalent Display - Conditional */}
                                            {formData.bank_account_id && selectedTreasury?.currency !== recordCurrency && (
                                                <>
                                                    <label className="text-xs text-purple-800">
                                                        {t('common.equivalent')}:
                                                    </label>
                                                    <div className="font-bold font-mono text-sm text-purple-800 bg-purple-50 p-2 rounded border border-purple-100 text-center">
                                                        {moneyOrDash(paymentPreview?.treasury_amount)} {paymentPreview?.treasury_currency || selectedTreasury?.currency}
                                                    </div>
                                                </>
                                            )}
                                        </div>
                                    </div>
                                )}
                            </div>

                            {formData.payment_method === 'check' && (
                                <div className="grid grid-cols-2 gap-4 mt-2 p-4 bg-purple-50 rounded-lg">
                                    <FormField label={t('buying.payments.form.check_number')}>
                                        <input
                                            type="text"
                                            value={formData.check_number}
                                            onChange={(e) => setFormData({ ...formData, check_number: e.target.value })}
                                            className="form-input border-purple-200"
                                        />
                                    </FormField>
                                    <div className="form-group">
                                        <CustomDatePicker
                                            label={t('buying.payments.form.check_date')}
                                            selected={formData.check_date}
                                            onChange={(dateStr) => setFormData({ ...formData, check_date: dateStr })}
                                        />
                                    </div>
                                </div>
                            )}

                            <FormField label={t('buying.payments.form.notes')} className="mt-4">
                                <textarea
                                    rows="2"
                                    value={formData.notes}
                                    onChange={(e) => setFormData({ ...formData, notes: e.target.value })}
                                    className="form-input border-purple-100"
                                    placeholder={t('buying.payments.form.notes_placeholder')}
                                />
                            </FormField>
                        </div>

                        <div style={{ width: '300px', padding: '24px', background: 'var(--bg-secondary)', borderRadius: '8px' }}>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                                <span>{t('buying.payments.form.summary.total_amount')}</span>
                                <span>{recordCurrency} {moneyOrDash(paymentPreview?.amount)}</span>
                            </div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                                <span>{t('buying.payments.form.summary.total_allocated')}</span>
                                <span>{recordCurrency} {moneyOrDash(totalAllocated)}</span>
                            </div>
                            <div style={{ borderTop: '1px solid var(--border-color)', margin: '12px 0' }}></div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                                <span style={{ fontWeight: 'bold' }}>{t('buying.payments.form.summary.remaining')}</span>
                                <span style={{ fontWeight: 'bold', fontSize: '1.2rem' }} className={paymentPreview?.has_unallocated_amount ? 'text-orange-600' : ''}>
                                    {recordCurrency} {moneyOrDash(unallocatedAmount)}
                                </span>
                            </div>

                            <button
                                type="submit"
                                className="btn bg-purple-600 text-white hover:bg-purple-700 transition-colors"
                                style={{ width: '100%', marginTop: '24px', padding: '12px' }}
                                disabled={loading}
                            >
                                {loading ? t('buying.payments.form.saving') : (formData.voucher_type === 'payment' ? t('buying.payments.form.save_btn') : t('buying.payments.form.save_refund_btn'))}
                            </button>
                            <button
                                type="button"
                                className="btn btn-secondary mt-2"
                                style={{ width: '100%' }}
                                onClick={() => navigate('/buying/payments')}
                            >
                                {t('buying.payments.form.cancel')}
                            </button>

                            {paymentPreview?.has_unallocated_amount && (
                                <div className="mt-4 p-3 bg-orange-50 border border-orange-100 rounded text-[10px] text-orange-800">
                                    {t('buying.payments.form.accounting_note')}
                                </div>
                            )}
                        </div>
                    </div>
                </div>
            </form >
        </div >
    );
}

export default PaymentForm;
