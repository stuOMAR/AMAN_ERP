/**
 * T14 P1 #107 — Reusable a11y primitives for forms and tables.
 *
 * Why this exists
 *   Audit found dozens of <input> elements without associated <label>s and
 *   tables without proper <th scope>/<caption> markup, failing WCAG 2.1
 *   AA. Patching every page individually is high-cost and high-regret;
 *   the cheaper path is to ship two reusable primitives that *bake the
 *   correct semantics in*, then migrate hotspots to use them.
 *
 * Components
 *   <AccessibleField>  — wraps any input/select/textarea with a proper
 *                        <label htmlFor>, optional helper text wired via
 *                        aria-describedby, and an aria-invalid + role=alert
 *                        error region. Auto-generates an id if missing.
 *
 *   <AccessibleTable>  — wraps a plain <table> with <caption>, <thead>
 *                        with scope="col" headers, and an aria-busy hint
 *                        for loading states. Renders rows via a render
 *                        prop so callers stay in control of cell shape.
 *
 * Usage (form):
 *   <AccessibleField label="اسم المستخدم" required error={errors.username}>
 *     <input value={username} onChange={...} />
 *   </AccessibleField>
 *
 * Usage (table):
 *   <AccessibleTable
 *     caption="قائمة الفواتير"
 *     columns={[{key:'number', label:'الرقم'}, {key:'total', label:'الإجمالي'}]}
 *     rows={invoices}
 *     loading={isLoading}
 *     renderCell={(row, col) => row[col.key]}
 *   />
 */
import React, { useId } from 'react';

export function AccessibleField({
  label,
  required = false,
  error,
  helperText,
  children,
  id: providedId,
  className = '',
}) {
  const autoId = useId();
  const id = providedId || `field-${autoId}`;
  const helperId = helperText ? `${id}-help` : undefined;
  const errorId = error ? `${id}-err` : undefined;
  const describedBy = [helperId, errorId].filter(Boolean).join(' ') || undefined;

  // We clone the child so callers don't have to repeat id/aria props.
  const child = React.Children.only(children);
  const enhanced = React.cloneElement(child, {
    id,
    'aria-required': required || undefined,
    'aria-invalid': error ? 'true' : undefined,
    'aria-describedby': describedBy,
  });

  return (
    <div className={`a11y-field ${className}`}>
      <label htmlFor={id} className="a11y-field__label">
        {label}
        {required && <span aria-hidden="true" style={{ color: '#c00', marginInlineStart: 4 }}>*</span>}
      </label>
      {enhanced}
      {helperText && (
        <div id={helperId} className="a11y-field__help" style={{ fontSize: 12, color: '#666' }}>
          {helperText}
        </div>
      )}
      {error && (
        <div id={errorId} role="alert" className="a11y-field__error" style={{ fontSize: 12, color: '#c00' }}>
          {error}
        </div>
      )}
    </div>
  );
}

export function AccessibleTable({
  caption,
  columns,
  rows,
  loading = false,
  empty = 'لا توجد بيانات',
  renderCell,
  rowKey = (row, idx) => row.id ?? idx,
  className = '',
}) {
  return (
    <div className={`a11y-table-wrap ${className}`} aria-busy={loading || undefined}>
      <table className="a11y-table" role="table">
        {caption && <caption className="a11y-table__caption">{caption}</caption>}
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} scope="col" aria-sort={c.sort || undefined}>
                {c.label}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {loading && (
            <tr>
              <td colSpan={columns.length} role="status">جاري التحميل…</td>
            </tr>
          )}
          {!loading && rows.length === 0 && (
            <tr>
              <td colSpan={columns.length}>{empty}</td>
            </tr>
          )}
          {!loading && rows.map((row, idx) => (
            <tr key={rowKey(row, idx)}>
              {columns.map((c) => (
                <td key={c.key}>{renderCell ? renderCell(row, c) : row[c.key]}</td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default { AccessibleField, AccessibleTable };
