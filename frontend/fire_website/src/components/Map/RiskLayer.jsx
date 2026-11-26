import { useCallback, useEffect, useRef } from 'react';
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

  // Added projection rows change the popup's height after Leaflet initially lays it out.
  popup.update();
}

const RiskLayer = ({ lead = 0, hoveredRiskBand, dataSource, geoData, selectedWardId, onSelectWard }) => {
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

  const styleRegion = useCallback((feature) => {
    const { risk_score: score, ward_id: wardId } = feature.properties;
    const selected = wardId === selectedWardId;
    const isBandMatch = selected || !hoveredRiskBand || hoveredRiskBand === getRiskBand(score);

    return {
      fillColor: getRiskColor(score),
      weight: selected ? 3 : isBandMatch ? 1.8 : 1,
      opacity: isBandMatch ? 0.95 : 0.35,
      color: selected ? '#38bdf8' : '#ffffff',
      fillOpacity: isBandMatch ? 0.42 : 0.12,
    };
  }, [hoveredRiskBand, selectedWardId]);
  const currentStyle = useRef(styleRegion);

  useEffect(() => {
    currentStyle.current = styleRegion;
  }, [styleRegion]);

  useEffect(() => {
    geoJsonRef.current?.eachLayer((layer) => {
      if (layer.feature.properties.ward_id === selectedWardId) {
        layer.bringToFront();
        if (!layer.isPopupOpen()) layer.openPopup();
      } else if (layer.isPopupOpen()) {
        layer.closePopup();
      }
    });
  }, [geoData, selectedWardId]);

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
          <span class="popup-score-label">/ 100 ${isModel ? 'Vulnerability index' : 'Sample score'}</span>
        </div>
        <p class="popup-row"><b>Ward ID:</b> ${p.ward_id ?? 'n/a'}</p>
        <div data-projection></div>

        <div class="popup-card">
          <p><b>Primary Drivers:</b><br/> ${drivers.join(', ') || 'Risk drivers unavailable.'}</p>
        </div>

        <p class="popup-row"><a href="#ward-explorer">See ward evidence and comparison</a></p>

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
    `, { maxHeight: 270 });

    if (!layer.__aiExplainWired) {
      layer.__aiExplainWired = true;

      layer.on('popupopen', (event) => {
        onSelectWard(wardId);
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
        event.target.setStyle(currentStyle.current(feature));
      }
    });
  };

  return (
    <GeoJSON
      ref={geoJsonRef}
      data={geoData}
      attribution={'Ward boundaries: <a href="https://www.ons.gov.uk/methodology/geography/licences">Office for National Statistics</a>. Contains OS data © Crown copyright and database right 2024.'}
      style={styleRegion}
      onEachFeature={onEachFeature}
    />
  );
};

export default RiskLayer;
