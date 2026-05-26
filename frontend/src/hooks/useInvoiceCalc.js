/**
 * useInvoiceCalc — Hook for backend-powered calculations.
 * 
 * Architecture: backend-authoritative calculation.
 * preview() sends raw data to the backend endpoint.
 * Backend computes with Decimal, resolves tax engine, and returns final values.
 * On submit, client sends submitted_grand_total for server-side verification.
 * 
 * Usage:
 *   const { totals, lines, preview, loading } = useInvoiceCalc();
 *   preview({
 *     branch_id: 1,
 *     customer_id: 25,
 *     lines: [{ product_id: 7, quantity: '10', unit_price: '1200', discount: '500' }],
 *     currency: 'SAR',
 *     paid_amount: '5000',
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

  const linesRef = useRef([]);
  linesRef.current = lines;

  /**
   * Calculate invoice totals via backend.
   * @param {Object} data - { lines: [...], header_discount_pct, markup_amount, paid_amount, currency }
   */
  const preview = useCallback(async (data, endpoint = '/calculate/invoice-totals') => {
    setLoading(true);
    setError(null);

    try {
      const res = await api.post(endpoint, data);
      const result = res.data;

      setTotals({
        subtotal: result.subtotal ?? null,
        totalDiscount: result.total_discount ?? null,
        totalTax: result.total_tax ?? null,
        grandTotal: result.grand_total ?? null,
        paidAmount: result.paid_amount ?? null,
        remainingBalance: result.remaining_balance ?? null,
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
   * Debounced preview — waits 500ms after last call.
   * Debounces the backend preview request.
   */
  const previewDebounced = useCallback((data, endpoint = '/calculate/invoice-totals') => {
    if (debounceRef.current) clearTimeout(debounceRef.current);
    debounceRef.current = setTimeout(() => {
      preview(data, endpoint);
    }, 600); // 600ms debounce for high-volume keystrokes
  }, [preview]);

  /**
   * Calculate contract totals via the contracts backend preview endpoint.
   * @param {Object} data - { items: [...], currency, party_id, branch_id }
   */
  const previewContract = useCallback(async (data) => {
    setLoading(true);
    setError(null);

    try {
      const res = await api.post('/contracts/preview', data);
      const result = res.data;

      setTotals({
        subtotal: result.subtotal ?? null,
        totalTax: result.tax_amount ?? result.total_tax ?? null,
        grandTotal: result.grand_total ?? null,
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

  const quickCalc = useCallback(() => ({
    subtotal: null,
    totalTax: null,
    grandTotal: null,
  }), []);

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
