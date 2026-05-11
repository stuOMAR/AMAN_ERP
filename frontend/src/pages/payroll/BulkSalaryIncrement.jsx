import React, { useState, useCallback } from 'react';
import { useMutation } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

/**
 * BulkSalaryIncrement — CSV upload + dry-run preview + per-row outcome table.
 *
 * Flow:
 *   1. Upload CSV with columns: employee_id, new_salary
 *   2. Preview (dry-run) shows per-row outcomes
 *   3. Confirm applies the increments
 */
export default function BulkSalaryIncrement() {
  const { t } = useTranslation();
  const [csvData, setCsvData] = useState(null);
  const [rows, setRows] = useState([]);
  const [effectiveDate, setEffectiveDate] = useState('');
  const [reason, setReason] = useState('');
  const [result, setResult] = useState(null);

  const parseCsv = useCallback((text) => {
    const lines = text.trim().split('\n');
    if (lines.length < 2) return [];
    const parsed = [];
    for (let i = 1; i < lines.length; i++) {
      const cols = lines[i].split(',').map((c) => c.trim());
      if (cols.length >= 2) {
        parsed.push({
          employee_id: parseInt(cols[0], 10),
          new_salary: parseFloat(cols[1]),
        });
      }
    }
    return parsed;
  }, []);

  const handleFileUpload = (e) => {
    const file = e.target.files[0];
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (evt) => {
      const text = evt.target.result;
      setCsvData(text);
      setRows(parseCsv(text));
    };
    reader.readAsText(file);
  };

  const mutation = useMutation({
    mutationFn: async (dryRun) => {
      const res = await fetch('/api/hr/employees/bulk-salary-increment', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          rows,
          effective_date: effectiveDate,
          reason,
          dry_run: dryRun,
        }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Operation failed');
      }
      return res.json();
    },
    onSuccess: (data) => {
      setResult(data);
    },
  });

  return (
    <div className="bulk-salary-increment">
        <h2>{t('payroll.bulk_salary_increment.title')}</h2>

      <div className="form-group">
        <label>{t('payroll.bulk_salary_increment.csv_label')}</label>
        <input type="file" accept=".csv" onChange={handleFileUpload} />
      </div>

      <div className="form-group">
        <label>{t('payroll.bulk_salary_increment.effective_date')}</label>
        <input
          type="date"
          className="form-control"
          value={effectiveDate}
          onChange={(e) => setEffectiveDate(e.target.value)}
        />
      </div>

      <div className="form-group">
        <label>{t('payroll.bulk_salary_increment.reason')}</label>
        <input
          type="text"
          className="form-control"
          value={reason}
          onChange={(e) => setReason(e.target.value)}
          placeholder={t('payroll.bulk_salary_increment.reason_placeholder')}
        />
      </div>

      {rows.length > 0 && (
        <div className="preview-section">
          <h3>{t('payroll.bulk_salary_increment.preview_title', { count: rows.length })}</h3>
          <table className="table table-sm">
            <thead>
              <tr>
                <th>{t('payroll.bulk_salary_increment.table.employee_id')}</th>
                <th>{t('payroll.bulk_salary_increment.table.new_salary')}</th>
              </tr>
            </thead>
            <tbody>
              {rows.slice(0, 10).map((r, i) => (
                <tr key={i}>
                  <td>{r.employee_id}</td>
                  <td>{r.new_salary.toLocaleString()}</td>
                </tr>
              ))}
              {rows.length > 10 && (
                <tr>
                  <td colSpan={2} className="text-muted">
                    ... and {rows.length - 10} more
                  </td>
                </tr>
              )}
            </tbody>
          </table>

          <div className="action-buttons">
            <button
              className="btn btn-secondary"
              onClick={() => mutation.mutate(true)}
              disabled={mutation.isLoading || !effectiveDate || !reason}
            >
              {mutation.isLoading ? t('payroll.bulk_salary_increment.buttons.previewing') : t('payroll.bulk_salary_increment.buttons.dry_run')}
            </button>
            <button
              className="btn btn-primary"
              onClick={() => mutation.mutate(false)}
              disabled={mutation.isLoading || !effectiveDate || !reason}
            >
              {mutation.isLoading ? t('payroll.bulk_salary_increment.buttons.applying') : t('payroll.bulk_salary_increment.buttons.apply')}
            </button>
          </div>
        </div>
      )}

      {mutation.isError && (
        <div className="alert alert-danger">{mutation.error.message}</div>
      )}

      {result && (
        <div className="result-section">
          <h3>
            {t('payroll.bulk_salary_increment.results.title')} {result.dry_run ? t('payroll.bulk_salary_increment.results.dry_run_suffix') : ''}
          </h3>
          <div className="summary">
            <span className="badge badge-success">
              {t('payroll.bulk_salary_increment.results.success')} {result.success_count}
            </span>
            <span className="badge badge-danger">
              {t('payroll.bulk_salary_increment.results.errors')} {result.error_count}
            </span>
            <span>{t('payroll.bulk_salary_increment.results.total_increment')} {result.total_increment}</span>
          </div>

          <table className="table table-sm">
            <thead>
              <tr>
                <th>{t('payroll.bulk_salary_increment.table.employee_id')}</th>
                <th>{t('payroll.bulk_salary_increment.table.old_salary')}</th>
                <th>{t('payroll.bulk_salary_increment.table.new_salary')}</th>
                <th>{t('payroll.bulk_salary_increment.table.increment')}</th>
                <th>{t('payroll.bulk_salary_increment.table.status')}</th>
                <th>{t('payroll.bulk_salary_increment.table.error')}</th>
              </tr>
            </thead>
            <tbody>
              {result.outcomes.map((o, i) => (
                <tr key={i} className={o.status === 'error' ? 'table-danger' : ''}>
                  <td>{o.employee_id}</td>
                  <td>{o.old_salary || '-'}</td>
                  <td>{o.new_salary}</td>
                  <td>{o.increment || '-'}</td>
                  <td>{o.status}</td>
                  <td>{o.error || '-'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
