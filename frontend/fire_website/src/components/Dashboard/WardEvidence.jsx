import { useState } from 'react';
import { describeFailure } from '../../apiError';
import { BACKEND_URL } from '../../config';
import { useApiResource } from '../../useApiResource';

function projectionSummary(prediction, lead) {
  const step = prediction?.projections?.find((candidate) => candidate.lead === lead);
  if (!step) return null;
  const annual = prediction.period_unit === 'financial_year';
  const period = annual && step.financial_year
    ? 'FY ' + step.financial_year
    : annual ? 'Year ' + lead : 'sample months ' + (lead - 5) + '–' + lead;
  const units = annual ? 'dwelling fires' : 'sample incidents';
  return { step, period, units };
}

function Projection({ prediction, lead }) {
  if (!lead) return null;
  const projection = projectionSummary(prediction, lead);
  if (!projection) return <p>Projection unavailable for this period.</p>;
  const { step, period, units } = projection;
  return (
    <p>
      {period} · <strong>{step.forecast} {units}</strong>
      {step.lower != null && step.upper != null && ' (residual range ' + step.lower + '–' + step.upper + ')'}
    </p>
  );
}

function WardZones({ wardId }) {
  const result = useApiResource(
    '/api/strategic/wards/' + encodeURIComponent(wardId) + '/zones',
    'Could not load the ward’s DataZones.',
  );
  if (result.status === 'loading') return <p role="status">Loading DataZones…</p>;
  if (result.status === 'error') {
    return (
      <>
        <p role="alert">{result.error}</p>
        <button type="button" className="top-area-ai-btn" onClick={result.retry}>Retry DataZones</button>
      </>
    );
  }
  const zones = result.data?.zones;
  if (!Array.isArray(zones)) {
    return (
      <>
        <p role="alert">Could not read the ward’s DataZones.</p>
        <button type="button" className="top-area-ai-btn" onClick={result.retry}>Retry DataZones</button>
      </>
    );
  }
  if (!zones.length) return <p role="status">No scored DataZones are assigned to this ward.</p>;
  return (
    <ul className="zone-list" aria-label="DataZones in this ward">
      {zones.map((zone) => (
        <li key={zone.datazone_id}>
          <strong>{zone.name || 'DataZone'} · {zone.risk_score}/100</strong>
          <p>{zone.datazone_id}</p>
          {!!zone.drivers?.length && <p>{zone.drivers.join(' · ')}</p>}
        </li>
      ))}
    </ul>
  );
}

function WardExplanation({ wardId, dataSource, lead }) {
  const [explanation, setExplanation] = useState(null);
  const [loading, setLoading] = useState(false);

  async function fetchExplanation() {
    setLoading(true);
    setExplanation(null);
    try {
      const query = new URLSearchParams({ mode: 'ward', id: wardId, source: dataSource, lead });
      const response = await fetch(BACKEND_URL + '/api/explain?' + query);
      if (!response.ok) throw new Error(await describeFailure(response, 'Could not load the explanation.'));
      const data = await response.json();
      setExplanation(data.text || 'No explanation returned.');
    } catch (error) {
      setExplanation(error instanceof TypeError ? 'Could not load the explanation.' : error.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <button type="button" className="top-area-ai-btn" onClick={fetchExplanation} disabled={loading}>
        {loading ? 'Loading explanation…' : 'Explain this ward'}
      </button>
      {explanation && <p role="status" className="top-area-ai-text">{explanation}</p>}
    </>
  );
}

export default function WardEvidence({ ward, dataSource, lead, onPin, pinned }) {
  const [showZones, setShowZones] = useState(false);
  const { ward_id: wardId, prediction } = ward;
  const isModel = dataSource === 'model';
  const hasWardZones = isModel && ward.score_method === 'datazone_aggregate';
  return (
    <section className="ward-evidence top-area-item" aria-label={ward.ward_name + ' evidence'}>
      <h4>{ward.ward_name}</h4>
      <p>{wardId} · May 2024 ward boundary</p>

      <dl>
        <dt>{isModel ? 'Vulnerability index' : 'Sample score'}</dt>
        <dd>
          <strong>{ward.risk_score}/100</strong>
          {isModel && ' · SIMD 2020'}
          {isModel && ward.score_method_note && <p>{ward.score_method_note}</p>}
          {!!ward.drivers?.length && <p>{ward.drivers.join(' · ')}</p>}
        </dd>
        {isModel && (
          <>
            <dt>Observed dwelling fires · SFRS</dt>
            <dd>
              {prediction?.last_observed_count != null && prediction.last_financial_year
                ? <p><strong>{prediction.last_observed_count} fires</strong> · FY {prediction.last_financial_year}</p>
                : <p>Latest observed count unavailable.</p>}
              {prediction?.first_financial_year && prediction.last_financial_year && (
                <p>Observation period FY {prediction.first_financial_year}–{prediction.last_financial_year}</p>
              )}
            </dd>
          </>
        )}
        <dt>{isModel ? 'Annual projection · SFRS linear trend' : 'Sample projection'}</dt>
        <dd>
          {lead
            ? <Projection prediction={prediction} lead={lead} />
            : <p>Choose a period in the Ward projection control.</p>}
        </dd>
      </dl>

      <div className="ward-evidence-actions">
        <button type="button" className="top-area-ai-btn" aria-pressed={pinned} onClick={() => onPin(wardId)}>
          {pinned ? 'Unpin comparison' : 'Pin for comparison'}
        </button>
        {hasWardZones && (
          <button
            type="button"
            className="top-area-ai-btn"
            aria-expanded={showZones}
            aria-controls="ward-zone-details"
            onClick={() => setShowZones((shown) => !shown)}
          >
            {showZones ? 'Hide DataZones' : 'Show DataZones (' + ward.zone_count + ')'}
          </button>
        )}
        <WardExplanation key={lead} wardId={wardId} dataSource={dataSource} lead={lead} />
      </div>
      {hasWardZones && (
        <div id="ward-zone-details" hidden={!showZones}>
          {showZones && <WardZones wardId={wardId} />}
        </div>
      )}
    </section>
  );
}
