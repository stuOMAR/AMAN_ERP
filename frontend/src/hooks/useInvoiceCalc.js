/**
 * useInvoiceCalc — Hook for backend-powered calculations.
 * 
 * All calculations happen in the backend. Frontend only sends raw data.
 * Tax is resolved by the backend engine — do NOT send tax_rate from frontend.
 * 
 * Usage:
 *   const { totals, lines, preview, loading } = useInvoiceCalc();
 *   preview({
 *     branch_id: 1,
 *     customer_id: 25,
 *     lines: [{ product_id: 7, quantity: 10, unit_price: 1200, discount: 500 }],
 *     currency: 'SAR',
 *     paid_amount: 5000,
 *   });
 */

import { useState, useCallback, useRef } from 'react';
import api from '../services/apiClient';

export default function useInvoiceCalc() {
  const [totals, setTotals] = useState(null);
  const [lines, setLines] = useState([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const debounceRef = useRef(null);

  /**
   * Calculate invoice totals via backend.
   * @param {Object} data - { lines: [...], header_discount_pct, markup_amount, paid_amount, currency }
   */
  const preview = useCallback(async (data) => {
    setLoading(true);
    setError(null);

    try {
      const res = await api.post('/calculate/invoice-totals', data);
      const result = res.data;

      setTotals({
        subtotal: result.subtotal || 0,
        totalDiscount: result.total_discount || 0,
        totalTax: result.total_tax || 0,
        grandTotal: result.grand_total || 0,
        paidAmount: result.paid_amount || 0,
        remainingBalance: result.remaining_balance || 0,
        currency: result.currency || 'SAR',
      });

      setLines(result.lines || []);
      return result;
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  /**
   * Debounced preview — waits 300ms after last call.
   * Use this for live calculations while user types.
   */
  const previewDebounced = useCallback((data) => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => preview(data), 300);
  }, [preview]);

  /**
   * Calculate contract totals via backend.
   * @param {Object} data - { lines: [...], currency }
   */
  const previewContract = useCallback(async (data) => {
    setLoading(true);
    setError(null);

    try {
      const res = await api.post('/calculate/contract-totals', data);
      const result = res.data;

      setTotals({
        subtotal: result.subtotal || 0,
        totalTax: result.total_tax || 0,
        grandTotal: result.grand_total || 0,
        currency: result.currency || 'SAR',
      });

      setLines(result.lines || []);
      return result;
    } catch (err) {
      setError(err.response?.data?.detail || err.message);
      return null;
    } finally {
      setLoading(false);
    }
  }, []);

  /**
   * Quick local calculation for immediate display (approximate).
   * Use this for instant feedback, then call preview() for accurate totals.
   */
  const quickCalc = useCallback((linesData) => {
    let subtotal = 0;
    let totalTax = 0;

    for (const ln of linesData) {
      const qty = Number(ln.quantity) || 0;
      const price = Number(ln.unit_price) || 0;
      const taxRate = Number(ln.tax_rate) || 0;
      const disc = Number(ln.discount) || 0;

      const lineSubtotal = qty * price;
      const taxable = lineSubtotal - disc;
      const lineTax = taxable * taxRate / 100;

      subtotal += lineSubtotal;
      totalTax += lineTax;
    }

    return { subtotal, totalTax, grandTotal: subtotal + totalTax };
  }, []);

  const reset = useCallback(() => {
    setTotals(null);
    setLines([]);
    setError(null);
  }, []);

  return {
    totals,
    lines,
    loading,
    error,
    preview,
    previewDebounced,
    previewContract,
    quickCalc,
    reset,
  };
}
