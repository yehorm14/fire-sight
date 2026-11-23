// src/components/Dashboard/TopRiskAreas.jsx
import { useEffect, useState } from 'react';
import './TopRiskAreas.css';
import { BACKEND_URL } from '../../config';
import { describeFailure } from '../../apiError';


const TopRiskAreas = ({ dataSource = 'mock', lead = 0 }) => {
  const [result, setResult] = useState({ status: 'loading', areas: [] });
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    const fetchAreas = async () => {
      try {
        const path = dataSource === 'model' ? '/api/zones/top?n=5' : '/api/strategic/wards';
        const response = await fetch(`${BACKEND_URL}${path}`, { signal: controller.signal });
        if (!response.ok) {
          const message = await describeFailure(response, 'Could not load the risk rankings.');
          if (!controller.signal.aborted) setResult({ status: 'error', areas: [], message });
          return;
        }
        const data = await response.json();
        const areas = dataSource === 'model'
          ? data.map((zone) => ({
              id: zone.zoneid,
              mode: 'zone',
              name: zone.zonename || zone.zoneid,
              risk: zone.riskscore ?? 0,
              drivers: Array.isArray(zone.drivers) ? zone.drivers : [],
            }))
          : data
              .sort((a, b) => (b.risk_score ?? 0) - (a.risk_score ?? 0))
              .slice(0, 5)
              .map((ward) => ({
                id: ward.ward_id,
                mode: 'ward',
                name: ward.ward_name,
                risk: ward.risk_score,
                drivers: Array.isArray(ward.drivers) ? ward.drivers : [],
                projections: ward.prediction?.projections,
              }));
        if (!controller.signal.aborted) setResult({ status: 'ready', areas });
      } catch {
        if (!controller.signal.aborted) setResult({ status: 'error', areas: [] });
      }
    };
    fetchAreas();
    return () => controller.abort();
  }, [dataSource, attempt]);

  const retry = () => {
    setResult({ status: 'loading', areas: [] });
    setAttempt((value) => value + 1);
  };

  const riskColor = (score) => {
    if (score >= 75) return '#ef4444';
    if (score >= 40) return '#f97316';
    return '#22c55e';
  };

  return (
    <div className="top-areas">
      <h3>Top Risk {dataSource === 'model' ? 'Zones' : 'Wards'}</h3>
      {result.status === 'loading' && <p className="top-areas-status" role="status">Loading…</p>}
      {result.status === 'error' && (
        <>
          <p className="top-areas-status" role="alert">{result.message || 'Could not load the risk rankings.'}</p>
          <button type="button" className="top-area-ai-btn" onClick={retry}>Retry</button>
        </>
      )}
      {result.status === 'ready' && result.areas.length === 0 && (
        <p className="top-areas-status" role="status">No ranked areas available.</p>
      )}
      {result.areas.length > 0 && (
        <ul>
          {result.areas.map((a) => (
            <li key={a.id} className="top-area-item">
              <div className="top-area-header">
                <span className="top-area-name">{a.name}</span>
                <span className="top-area-score" style={{ color: riskColor(a.risk) }}>
                  {a.risk}
                </span>
              </div>

              {a.drivers.length > 0 && (
                <p className="top-area-drivers">{a.drivers.slice(0, 2).join(' · ')}</p>
              )}

              <AreaDetails key={lead} area={a} dataSource={dataSource} lead={lead} />
            </li>
          ))}
        </ul>
      )}
    </div>
  );
};

function AreaDetails({ area, dataSource, lead }) {
  const [explanation, setExplanation] = useState('');
  const [loading, setLoading] = useState(false);
  const projection = area.projections?.find((step) => step.lead === lead);

  const fetchExplanation = async () => {
    setLoading(true);
    try {
      const query = new URLSearchParams({ mode: area.mode, id: area.id, source: dataSource, lead });
      const response = await fetch(`${BACKEND_URL}/api/explain?${query}`);
      if (!response.ok) {
        setExplanation(await describeFailure(response, 'Could not load recommendations right now.'));
        return;
      }
      const data = await response.json();
      setExplanation(data.text || 'No recommendation returned.');
    } catch {
      setExplanation('Could not load recommendations right now.');
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      {projection && (
        <p className="top-area-forecast">
          Sample months {lead - 5}–{lead}: <strong>{projection.forecast}</strong> incidents
        </p>
      )}
      <button type="button" className="top-area-ai-btn" onClick={fetchExplanation} disabled={loading}>
        {loading ? 'Generating…' : 'AI Next Steps'}
      </button>
      {explanation && <div className="top-area-ai-text">{explanation}</div>}
    </>
  );
}

export default TopRiskAreas;
