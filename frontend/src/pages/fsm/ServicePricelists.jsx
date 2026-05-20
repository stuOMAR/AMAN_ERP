import React, { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { getCurrency } from '../../utils/auth';
import { useTranslation } from 'react-i18next';

/**
 * ServicePricelists — DataTable + scope-aware editor with valid_from/valid_to.
 */
export default function ServicePricelists() {
  const { t } = useTranslation();
  const [scope, setScope] = useState('');
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    scope: 'global',
    scope_ref_id: '',
    item_id: '',
    currency: getCurrency() || 'SAR',
    price: '',
    valid_from: '',
    valid_to: '',
  });

  const queryClient = useQueryClient();

  const { data: pricelists, isLoading } = useQuery({
    queryKey: ['pricelists', scope],
    queryFn: async () => {
      const params = scope ? `?scope=${scope}` : '';
      const res = await fetch(`/api/fsm/pricelists${params}`);
      if (!res.ok) throw new Error('Failed to load pricelists');
      return res.json();
    },
  });

  const mutation = useMutation({
    mutationFn: async (data) => {
      const res = await fetch('/api/fsm/pricelists', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.detail || 'Failed to save');
      }
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries(['pricelists']);
      setShowForm(false);
      setForm({
        scope: 'global',
        scope_ref_id: '',
        item_id: '',
        currency: getCurrency() || 'SAR',
        price: '',
        valid_from: '',
        valid_to: '',
      });
    },
  });

  const handleSubmit = (e) => {
    e.preventDefault();
    const data = {
      ...form,
      scope_ref_id: form.scope_ref_id ? parseInt(form.scope_ref_id) : null,
      item_id: parseInt(form.item_id),
      price: form.price,
      valid_from: form.valid_from || null,
      valid_to: form.valid_to || null,
    };
    mutation.mutate(data);
  };

  return (
    <div className="service-pricelists">
      <h2>{t('fsm.service_pricelists.title')}</h2>

      <div className="toolbar">
        <select
          className="form-control"
          style={{ width: 200, display: 'inline-block' }}
          value={scope}
          onChange={(e) => setScope(e.target.value)}
        >
          <option value="">{t('fsm.service_pricelists.filters.all_scopes')}</option>
          <option value="global">{t('fsm.service_pricelists.filters.global')}</option>
          <option value="group">{t('fsm.service_pricelists.filters.customer_group')}</option>
          <option value="customer">{t('fsm.service_pricelists.filters.customer')}</option>
        </select>

        <button
          className="btn btn-primary ml-2"
          onClick={() => setShowForm(!showForm)}
        >
          {showForm ? t('fsm.service_pricelists.buttons.cancel') : t('fsm.service_pricelists.buttons.add_entry')}
        </button>
      </div>

      {showForm && (
        <form onSubmit={handleSubmit} className="pricelist-form card p-3 my-3">
          <div className="row">
            <div className="col-md-3">
              <label>{t('fsm.service_pricelists.form.scope')}</label>
              <select
                className="form-control"
                value={form.scope}
                onChange={(e) => setForm({ ...form, scope: e.target.value })}
              >
                <option value="global">{t('fsm.service_pricelists.filters.global')}</option>
                <option value="group">{t('fsm.service_pricelists.filters.customer_group')}</option>
                <option value="customer">{t('fsm.service_pricelists.filters.customer')}</option>
              </select>
            </div>
            {form.scope !== 'global' && (
              <div className="col-md-3">
                <label>{t('fsm.service_pricelists.form.scope_ref_id')}</label>
                <input
                  type="number"
                  className="form-control"
                  value={form.scope_ref_id}
                  onChange={(e) => setForm({ ...form, scope_ref_id: e.target.value })}
                  required
                />
              </div>
            )}
            <div className="col-md-2">
              <label>{t('fsm.service_pricelists.form.item_id')}</label>
              <input
                type="number"
                className="form-control"
                value={form.item_id}
                onChange={(e) => setForm({ ...form, item_id: e.target.value })}
                required
              />
            </div>
            <div className="col-md-2">
              <label>{t('fsm.service_pricelists.form.currency')}</label>
              <input
                type="text"
                className="form-control"
                value={form.currency}
                onChange={(e) => setForm({ ...form, currency: e.target.value })}
                required
              />
            </div>
            <div className="col-md-2">
              <label>{t('fsm.service_pricelists.form.price')}</label>
              <input
                type="number"
                step="0.01"
                className="form-control"
                value={form.price}
                onChange={(e) => setForm({ ...form, price: e.target.value })}
                required
              />
            </div>
          </div>
          <div className="row mt-2">
            <div className="col-md-3">
              <label>{t('fsm.service_pricelists.form.valid_from')}</label>
              <input
                type="date"
                className="form-control"
                value={form.valid_from}
                onChange={(e) => setForm({ ...form, valid_from: e.target.value })}
              />
            </div>
            <div className="col-md-3">
              <label>{t('fsm.service_pricelists.form.valid_to')}</label>
              <input
                type="date"
                className="form-control"
                value={form.valid_to}
                onChange={(e) => setForm({ ...form, valid_to: e.target.value })}
              />
            </div>
            <div className="col-md-3 d-flex align-items-end">
              <button
                type="submit"
                className="btn btn-success"
                disabled={mutation.isLoading}
              >
                {mutation.isLoading ? t('fsm.service_pricelists.buttons.saving') : t('fsm.service_pricelists.buttons.save')}
              </button>
            </div>
          </div>
          {mutation.isError && (
            <div className="alert alert-danger mt-2">{mutation.error.message}</div>
          )}
        </form>
      )}

      {isLoading ? (
        <p>{t('fsm.service_pricelists.loading')}</p>
      ) : (
        <table className="table table-sm">
          <thead>
            <tr>
              <th>{t('fsm.service_pricelists.table.scope')}</th>
              <th>{t('fsm.service_pricelists.table.ref_id')}</th>
              <th>{t('fsm.service_pricelists.table.item_id')}</th>
              <th>{t('fsm.service_pricelists.table.currency')}</th>
              <th>{t('fsm.service_pricelists.table.price')}</th>
              <th>{t('fsm.service_pricelists.table.valid_from')}</th>
              <th>{t('fsm.service_pricelists.table.valid_to')}</th>
            </tr>
          </thead>
          <tbody>
            {pricelists?.map((p) => (
              <tr key={p.id}>
                <td>{p.scope}</td>
                <td>{p.scope_ref_id || '-'}</td>
                <td>{p.item_id}</td>
                <td>{p.currency}</td>
                <td>{p.price}</td>
                <td>{p.valid_from || '-'}</td>
                <td>{p.valid_to || '-'}</td>
              </tr>
            ))}
            {pricelists?.length === 0 && (
              <tr>
                <td colSpan={7} className="text-center text-muted">
                  {t('fsm.service_pricelists.no_entries')}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      )}
    </div>
  );
}
