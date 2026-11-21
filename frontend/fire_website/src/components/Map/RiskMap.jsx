import { useState } from 'react';
import { MapContainer, TileLayer } from 'react-leaflet';
import EventLayer from './EventLayer';
import MapLegend from './MapLegend';
import PremisesLayer from './PremisesLayer';
import RiskLayer from './RiskLayer';
import 'leaflet/dist/leaflet.css';
import './Map.css';
import { MAP_TILE_ATTRIBUTION, MAP_TILE_URL } from '../../config';

const RiskMap = ({
  lead,
  overlayTimeFrame,
  dataSource = 'mock',
  nightMode = false,
  showPremises = true,
}) => {
  const [hoveredRiskBand, setHoveredRiskBand] = useState(null);
  const glasgowCenter = [55.8642, -4.2518];

  return (
    <div className={`risk-map-container ${nightMode ? 'night-mode' : ''}`}>
      <MapLegend
        hoveredRiskBand={hoveredRiskBand}
        onRiskBandHover={setHoveredRiskBand}
      />

      <MapContainer
        center={glasgowCenter}
        zoom={12}
        className="risk-map-container"
        zoomControl={false}
      >
        {MAP_TILE_URL && MAP_TILE_ATTRIBUTION && (
          <TileLayer url={MAP_TILE_URL} attribution={MAP_TILE_ATTRIBUTION} />
        )}

        <RiskLayer lead={lead} hoveredRiskBand={hoveredRiskBand} dataSource={dataSource} />
        {showPremises && <PremisesLayer timeFrame={overlayTimeFrame} focus="city-centre" riskBandFilter="high" />}
        <EventLayer timeFrame={overlayTimeFrame} />
      </MapContainer>
    </div>
  );
};

export default RiskMap;
