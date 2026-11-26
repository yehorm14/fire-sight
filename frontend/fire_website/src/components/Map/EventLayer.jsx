import { Marker, Pane, Popup } from 'react-leaflet';
import { useEffect, useMemo, useState } from 'react';
import L from 'leaflet';
import { EVENTS_API_URL, EVENTS_DEMO_MODE } from '../../config';
import { isEventInWindow, parseEventRange } from './eventFeed';

/** Only show “big” events (major crowd / demand signal). */
const MIN_ATTENDANCE = 1000;

const eventAlertIcon = L.divIcon({
  className: 'event-marker-icon-root',
  html: `
    <div class="event-marker-badge" aria-hidden="true">
      <span class="event-marker-excl">!</span>
    </div>
  `,
  iconSize: [36, 36],
  iconAnchor: [18, 18],
  popupAnchor: [0, -22]
});

// Illustrative sample events, shown only in explicit demo mode (VITE_EVENTS_DEMO=true).
// Dates are offsets from today so the demo always has upcoming events to show.
const localDateString = (daysFromToday) => {
  const d = new Date();
  d.setDate(d.getDate() + daysFromToday);
  const pad = (n) => String(n).padStart(2, '0');
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
};

const SAMPLE_EVENTS = [
  { id: 'evt-1', name: 'Glasgow City Marathon Expo', location: 'SEC Glasgow', days: 21, estimatedAttendance: 11000, lat: 55.8591, lng: -4.2887 },
  { id: 'evt-2', name: 'Summer Riverside Festival', location: 'Glasgow Green', days: 120, estimatedAttendance: 18000, lat: 55.8517, lng: -4.2369 },
  { id: 'evt-3', name: 'Innovation and Tech Summit', location: 'Scottish Event Campus', days: 240, estimatedAttendance: 7000, lat: 55.8598, lng: -4.288 },
  { id: 'evt-4', name: 'Winter Market Launch', location: 'George Square', days: 400, estimatedAttendance: 9500, lat: 55.8612, lng: -4.2518 }
];

// Built when the component mounts, not at module load, so dates track the current day.
const buildFallbackEvents = () =>
  SAMPLE_EVENTS.map(({ days, ...event }) => ({ ...event, date: localDateString(days) }));

const bigEvents = (events) => events.filter((e) => e.estimatedAttendance > MIN_ATTENDANCE);

const TIMEFRAME_TO_MONTHS = {
  Current: 1,
  'In 6 months': 6,
  'In 1 year': 12,
  'In 1.5 years': 18
};

const normalizeEvent = (event, idx) => {
  if (event === null || typeof event !== 'object' || Array.isArray(event)) return null;

  const lat = Number(event.lat ?? event.latitude ?? event.coordinates?.lat);
  const lng = Number(event.lng ?? event.longitude ?? event.coordinates?.lng);
  const date = event.date ?? event.eventDate ?? event.startDate;

  if (!Number.isFinite(lat) || !Number.isFinite(lng) || !date) {
    return null;
  }

  return {
    id: event.id ?? `event-${idx}`,
    name: event.name ?? event.title ?? 'Unnamed event',
    location: event.location ?? event.venue ?? 'Location pending',
    date,
    endDate: event.endDate ?? event.end_date ?? undefined,
    estimatedAttendance: Number(
      event.estimatedAttendance ?? event.attendance ?? event.expectedAttendance ?? 0
    ),
    lat,
    lng
  };
};

const EventLayer = ({ timeFrame }) => {
  const [events, setEvents] = useState([]);
  const [status, setStatus] = useState('loading'); // loading | ready | error
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;

    const fetchEvents = async () => {
      if (EVENTS_DEMO_MODE) {
        setEvents(bigEvents(buildFallbackEvents()));
        setStatus('ready');
        return;
      }
      if (!EVENTS_API_URL) {
        // No feed configured and not in demo mode: show nothing rather than invented events.
        setEvents([]);
        setStatus('ready');
        return;
      }
      setStatus('loading');
      try {
        const response = await fetch(EVENTS_API_URL);
        if (!response.ok) {
          throw new Error('Failed to fetch events');
        }

        const payload = await response.json();
        const rawEvents = Array.isArray(payload) ? payload : payload?.events;
        if (!Array.isArray(rawEvents)) {
          throw new Error('Unexpected events payload');
        }
        const parsedEvents = bigEvents(
          rawEvents
            .map((event, idx) => normalizeEvent(event, idx))
            .filter((event) => event && parseEventRange(event.date, event.endDate))
        );

        if (!cancelled) {
          // A successful empty feed stays empty.
          setEvents(parsedEvents);
          setStatus('ready');
        }
      } catch {
        if (!cancelled) {
          setEvents([]);
          setStatus('error');
        }
      }
    };

    fetchEvents();

    return () => {
      cancelled = true;
    };
  }, [attempt]);

  const filteredEvents = useMemo(() => {
    const months = TIMEFRAME_TO_MONTHS[timeFrame] ?? 1;
    const now = new Date();
    return events.filter((event) => isEventInWindow(event, now, months));
  }, [events, timeFrame]);

  return (
    <>
      {EVENTS_DEMO_MODE && (
        <div className="event-feed-status event-feed-demo" role="note">
          Demo mode: sample events, not real data
        </div>
      )}
      {status === 'error' && (
        <div className="event-feed-status event-feed-error" role="alert">
          Events could not be loaded.{' '}
          <button type="button" onClick={() => setAttempt((n) => n + 1)}>
            Retry
          </button>
        </div>
      )}
    <Pane name="eventMarkersPane" style={{ zIndex: 550 }}>
      {filteredEvents.map((event) => (
        <Marker
          key={event.id}
          position={[event.lat, event.lng]}
          icon={eventAlertIcon}
          eventHandlers={{
            mouseover: (e) => {
              e.target.openPopup();
            },
            click: (e) => {
              e.target.openPopup();
            }
          }}
        >
          <Popup offset={[0, -8]} closeButton={false}>
            <div className="event-popup">
              <div className="event-popup-header">
                <h3>{event.name}</h3>
                <span className="event-risk-tag">Higher fire risk</span>
              </div>

              <div className="event-popup-grid">
                <p>
                  <span>Location</span>
                  <strong>{event.location}</strong>
                </p>
                <p>
                  <span>Date</span>
                  <strong>{parseEventRange(event.date)?.start.toLocaleDateString()}</strong>
                </p>
                <p>
                  <span>Estimated Attendance</span>
                  <strong>{event.estimatedAttendance.toLocaleString()}</strong>
                </p>
              </div>

              <p className="event-popup-note">
                Event demand may increase fire risk for this area in the selected timeframe.
              </p>
            </div>
          </Popup>
        </Marker>
      ))}
    </Pane>
    </>
  );
};

export default EventLayer;
