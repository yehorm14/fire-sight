import './Map.css';
import { MAP_TILE_ATTRIBUTION, MAP_TILE_URL } from '../../config';

const MapLegend = ({ hoveredRiskBand, onRiskBandHover }) => {
  return (
    <div className="map-legend" onMouseLeave={() => onRiskBandHover(null)}>
      <h4>Baseline Ward Risk</h4>
      <p className="legend-subtitle">
        {MAP_TILE_URL && MAP_TILE_ATTRIBUTION
          ? 'Colours show each ward’s baseline score.'
          : 'Ward boundaries shown without a street basemap.'}
      </p>
      
      <div
        className={`legend-item ${hoveredRiskBand === 'high' ? 'active' : ''}`}
        onMouseEnter={() => onRiskBandHover('high')}
      >
        <div className="color-box risk-high"></div>
        <span>High Risk (75 - 100)</span>
      </div>
      <div
        className={`legend-item ${hoveredRiskBand === 'medium' ? 'active' : ''}`}
        onMouseEnter={() => onRiskBandHover('medium')}
      >
        <div className="color-box risk-medium"></div>
        <span>Medium Risk (40 - 74)</span>
      </div>
      <div
        className={`legend-item ${hoveredRiskBand === 'low' ? 'active' : ''}`}
        onMouseEnter={() => onRiskBandHover('low')}
      >
        <div className="color-box risk-low"></div>
        <span>Low Risk (0 - 39)</span>
      </div>
      <p className="legend-subtitle">
        Premises and any sample events are illustrative overlays.
      </p>
    </div>
  );
};

export default MapLegend;