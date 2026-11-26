import { useState } from 'react';
import './TopRiskAreas.css';
import WardEvidence from './WardEvidence';

const riskColor = (score) => {
  if (score >= 75) return '#ef4444';
  if (score >= 40) return '#f97316';
  return '#22c55e';
};

export default function TopRiskAreas({
  result,
  dataSource,
  lead,
  selectedWardId,
  onSelectWard,
}) {
  const [pinnedWardId, setPinnedWardId] = useState('');
  const wards = result.data?.features?.map(({ properties }) => properties) || [];
  const ranked = [...wards].sort((a, b) => b.risk_score - a.risk_score || a.ward_id.localeCompare(b.ward_id)).slice(0, 5);
  const selected = wards.find((ward) => ward.ward_id === selectedWardId);
  const pinned = wards.find((ward) => ward.ward_id === pinnedWardId);

  function togglePin(id) {
    setPinnedWardId((current) => current === id ? '' : id);
  }

  return (
    <div className="top-areas">
      <h3>Ward ranking</h3>
      {result.status === 'loading' && <p className="top-areas-status" role="status">Loading Glasgow wards…</p>}
      {result.status === 'error' && (
        <>
          <p className="top-areas-status" role="alert">{result.error}</p>
          <button type="button" className="top-area-ai-btn" onClick={result.retry}>Retry wards</button>
        </>
      )}
      {result.status === 'ready' && wards.length === 0 && (
        <p className="top-areas-status" role="status">No wards are available.</p>
      )}
      {wards.length > 0 && (
        <>
          <p className="top-areas-status">
            {dataSource === 'model' ? 'Top five by vulnerability index' : 'Top five by sample score'}
          </p>
          <ul className="ward-rankings">
            {ranked.map((ward) => (
              <li key={ward.ward_id}>
                <button
                  type="button"
                  className="top-area-item top-area-header ward-rank-button"
                  aria-label={ward.ward_name + ', ' + ward.risk_score + ' out of 100'}
                  aria-pressed={ward.ward_id === selectedWardId}
                  onClick={() => onSelectWard(ward.ward_id === selectedWardId ? '' : ward.ward_id)}
                >
                  <span className="top-area-name">{ward.ward_name}</span>
                  <span className="top-area-score" style={{ color: riskColor(ward.risk_score) }}>{ward.risk_score + '/100'}</span>
                </button>
              </li>
            ))}
          </ul>
          <label className="ward-picker" htmlFor="all-ward-select">Explore any ward</label>
          <select id="all-ward-select" value={selectedWardId} onChange={(event) => onSelectWard(event.target.value)}>
            <option value="">Choose a ward</option>
            {[...wards].sort((a, b) => a.ward_name.localeCompare(b.ward_name)).map((ward) => (
              <option key={ward.ward_id} value={ward.ward_id}>{ward.ward_name}</option>
            ))}
          </select>
          {pinned && (
            <p className="ward-comparison">
              Pinned for comparison: <strong>{pinned.ward_name} · {pinned.risk_score}/100</strong>
              {selected?.ward_id !== pinned.ward_id && (
                <button type="button" className="top-area-ai-btn" onClick={() => togglePin(pinned.ward_id)}>
                  Clear pin
                </button>
              )}
            </p>
          )}
          <p className="sr-only" role="status">{selected ? 'Selected ' + selected.ward_name : ''}</p>
          {selected && (
            <WardEvidence
              key={selected.ward_id}
              ward={selected}
              dataSource={dataSource}
              lead={lead}
              onPin={togglePin}
              pinned={pinnedWardId === selected.ward_id}
            />
          )}
        </>
      )}
    </div>
  );
}
