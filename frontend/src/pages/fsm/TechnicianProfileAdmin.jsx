import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { useTranslation } from 'react-i18next';

/**
 * TechnicianProfileAdmin — CRUD + match preview for technician profiles.
 */
export default function TechnicianProfileAdmin() {
  const { t } = useTranslation();
  const [showForm, setShowForm] = useState(false);
  const [form, setForm] = useState({
    employee_id: '',
    skills: '',
    zones: '',
    certifications: '',
  });
  const [matchSkills, setMatchSkills] = useState('');
  const [matchResults, setMatchResults] = useState(null);

  const queryClient = useQueryClient();

  const { data: technicians, isLoading } = useQuery({
    queryKey: ['technicians'],
    queryFn: async () => {
      const res = await fetch('/api/fsm/technicians');
      if (!res.ok) throw new Error('Failed to load');
      return res.json();
    },
  });

  const createMutation = useMutation({
    mutationFn: async (data) => {
      const res = await fetch('/api/fsm/technicians', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(data),
      });
      if (!res.ok) throw new Error('Failed to create');
      return res.json();
    },
    onSuccess: () => {
      queryClient.invalidateQueries(['technicians']);
      setShowForm(false);
    },
  });

  const matchMutation = useMutation({
    mutationFn: async (skills) => {
      const res = await fetch('/api/fsm/technicians/match', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ required_skills: skills.split(',').map(s => s.trim()) }),
      });
      if (!res.ok) throw new Error('Match failed');
      return res.json();
    },
    onSuccess: (data) => setMatchResults(data.candidates),
  });

  return (
    <div className="technician-admin">
      <h2>{t('fsm.technician_profiles.title')}</h2>

      <div className="toolbar">
        <button className="btn btn-primary" onClick={() => setShowForm(!showForm)}>
          {showForm ? t('fsm.technician_profiles.buttons.cancel') : t('fsm.technician_profiles.buttons.add_technician')}
        </button>
      </div>

      {showForm && (
        <form
          className="card p-3 my-3"
          onSubmit={(e) => {
            e.preventDefault();
            createMutation.mutate({
              employee_id: parseInt(form.employee_id),
              skills: form.skills.split(',').map(s => s.trim()),
              zones: form.zones.split(',').map(s => s.trim()).filter(Boolean),
              certifications: form.certifications.split(',').map(s => s.trim()).filter(Boolean),
            });
          }}
        >
          <div className="row">
            <div className="col-md-3">
              <label>{t('fsm.technician_profiles.form.employee_id')}</label>
              <input type="number" className="form-control" value={form.employee_id}
                onChange={(e) => setForm({ ...form, employee_id: e.target.value })} required />
            </div>
            <div className="col-md-3">
              <label>{t('fsm.technician_profiles.form.skills')}</label>
              <input type="text" className="form-control" value={form.skills}
                onChange={(e) => setForm({ ...form, skills: e.target.value })} required />
            </div>
            <div className="col-md-3">
              <label>{t('fsm.technician_profiles.form.zones')}</label>
              <input type="text" className="form-control" value={form.zones}
                onChange={(e) => setForm({ ...form, zones: e.target.value })} />
            </div>
            <div className="col-md-3">
              <label>{t('fsm.technician_profiles.form.certifications')}</label>
              <input type="text" className="form-control" value={form.certifications}
                onChange={(e) => setForm({ ...form, certifications: e.target.value })} />
            </div>
          </div>
          <button type="submit" className="btn btn-success mt-2" disabled={createMutation.isLoading}>
            {createMutation.isLoading ? t('fsm.technician_profiles.buttons.saving') : t('fsm.technician_profiles.buttons.save')}
          </button>
        </form>
      )}

      <div className="match-section my-3">
        <h3>{t('fsm.technician_profiles.match_section.title')}</h3>
        <div className="d-flex gap-2">
          <input type="text" className="form-control" placeholder={t('fsm.technician_profiles.match_section.required_skills')}
            value={matchSkills} onChange={(e) => setMatchSkills(e.target.value)} />
          <button className="btn btn-secondary" onClick={() => matchMutation.mutate(matchSkills)}
            disabled={matchMutation.isLoading || !matchSkills}>
            {matchMutation.isLoading ? t('fsm.technician_profiles.buttons.matching') : t('fsm.technician_profiles.buttons.find_match')}
          </button>
        </div>

        {matchResults && (
          <table className="table table-sm mt-2">
            <thead>
              <tr><th>{t('fsm.technician_profiles.match_table.technician')}</th><th>{t('fsm.technician_profiles.match_table.score')}</th><th>{t('fsm.technician_profiles.match_table.matched')}</th><th>{t('fsm.technician_profiles.match_table.missing')}</th></tr>
            </thead>
            <tbody>
              {matchResults.map((c, i) => (
                <tr key={i}>
                  <td>#{c.technician_id} (Employee #{c.employee_id})</td>
                  <td>{(c.score * 100).toFixed(0)}%</td>
                  <td>{c.matched_skills.join(', ')}</td>
                  <td>{c.missing_skills.join(', ') || '—'}</td>
                </tr>
              ))}
              {matchResults.length === 0 && <tr><td colSpan={4} className="text-muted">{t('fsm.technician_profiles.no_matches')}</td></tr>}
            </tbody>
          </table>
        )}
      </div>

      <h3>{t('fsm.technician_profiles.all_technicians')}</h3>
      {isLoading ? <p>{t('fsm.technician_profiles.loading')}</p> : (
        <table className="table table-sm">
          <thead><tr><th>{t('fsm.technician_profiles.table.id')}</th><th>{t('fsm.technician_profiles.table.employee')}</th><th>{t('fsm.technician_profiles.table.skills')}</th><th>{t('fsm.technician_profiles.table.zones')}</th></tr></thead>
          <tbody>
            {technicians?.map(t => (
              <tr key={t.id}>
                <td>{t.id}</td>
                <td>#{t.employee_id}</td>
                <td>{t.skills.join(', ')}</td>
                <td>{t.zones.join(', ') || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
