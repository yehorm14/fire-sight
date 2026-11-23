import { useEffect, useRef, useState } from 'react';
import { GeoJSON } from 'react-leaflet';
import { BACKEND_URL } from '../../config';
import { describeFailure } from '../../apiError';


const getRiskColor = (riskFactor) => {
  if (riskFactor >= 75) return '#d73027';
  if (riskFactor >= 40) return '#fdae61';
  return '#1a9850';
};

const getRiskBand = (riskFactor) => {
  if (riskFactor >= 75) return 'high';
  if (riskFactor >= 40) return 'medium';
  return 'low';
};

const safeText = (value) => {
  if (value === null || value === undefined) return '';
  return String(value);
};

function showProjection(popup, prediction, lead) {
  const container = popup?.getElement()?.querySelector('[data-projection]');
  if (!container) return;
  container.replaceChildren();
  const result = prediction?.projections?.find((step) => step.lead === lead);
  const isModel = prediction?.period_unit === 'financial_year';

  if (lead) {
    const row = document.createElement('p');
    row.className = 'popup-row';
    if (result) {
      const period = isModel
        ? (result.financial_year ? `FY ${result.financial_year}` : `Financial-year step ${lead}`)
        : `Sample months ${lead - 5}–${lead}`;
      const unit = isModel ? 'dwelling fires' : 'sample incidents';
      const range = result.lower != null && result.upper != null
        ? ` (residual range ${result.lower}–${result.upper})` : '';
      row.textContent = `${period}: ${result.forecast} ${unit}${range}`;
    } else {
      row.textContent = 'Projection unavailable for this period.';
    }
    container.append(row);
  }

  const popupElement = popup.getElement();
  const button = popupElement.querySelector('.popup-ai-button');
  const meta = popupElement.querySelector('[data-ai-meta]');
  const text = popupElement.querySelector('[data-ai-text]');
  if (button && meta && text && button.dataset.lead !== String(lead)) {
    button.dataset.lead = String(lead);
    button.explanationRequest = null;
    button.disabled = false;
    button.textContent = 'AI Actionable Next Steps';
    meta.textContent = '';
    text.textContent = 'Click for AI-powered prevention and capacity planning recommendations.';
  }

  if (prediction?.note) {
    const note = document.createElement('p');
    note.className = 'popup-row';
    const { first_financial_year: first, last_financial_year: last, years_of_data: years } = prediction;
    note.textContent = isModel && first && last && years
      ? `SFRS dwelling-fire data · ${years} observed years, FY ${first} to ${last}`
      : prediction.note;
    container.append(note);
  }
}

