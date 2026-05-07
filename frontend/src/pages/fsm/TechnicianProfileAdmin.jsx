import React, { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

/**
 * TechnicianProfileAdmin — CRUD + match preview for technician profiles.
 */
export default function TechnicianProfileAdmin() {
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
      <h2>Technician Profiles</h2>

      <div className="toolbar">
        <button className="btn btn-primary" onClick={() => setShowForm(!showForm)}>
          {showForm ? 'Cancel' : 'Add Technician'}
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
              <label>Employee ID</label>
              <input type="number" className="form-control" value={form.employee_id}
                onChange={(e) => setForm({ ...form, employee_id: e.target.value })} required />
            </div>
            <div className="col-md-3">
              <label>Skills (comma-separated)</label>
              <input type="text" className="form-control" value={form.skills}
                onChange={(e) => setForm({ ...form, skills: e.target.value })} required />
            </div>
            <div className="col-md-3">
              <label>Zones</label>
              <input type="text" className="form-control" value={form.zones}
                onChange={(e) => setForm({ ...form, zones: e.target.value })} />
            </div>
            <div className="col-md-3">
              <label>Certifications</label>
              <input type="text" className="form-control" value={form.certifications}
                onChange={(e) => setForm({ ...form, certifications: e.target.value })} />
            </div>
          </div>
          <button type="submit" className="btn btn-success mt-2" disabled={createMutation.isLoading}>
            {createMutation.isLoading ? 'Saving...' : 'Save'}
          </button>
        </form>
      )}

      <div className="match-section my-3">
        <h3>Match Technicians</h3>
        <div className="d-flex gap-2">
          <input type="text" className="form-control" placeholder="Required skills (comma-separated)"
            value={matchSkills} onChange={(e) => setMatchSkills(e.target.value)} />
          <button className="btn btn-secondary" onClick={() => matchMutation.mutate(matchSkills)}
            disabled={matchMutation.isLoading || !matchSkills}>
            {matchMutation.isLoading ? 'Matching...' : 'Find Match'}
          </button>
        </div>

        {matchResults && (
          <table className="table table-sm mt-2">
            <thead>
              <tr><th>Technician</th><th>Score</th><th>Matched</th><th>Missing</th></tr>
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
              {matchResults.length === 0 && <tr><td colSpan={4} className="text-muted">No matches</td></tr>}
            </tbody>
          </table>
        )}
      </div>

      <h3>All Technicians</h3>
      {isLoading ? <p>Loading...</p> : (
        <table className="table table-sm">
          <thead><tr><th>ID</th><th>Employee</th><th>Skills</th><th>Zones</th></tr></thead>
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
