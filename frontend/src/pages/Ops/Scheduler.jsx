// T264: Scheduler monitoring page - auto-refresh + Run now button.

import React, { useState, useEffect } from 'react';
import useApi from '../../hooks/useApi';

export default function Scheduler() {
  const { data, loading, error, refetch } = useApi('/ops/scheduler/jobs');
  const [runningJob, setRunningJob] = useState(null);

  // Auto-refresh every 30s
  useEffect(() => {
    const interval = setInterval(refetch, 30000);
    return () => clearInterval(interval);
  }, [refetch]);

  const handleRunNow = async (jobId) => {
    setRunningJob(jobId);
    try {
      const response = await fetch(`/api/ops/scheduler/jobs/${jobId}/run-now`, {
        method: 'POST',
      });
      if (response.ok) {
        setTimeout(refetch, 1000);
      }
    } catch (err) {
      console.error('Failed to run job:', err);
    } finally {
      setRunningJob(null);
    }
  };

  if (loading) return <div className="p-4">Loading scheduler jobs...</div>;
  if (error) return <div className="p-4 text-red-500">Error: {error}</div>;

  const jobs = data?.jobs || [];

  return (
    <div className="p-6">
      <div className="flex justify-between items-center mb-6">
        <h1 className="text-2xl font-bold">Scheduler Jobs</h1>
        <button
          onClick={refetch}
          className="bg-gray-500 text-white px-4 py-2 rounded hover:bg-gray-600"
        >
          Refresh
        </button>
      </div>

      <div className="bg-white rounded-lg shadow">
        <table className="w-full">
          <thead>
            <tr className="border-b">
              <th className="text-left p-3">Job ID</th>
              <th className="text-left p-3">Name</th>
              <th className="text-left p-3">Status</th>
              <th className="text-left p-3">Next Run</th>
              <th className="text-left p-3">Trigger</th>
              <th className="text-left p-3">Actions</th>
            </tr>
          </thead>
          <tbody>
            {jobs.map((job) => (
              <tr key={job.job_id} className="border-b hover:bg-gray-50">
                <td className="p-3 font-mono text-sm">{job.job_id}</td>
                <td className="p-3">{job.name}</td>
                <td className="p-3">
                  <span className={`px-2 py-1 rounded text-sm ${
                    job.status === 'scheduled' ? 'bg-green-100 text-green-800' :
                    job.status === 'paused' ? 'bg-yellow-100 text-yellow-800' :
                    'bg-gray-100 text-gray-800'
                  }`}>
                    {job.status}
                  </span>
                </td>
                <td className="p-3 text-sm">
                  {job.next_run ? new Date(job.next_run).toLocaleString() : 'N/A'}
                </td>
                <td className="p-3 text-sm">{job.trigger}</td>
                <td className="p-3">
                  <button
                    onClick={() => handleRunNow(job.job_id)}
                    disabled={runningJob === job.job_id}
                    className="bg-blue-500 text-white px-3 py-1 rounded text-sm hover:bg-blue-600 disabled:opacity-50"
                  >
                    {runningJob === job.job_id ? 'Running...' : 'Run now'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