const RiskLayer = ({ lead = 0, hoveredRiskBand = null, dataSource = 'mock' }) => {
  const [geoData, setGeoData] = useState(null);
  const [error, setError] = useState(null);

  const geoJsonRef = useRef(null);
  const selectedLead = useRef(lead);

  useEffect(() => {
    selectedLead.current = lead;
    geoJsonRef.current?.eachLayer((layer) => {
      if (layer.isPopupOpen()) {
        showProjection(layer.getPopup(), layer.feature.properties.prediction, lead);
      }
    });
  }, [lead]);

  useEffect(() => {
    let cancelled = false;
    setGeoData(null); // clear immediately so the old layer unmounts before new data arrives

    const fetchWards = async () => {
      try {
        const response = await fetch(
          `${BACKEND_URL}/api/strategic/wards.geojson?source=${dataSource}`
        );
        if (!response.ok) {
          const message = await describeFailure(response, 'Could not load Glasgow ward data from the backend.');
          if (!cancelled) setError(message);
          return;
        }

        const payload = await response.json();
        if (!cancelled) {
          setGeoData(payload);
          setError(null);
        }
      } catch (err) {
        if (!cancelled) {
          console.error('Error loading ward data:', err);
          setError('Could not load Glasgow ward data from the backend.');
        }
      }
    };

    fetchWards();

    return () => {
      cancelled = true;
    };
  }, [dataSource]);

  const styleRegion = (feature) => {
    const riskFactor = feature.properties.risk_score;
    const band = getRiskBand(riskFactor);
    const isBandMatch = !hoveredRiskBand || hoveredRiskBand === band;

    return {
      fillColor: getRiskColor(riskFactor),
      weight: isBandMatch ? 1.8 : 1,
      opacity: isBandMatch ? 0.95 : 0.35,
      color: '#ffffff',
      fillOpacity: isBandMatch ? 0.42 : 0.12
    };
  };

  const onEachFeature = (feature, layer) => {
    if (!feature.properties) return;

    const p = feature.properties;
    const wardId = safeText(p.ward_id ?? p.id ?? '');
    const baseRisk = p.risk_score;
    const drivers = Array.isArray(p.drivers) ? p.drivers : [];
    const isModel = p.data_source === 'model';
    const modelComponents = p.model_components ?? null;

    const componentsBadge = isModel && modelComponents
      ? `<span class="popup-components-badge">${modelComponents}/5 indicators</span>`
      : '';

    const sourceBadge = `<span class="popup-source-badge popup-source-badge--${isModel ? 'model' : 'mock'}">${isModel ? 'Linear model' : 'Mock data'}</span>`;

    layer.bindPopup(`
      <div class="custom-popup" style="min-width: 220px;">
        <div class="popup-header">
          <h3>${p.ward_name ?? p.name ?? 'Unknown area'}</h3>
          ${sourceBadge}
          ${componentsBadge}
        </div>

        <div class="popup-score">
          <span class="popup-score-value" style="color: ${getRiskColor(baseRisk)}">
            ${baseRisk}
          </span>
          <span class="popup-score-label">/ 100 Baseline Risk</span>
        </div>
        <p class="popup-row"><b>Ward ID:</b> ${p.ward_id ?? 'n/a'}</p>
        <div data-projection></div>

        <div class="popup-card">
          <p><b>Primary Drivers:</b><br/> ${drivers.join(', ') || 'Risk drivers unavailable.'}</p>
        </div>

        <div class="popup-card action">
          <p><b>System Recommendation:</b><br/> Prioritise prevention review and targeted community safety activity for this ward.</p>
        </div>

        <div class="popup-ai">
          <div class="popup-ai-row">
            <button
              type="button"
              class="popup-ai-button"
              data-mode="ward"
              data-id="${wardId}"
            >
              AI Actionable Next Steps
            </button>
            <span class="popup-ai-meta" data-ai-meta></span>
          </div>
          <div class="popup-ai-text" data-ai-text>
            Click for AI-powered prevention and capacity planning recommendations.
          </div>
        </div>
      </div>
    `);

    if (!layer.__aiExplainWired) {
      layer.__aiExplainWired = true;

      layer.on('popupopen', async (event) => {
        const popupEl = event.popup?.getElement?.();
        if (!popupEl) return;

        showProjection(event.popup, p.prediction, selectedLead.current);
        const btn = popupEl.querySelector('.popup-ai-button');
        const metaEl = popupEl.querySelector('[data-ai-meta]');
        const textEl = popupEl.querySelector('[data-ai-text]');
        if (!btn || !textEl) return;

        if (btn.dataset.wired === 'true') return;
        btn.dataset.wired = 'true';

        btn.addEventListener('click', async () => {
          const mode = btn.dataset.mode;
          const id = btn.dataset.id;
          if (!mode || !id) return;

          const requestedLead = selectedLead.current;
          const request = Symbol();
          btn.explanationRequest = request;
          const isCurrent = () => btn.explanationRequest === request && requestedLead === selectedLead.current;
          btn.disabled = true;
          btn.textContent = 'Generating…';
          if (metaEl) metaEl.textContent = '';
          textEl.textContent = 'Generating AI recommendations…';

          try {
            const response = await fetch(
              `${BACKEND_URL}/api/explain?mode=${encodeURIComponent(mode)}&id=${encodeURIComponent(id)}&source=${encodeURIComponent(dataSource)}&lead=${requestedLead}`
            );
            if (!response.ok) {
              const message = await describeFailure(response, 'Could not load the AI overview right now. Please try again.');
              if (isCurrent()) textEl.textContent = message;
              return;
            }
            const payload = await response.json();
            if (!isCurrent()) return;

            const source = safeText(payload?.source || '');
            const text = safeText(payload?.text || 'No explanation returned.');
            if (metaEl) metaEl.textContent = source ? `Source: ${source}` : '';
            textEl.textContent = text;
          } catch {
            if (!isCurrent()) return;
            textEl.textContent =
              'Could not load the AI overview right now. Please try again.';
          } finally {
            if (isCurrent()) {
              btn.disabled = false;
              btn.textContent = 'AI Actionable Next Steps';
            }
          }
        });
      });
    }

    layer.on({
      mouseover: (event) => {
        const hoveredLayer = event.target;
        hoveredLayer.setStyle({
          weight: 2.6,
          color: '#ffffff',
          opacity: 1,
          fillOpacity: 0.52
        });
      },
      mouseout: (event) => {
        layer.options.style = styleRegion(feature);
        event.target.setStyle(layer.options.style);
      }
    });
  };

  return (
    <>
      {error && (
        <div
          style={{
            position: 'absolute',
            top: 16,
            left: 16,
            zIndex: 1100,
            background: 'white',
            color: '#a50f15',
            padding: '10px 12px',
            borderRadius: 8,
            boxShadow: '0 2px 10px rgba(0,0,0,0.2)'
          }}
        >
          {error}
        </div>
      )}

      {geoData && (
        <GeoJSON
          key={dataSource}
          ref={geoJsonRef}
          data={geoData}
          attribution={'Ward boundaries: <a href="https://www.ons.gov.uk/methodology/geography/licences">Office for National Statistics</a>. Contains OS data © Crown copyright and database right 2024.'}
          style={styleRegion}
          onEachFeature={onEachFeature}
        />
      )}
    </>
  );
};

export default RiskLayer;
