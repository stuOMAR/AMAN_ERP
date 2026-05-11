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


function PaymentForm() {
    const { t } = useTranslation();
    const navigate = useNavigate();
    const location = useLocation();
    const baseCurrency = getCurrency();
    const { currentBranch } = useBranch();
    const { showToast } = useToast();
    const [recordCurrency, setRecordCurrency] = useState(baseCurrency);
    const [exchangeRate, setExchangeRate] = useState(1.0);
    const [transactionRate, setTransactionRate] = useState(1.0); // Rate between Record and Treasury
    const [loading, setLoading] = useState(false);
    const [initialLoad, setInitialLoad] = useState(true);
    const [suppliers, setSuppliers] = useState([]);
    const [currenciesList, setCurrenciesList] = useState([]);
    const [outstandingInvoices, setOutstandingInvoices] = useState([]);
    const [treasuryAccounts, setTreasuryAccounts] = useState([]);
    const [formData, setFormData] = useState({
        supplier_id: '',
        party_site_id: '',
        voucher_date: new Date().toISOString().split('T')[0],
        amount: 0,
        voucher_type: 'payment', // 'payment' or 'refund'
        payment_method: '',
        bank_account_id: null,
        check_number: '',
        check_date: '',
        reference: '',
        notes: '',
        allocations: []
    });

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
                setFormData(prev => ({
                    ...prev,
                    supplier_id: inv.supplier_id,
                    amount: inv.remaining_balance || (inv.total - (inv.paid_amount || 0)),
                    notes: t('buying.payments.form.prefilled_note', { number: inv.invoice_number }) || `سداد فاتورة مشتريات رقم ${inv.invoice_number}`
                }));

                // Fetch outstanding invoices for this supplier to show the grid
                const outstandingRes = await purchasesAPI.getOutstandingInvoices(inv.supplier_id, { branch_id: currentBranch?.id });
                setOutstandingInvoices(outstandingRes.data);

                // Automatically allocate to this specific invoice
                setFormData(prev => ({
                    ...prev,
                    allocations: [{ invoice_id: inv.id, allocated_amount: inv.remaining_balance || (inv.total - (inv.paid_amount || 0)) }]
                }));
            }
        } catch (error) {
            showToast(t('common.error'), 'error');
        } finally {
            setInitialLoad(false);
        }
    };

    const autoAllocate = (amount, invoices) => {
        let remaining = Number(amount) || 0;
        const newAllocations = [];

        // Filter invoices by type
        const filteredInvoices = invoices.filter(inv => (
            formData.voucher_type === 'payment'
                ? ['purchase', 'purchase_debit_note'].includes(inv.invoice_type)
                : ['purchase_return', 'purchase_credit_note'].includes(inv.invoice_type)
        ));

        // Sort invoices by date (FIFO)
        const sortedInvoices = [...filteredInvoices].sort((a, b) =>
            new Date(a.invoice_date) - new Date(b.invoice_date)
        );

        for (const inv of sortedInvoices) {
            if (remaining <= 0) break;

            const invRate = Number(inv.exchange_rate) || 1.0;
            const vRate = Number(exchangeRate) || 1.0;

            // Calculate remaining balance in VOUCHER currency
            // balance_v = balance_i * (invRate / vRate)
            const remainingInVoucher = Number(inv.remaining_balance) * (invRate / vRate);

            const toAllocate = Math.min(remaining, remainingInVoucher);

            if (toAllocate > 0.001) {
                newAllocations.push({
                    invoice_id: inv.id,
                    allocated_amount: toAllocate
                });
                remaining -= toAllocate;
            }
        }

        return newAllocations;
    };

    const handleSupplierChange = async (e) => {
        const supplierId = e.target.value;
        setFormData({ ...formData, supplier_id: supplierId, allocations: [] });

        if (supplierId) {
            try {
                const res = await purchasesAPI.getOutstandingInvoices(supplierId, { branch_id: currentBranch?.id });
                setOutstandingInvoices(res.data);

                // Set currency from supplier data
                const selectedSupp = suppliers.find(s => s.id == supplierId);
                if (selectedSupp && selectedSupp.currency) {
                    setRecordCurrency(selectedSupp.currency);
                } else {
                    setRecordCurrency(baseCurrency);
                }

                // Auto-allocate if amount is already set
                if (formData.amount > 0) {
                    const allocations = autoAllocate(formData.amount, res.data);
                    setFormData(prev => ({ ...prev, allocations }));
                }
            } catch (error) {
                showToast(t('common.error'), 'error');
            }
        } else {
            setOutstandingInvoices([]);
        }
    };

    const handleTreasuryChange = (e) => {
        const treasuryId = e.target.value;
        setFormData(prev => ({ ...prev, bank_account_id: treasuryId }));

        if (treasuryId) {
            const selectedTreasury = treasuryAccounts.find(acc => acc.id == treasuryId);
            if (selectedTreasury) {
                const tRate = Number(selectedTreasury.exchange_rate) || 1.0;
                const vRate = Number(exchangeRate) || 1.0;
                setTransactionRate(vRate / tRate);
            }
        } else {
            setTransactionRate(1.0);
        }
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
        if (shouldClear) setFormData(prev => ({ ...prev, allocations: [] }));

        // Fetch exchange rate for the new currency
        try {
            const currencyData = currenciesList.find(c => c.code === newCurrency);
            const newVRate = currencyData ? (currencyData.current_rate || 1.0) : 1.0;
            setExchangeRate(newVRate);

            // Update transaction rate if treasury is selected
            if (formData.bank_account_id) {
                const treasury = treasuryAccounts.find(acc => acc.id == formData.bank_account_id);
                if (treasury) {
                    const tRate = Number(treasury.exchange_rate) || 1.0;
                    setTransactionRate(newVRate / tRate);
                }
            }
        } catch (error) {
            showToast(t('common.error'), 'error');
            setExchangeRate(1.0);
        }
    };

    const handleAllocationChange = (invoiceId, amount) => {
        const val = Number(amount) || 0;

        const existing = formData.allocations.find(a => a.invoice_id === invoiceId);
        if (existing) {
            setFormData({
                ...formData,
                allocations: formData.allocations.map(a =>
                    a.invoice_id === invoiceId ? { ...a, allocated_amount: val } : a
                )
            });
        } else {
            setFormData({
                ...formData,
                allocations: [...formData.allocations, { invoice_id: invoiceId, allocated_amount: val }]
            });
        }
    };

    const handleAmountChange = (e) => {
        const newAmount = Number(e.target.value) || 0;
        setFormData({ ...formData, amount: newAmount });

        // Auto-allocate when amount changes and we have invoices
        if (outstandingInvoices.length > 0) {
            const allocations = autoAllocate(newAmount, outstandingInvoices);
            setFormData(prev => ({ ...prev, amount: newAmount, allocations }));
        }
    };

    const handleAutoAllocate = () => {
        if (formData.amount > 0 && outstandingInvoices.length > 0) {
            const allocations = autoAllocate(formData.amount, outstandingInvoices);
            setFormData({ ...formData, allocations });
        }
    };

    // Pay all outstanding invoices in full (filtered by currency)
    const handlePayAll = () => {
        if (outstandingInvoices.length > 0) {
            const filteredInvoices = outstandingInvoices.filter(inv =>
                (inv.invoice_type === (formData.voucher_type === 'payment' ? 'purchase' : 'purchase_return'))
            );

            if (filteredInvoices.length === 0) {
                showToast(t('buying.payments.form.validation.no_invoices_matching_currency') || `لا توجد فواتير مطابقة لعملة السند (${recordCurrency})`, 'error');
                return;
            }

            const allocations = filteredInvoices.map(inv => ({
                invoice_id: inv.id,
                allocated_amount: Number(inv.remaining_balance)
            }));
            const total = allocations.reduce((sum, a) => sum + a.allocated_amount, 0);
            setFormData({ ...formData, allocations, amount: total });
        }
    };

    // Quick fill a single invoice with its full remaining balance
    const handleQuickFill = (invoiceId, remainingBalance) => {
        const invoice = outstandingInvoices.find(inv => inv.id === invoiceId);
        const invRate = Number(invoice?.exchange_rate) || 1.0;
        const vRate = Number(exchangeRate) || 1.0;

        // Convert invoice remaining balance to voucher currency
        const amountInVoucher = remainingBalance * (invRate / vRate);

        const existing = formData.allocations.find(a => a.invoice_id === invoiceId);
        const newAllocations = existing
            ? formData.allocations.map(a => a.invoice_id === invoiceId ? { ...a, allocated_amount: amountInVoucher } : a)
            : [...formData.allocations, { invoice_id: invoiceId, allocated_amount: amountInVoucher }];
        setFormData({ ...formData, allocations: newAllocations });
    };

    const totalAllocated = formData.allocations.reduce((sum, alloc) => sum + alloc.allocated_amount, 0);

    const handleSubmit = async (e) => {
        e.preventDefault();

        if (!formData.supplier_id) {
            showToast(t('buying.payments.form.validation.select_supplier'), 'error');
            return;
        }

        if (formData.amount <= 0) {
            showToast(t('buying.payments.form.validation.invalid_amount'), 'error');
            return;
        }

        if (totalAllocated > formData.amount) {
            showToast(t('buying.payments.form.validation.allocation_exceeded'), 'error');
            return;
        }

        if (!formData.payment_method) {
            showToast(t('buying.payments.form.validation.payment_method_required'), 'error');
            return;
        }

        setLoading(true);
        try {
            // Use the actual total allocated as the payment amount
            const actualAmount = totalAllocated > 0 ? totalAllocated : formData.amount;

            const sanitizedData = {
                ...formData,
                amount: actualAmount,  // Use calculated total instead of input
                supplier_id: parseInt(formData.supplier_id),
                branch_id: currentBranch?.id,
                bank_account_id: formData.bank_account_id ? parseInt(formData.bank_account_id) : null,
                check_date: formData.check_date || null,
                check_number: formData.check_number || null,
                reference: formData.reference || null,
                notes: formData.notes || null,
                allocations: formData.allocations.filter(a => a.allocated_amount > 0).map(a => ({
                    invoice_id: parseInt(a.invoice_id),
                    allocated_amount: String(a.allocated_amount)
                })),
                currency: recordCurrency,
                exchange_rate: String(exchangeRate || 1.0),
                treasury_account_id: formData.bank_account_id ? parseInt(formData.bank_account_id) : null,
                transaction_rate: String(transactionRate || 1.0)
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
                                        onChange={(dateStr) => setFormData({ ...formData, voucher_date: dateStr })}
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
                                    onChange={() => setFormData(prev => ({ ...prev, voucher_type: 'payment', allocations: [] }))}
                                />
                                <span style={{ fontWeight: formData.voucher_type === 'payment' ? 'bold' : 'normal', color: '#dc2626' }}>{t('buying.payments.form.type_payment')}</span>
                            </label>
                            <label style={{ display: 'flex', alignItems: 'center', gap: '8px', cursor: 'pointer' }}>
                                <input
                                    type="radio"
                                    name="voucher_type"
                                    value="refund"
                                    checked={formData.voucher_type === 'refund'}
                                    onChange={() => setFormData(prev => ({ ...prev, voucher_type: 'refund', allocations: [] }))}
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
                                    {t('buying.payments.form.allocated_total')} <span className="font-bold text-purple-700">{totalAllocated.toLocaleString()} {recordCurrency}</span>
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
                                        {formData.amount > 0 && (
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
                                                <td>{Number(inv.total).toLocaleString()}</td>
                                                <td className="font-bold text-red-600">{Number(inv.remaining_balance).toLocaleString()}</td>
                                                <td>
                                                    <div style={{ display: 'flex', gap: '4px', alignItems: 'center' }}>
                                                        <input
                                                            type="number"
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
                                                            onClick={() => handleQuickFill(inv.id, Number(inv.remaining_balance))}
                                                            className="btn btn-sm bg-green-100 text-green-700 hover:bg-green-200 border border-green-300"
                                                            title={t('buying.payments.table.quick_fill')}
                                                            style={{ padding: '4px 8px', fontSize: '12px' }}
                                                        >
                                                            {t('buying.payments.table.all')}
                                                        </button>
                                                    </div>
                                                    {recordCurrency !== (inv.currency || baseCurrency) && formData.allocations.find(a => a.invoice_id === inv.id)?.allocated_amount > 0 && (
                                                        <div className="text-[10px] text-gray-500 mt-1">
                                                            {t('common.equivalent')}: {((formData.allocations.find(a => a.invoice_id === inv.id)?.allocated_amount || 0) * (exchangeRate / (inv.exchange_rate || 1))).toFixed(2)} {inv.currency || baseCurrency}
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
                                            type="number"
                                            required
                                            step="0.01"
                                            min="0.01"
                                            value={formData.amount}
                                            onChange={(e) => setFormData({ ...formData, amount: Number(e.target.value) || 0 })}
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
                                                            type="number"
                                                            step="0.000001"
                                                            value={transactionRate}
                                                            onChange={(e) => {
                                                                const newTRate = e.target.value;
                                                                setTransactionRate(newTRate);

                                                                // If treasury is base currency, update the main exchange rate too
                                                                const selectedTreasury = treasuryAccounts.find(acc => acc.id == formData.bank_account_id);
                                                                if (selectedTreasury && selectedTreasury.currency === baseCurrency) {
                                                                    setExchangeRate(newTRate);
                                                                }
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
                                                                type="number"
                                                                step="0.000001"
                                                                value={exchangeRate}
                                                                onChange={(e) => setExchangeRate(e.target.value)}
                                                                className="form-input form-input-sm w-full font-mono text-center border-gray-300 pr-12"
                                                                style={{ paddingRight: '3rem' }}
                                                            />
                                                            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-xs text-gray-400 font-medium pointer-events-none select-none bg-gray-50 px-1 rounded">{baseCurrency}</span>
                                                        </div>
                                                    </>
                                                )}

                                            {/* ROW 4: Equivalent Display - Conditional */}
                                            {formData.bank_account_id && treasuryAccounts.find(acc => acc.id == formData.bank_account_id)?.currency !== recordCurrency && (
                                                <>
                                                    <label className="text-xs text-purple-800">
                                                        {t('common.equivalent')}:
                                                    </label>
                                                    <div className="font-bold font-mono text-sm text-purple-800 bg-purple-50 p-2 rounded border border-purple-100 text-center">
                                                        {(formData.amount * transactionRate).toLocaleString()} {treasuryAccounts.find(acc => acc.id == formData.bank_account_id)?.currency}
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
                                <span>{recordCurrency} {formData.amount.toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
                            </div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                                <span>{t('buying.payments.form.summary.total_allocated')}</span>
                                <span>{recordCurrency} {totalAllocated.toLocaleString(undefined, { minimumFractionDigits: 2 })}</span>
                            </div>
                            <div style={{ borderTop: '1px solid var(--border-color)', margin: '12px 0' }}></div>
                            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '8px' }}>
                                <span style={{ fontWeight: 'bold' }}>{t('buying.payments.form.summary.remaining')}</span>
                                <span style={{ fontWeight: 'bold', fontSize: '1.2rem' }} className={formData.amount - totalAllocated > 0.01 ? 'text-orange-600' : ''}>
                                    {recordCurrency} {(formData.amount - totalAllocated).toLocaleString(undefined, { minimumFractionDigits: 2 })}
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

                            {formData.amount - totalAllocated > 0.01 && (
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
