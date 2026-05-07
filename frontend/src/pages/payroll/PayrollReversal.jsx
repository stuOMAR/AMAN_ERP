import React, { useState } from 'react';
import { useMutation, useQueryClient } from '@tanstack/react-query';

/**
 * PayrollReversal — confirm-and-reason modal for reversing a locked payroll period.
 *
 * Props:
 *   periodId   — the payroll period ID to reverse
 *   periodName — display name for the confirmation dialog
 *   onSuccess  — callback after successful reversal
 */
export default function PayrollReversal({ periodId, periodName, onSuccess }) {
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
        Reverse Period
      </button>
    );
  }

  return (
    <div className="modal-overlay">
      <div className="modal-content" style={{ maxWidth: 500 }}>
        <h3>Reverse Payroll Period</h3>
        <p>
          Are you sure you want to reverse <strong>{periodName}</strong>?
          This will reverse the GL journal entries and create compensating bank movements.
        </p>

        <div className="form-group">
          <label htmlFor="reversal-reason">Reason for reversal *</label>
          <textarea
            id="reversal-reason"
            className="form-control"
            rows={3}
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="Enter the reason for reversing this payroll period..."
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
            <p>Period reversed successfully.</p>
            {result.je_id && <p>Reversed JE: #{result.je_id}</p>}
            {result.run_id && <p>Run ID: {result.run_id}</p>}
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
            Cancel
          </button>
          <button
            className="btn btn-danger"
            onClick={() => mutation.mutate()}
            disabled={!reason.trim() || mutation.isLoading || result}
          >
            {mutation.isLoading ? 'Reversing...' : 'Confirm Reversal'}
          </button>
        </div>
      </div>
    </div>
  );
}
