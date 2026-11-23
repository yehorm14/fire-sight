// Single place for runtime configuration. Set these in .env.local (see ../.env.example).
const stripTrailingSlash = (url) => url.replace(/\/+$/, '');

export const BACKEND_URL = stripTrailingSlash(
  import.meta.env.VITE_BACKEND_URL || 'http://localhost:8000'
);

// Optional external events feed. When unset, the map shows no events.
export const EVENTS_API_URL = import.meta.env.VITE_EVENTS_API_URL || '';
// Explicit demo mode: show labelled, invented sample events instead of a feed.
export const EVENTS_DEMO_MODE = import.meta.env.VITE_EVENTS_DEMO === 'true';

// Optional browser-authorised basemap template and its provider attribution.
export const MAP_TILE_URL = import.meta.env.VITE_MAP_TILE_URL || '';
export const MAP_TILE_ATTRIBUTION = import.meta.env.VITE_MAP_TILE_ATTRIBUTION || '';
