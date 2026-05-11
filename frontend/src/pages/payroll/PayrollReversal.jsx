import React, { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

/**
 * PayrollReversal — confirm-and-reason modal for reversing a locked payroll period.
 *
 * Props:
 *   periodId   — the payroll period ID to reverse
 *   periodName — display name for the confirmation dialog
 *   onSuccess  — callback after successful reversal
 */
export default function PayrollReversal({ periodId, periodName, onSuccess }) {
  const { t } = useTranslation();
  const [reason, setReason] = useState('');
  const [showModal, setShowModal] = useState(false);
  const [result, setResult] = useState(null);
  const queryClient = useQueryClient();

  const mutation = useMutation({
    mutationFn: async () => {
      const res = await fetch(`/api/payroll/periods/${periodId}/reverse`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ reason }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Reversal failed');
      }
      return res.json();
    },
    onSuccess: (data) => {
      setResult(data);
      queryClient.invalidateQueries(['payroll-periods']);
      if (onSuccess) onSuccess(data);
    },
  });

  if (!showModal) {
    return (
      <button
        className="btn btn-danger btn-sm"
        onClick={() => setShowModal(true)}
      >
        {t('payroll.payroll_reversal.reverse_period')}
      </button>
    );
  }

  return (
    <div className="modal-overlay">
      <div className="modal-content" style={{ maxWidth: 500 }}>
        <h3>{t('payroll.payroll_reversal.modal_title')}</h3>
        <p>
          {t('payroll.payroll_reversal.confirm_text')} <strong>{periodName}</strong>?
          This will reverse the GL journal entries and create compensating bank movements.
        </p>

        <div className="form-group">
          <label htmlFor="reversal-reason">{t('payroll.payroll_reversal.reason_label')}</label>
          <textarea
            id="reversal-reason"
            className="form-control"
            rows={3}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder={t('payroll.payroll_reversal.reason_placeholder')}
            required
          />
        </div>

        {mutation.isError && (
          <div className="alert alert-danger">
            {mutation.error.message}
          </div>
        )}

        {result && (
          <div className="alert alert-success">
            <p>{t('payroll.payroll_reversal.success_message')}</p>
            {result.je_id && <p>{t('payroll.payroll_reversal.reversed_je')}{result.je_id}</p>}
            {result.run_id && <p>{t('payroll.payroll_reversal.run_id')}{result.run_id}</p>}
          </div>
        )}

        <div className="modal-actions">
          <button
            className="btn btn-secondary"
            onClick={() => {
              setShowModal(false);
              setResult(null);
              setReason('');
            }}
          >
            {t('payroll.payroll_reversal.buttons.cancel')}
          </button>
          <button
            className="btn btn-danger"
            onClick={() => mutation.mutate()}
            disabled={!reason.trim() || mutation.isLoading || result}
          >
            {mutation.isLoading ? t('payroll.payroll_reversal.buttons.reversing') : t('payroll.payroll_reversal.buttons.confirm')}
          </button>
        </div>
      </div>
    </div>
  );
}
