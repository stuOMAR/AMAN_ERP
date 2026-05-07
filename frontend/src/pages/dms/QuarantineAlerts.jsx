import React from 'react';
import { useQuery } from '@tanstack/react-query';

/**
 * QuarantineAlerts — lists quarantined documents.
 */
export default function QuarantineAlerts() {
  const { data: items, isLoading } = useQuery({
    queryKey: ['dms-quarantine'],
    queryFn: async () => {
      const res = await fetch('/api/dms/quarantine');
      if (!res.ok) throw new Error('Failed to load');
      return res.json();
    },
  });

  if (isLoading) return <div>Loading...</div>;

  return (
    <div className="quarantine-alerts">
      <h3>Quarantined Documents</h3>
      {items?.length === 0 ? (
        <p className="text-muted">No quarantined documents</p>
      ) : (
        <table className="table table-sm table-danger">
          <thead>
            <tr>
              <th>ID</th>
              <th>Filename</th>
              <th>Size</th>
              <th>Scanned</th>
              <th>Engine</th>
            </tr>
          </thead>
          <tbody>
            {items?.map((item) => (
              <tr key={item.id}>
                <td>{item.id}</td>
                <td>{item.filename}</td>
                <td>{(item.file_size / 1024).toFixed(1)} KB</td>
                <td>{item.scanned_at || '—'}</td>
                <td>{item.scan_engine || '—'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
