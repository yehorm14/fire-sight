import { useEffect, useState } from 'react';
import './App.css';
import RiskMap from './components/Map/RiskMap';
import TopRiskAreas from './components/Dashboard/TopRiskAreas';
import { BACKEND_URL } from './config';

const SAMPLE_PERIODS = [
  { lead: 6, label: 'Sample months 1–6', overlay: 'In 6 months' },
  { lead: 12, label: 'Sample months 7–12', overlay: 'In 1 year' },
  { lead: 18, label: 'Sample months 13–18', overlay: 'In 1.5 years' },
];

function App() {
  const [lead, setLead] = useState(0);
  const [dataSource, setDataSource] = useState('mock');
  const [modelStatus, setModelStatus] = useState(null);
  const [showPremises, setShowPremises] = useState(true);
  const [nightMode, setNightMode] = useState(() => {
    try {
      const stored = window.localStorage.getItem('fireSightNightMode');
      return stored === null ? true : stored === 'true';
    } catch {
      return true;
    }
  });

  useEffect(() => {
    fetch(`${BACKEND_URL}/api/status`)
      .then((r) => r.json())
      .then(setModelStatus)
      .catch(() => setModelStatus(null));
  }, []);

  const modelLoaded = modelStatus?.model_loaded === true;
  const periods = dataSource === 'model'
    ? (modelStatus?.ward_projection_periods ?? []).map(({ lead, financial_years: years }) => ({
        lead,
        label: years.length === 1
          ? `FY ${years[0]} · Year ${lead} after data`
          : `Year ${lead} after data`,
      }))
    : SAMPLE_PERIODS;
  const overlayTimeFrame = periods.find((period) => period.lead === lead)?.overlay ?? 'Current';

  const selectSource = (source) => {
    if (source !== dataSource) {
      setLead(0);
      setDataSource(source);
    }
  };

  return (
    <div className={`app-container${nightMode ? ' night-mode' : ''}`}>
      <header className="app-header">
        <div className="app-header-brand">
          <div className="app-header-logo" aria-hidden="true">
            <svg width="22" height="22" viewBox="0 0 24 24" fill="none">
              <path
                d="M12.4 2.2c-.4 2.1-1.8 3.4-3.1 4.7-1.8 1.8-3.6 3.7-3.6 6.8 0 3.3 2.6 6.1 6.3 6.1 3.8 0 6.3-2.8 6.3-6.2 0-4.2-2.8-7.6-5.9-11.4z"
                fill="url(#flameOuter)"
              />
              <path
                d="M12.2 8.1c-1 1.3-2.2 2.4-2.2 4.4 0 1.7 1.3 3.1 3.1 3.1 1.8 0 3.1-1.4 3.1-3.2 0-1.8-1.1-3.1-2.8-4.3-.4-.3-.8-.6-1.2-1z"
                fill="url(#flameInner)"
              />
              <path d="M16.8 4.2l.5-1.5.5 1.5 1.5.5-1.5.5-.5 1.5-.5-1.5-1.5-.5 1.5-.5z" fill="#fde68a" />
              <defs>
                <linearGradient id="flameOuter" x1="12" y1="2.2" x2="12" y2="19.8" gradientUnits="userSpaceOnUse">
                  <stop stopColor="#fff7ed" />
                  <stop offset="0.5" stopColor="#fdba74" />
                  <stop offset="1" stopColor="#f97316" />
                </linearGradient>
                <linearGradient id="flameInner" x1="13.1" y1="8.1" x2="13.1" y2="15.6" gradientUnits="userSpaceOnUse">
                  <stop stopColor="#fef3c7" />
                  <stop offset="1" stopColor="#fb923c" />
                </linearGradient>
              </defs>
            </svg>
          </div>
          <div className="app-header-text">
            <h1>FireSight: Glasgow Risk Predictor</h1>
            <p>Operational risk view for Glasgow regions</p>
          </div>
        </div>

        <div className="app-header-controls">
          <label className="header-toggle" title="Switch map to dark style">
            <input
              type="checkbox"
              checked={nightMode}
              onChange={(e) => {
                const next = e.target.checked;
                setNightMode(next);
                try {
                  window.localStorage.setItem('fireSightNightMode', String(next));
                } catch {
                  // ignore
                }
              }}
            />
            <span>Night mode</span>
          </label>

          <div className="data-source-toggle">
            <span className="data-source-label">Data source</span>
            <div className="data-source-buttons">
              <button
                className={`ds-btn ${dataSource === 'mock' ? 'ds-btn--active' : ''}`}
                onClick={() => selectSource('mock')}
              >
                Mock
              </button>
              <button
                className={`ds-btn ${dataSource === 'model' ? 'ds-btn--active' : ''}`}
                onClick={() => selectSource('model')}
                disabled={!modelLoaded}
                title={!modelLoaded ? 'Run the data pipeline first' : 'Switch to linear model output'}
              >
                Model
              </button>
            </div>
          </div>
          <span className="app-header-badge">
            {dataSource === 'model' ? 'Linear model' : 'Mock data'}
          </span>
        </div>
      </header>

      <main className="app-main">
        <div className="timeframe-control">
          <label htmlFor="timeframe-select">Ward projection</label>
          <select
            id="timeframe-select"
            value={lead}
            onChange={(event) => setLead(Number(event.target.value))}
          >
            <option value={0}>Baseline risk</option>
            {periods.map((period) => (
              <option key={period.lead} value={period.lead}>
                {period.label}
              </option>
            ))}
          </select>

          <div className="layer-toggles">
            <label className="layer-toggle">
              <input
                type="checkbox"
                checked={showPremises}
                onChange={(e) => setShowPremises(e.target.checked)}
              />
              <span>High-risk premises</span>
            </label>
          </div>
        </div>

        <RiskMap
          lead={lead}
          overlayTimeFrame={overlayTimeFrame}
          dataSource={dataSource}
          nightMode={nightMode}
          showPremises={showPremises}
        />

        <div className={`top-risk-panel${nightMode ? ' night-mode' : ''}`}>
          <TopRiskAreas key={dataSource} dataSource={dataSource} lead={lead} />
        </div>
      </main>
    </div>
  );
}

export default App;
