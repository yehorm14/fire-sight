// Pure helpers for the events overlay: normalising feed rows and deciding which are in the window.
//
// Date semantics: an event date written as a bare calendar date ("2026-11-23") covers that whole
// LOCAL day, so it stays visible until local midnight ends it. A date with a time component is an
// instant. An optional end date/time makes the event a start..end range; with no end it ends where
// it starts. The window runs from "now" to the end of the local calendar day that is N calendar
// months ahead (day clamped at month end, so 31 Jan + 1 month is 28/29 Feb, not 3 March).

const ISO_DATE_TIME = /^(\d{4}-\d{2}-(\d{2}))(T(?:[01]\d|2[0-3]):[0-5]\d(?::[0-5]\d(?:\.\d+)?)?(?:Z|[+-](?:[01]\d|2[0-3]):?[0-5]\d)?)?$/;

const parseOne = (value, isEnd) => {
  if (typeof value !== 'string') return null;
  const match = ISO_DATE_TIME.exec(value.trim());
  if (!match) return null;

  const [dateTime, calendarDate, day, time] = match;
  // Check the calendar date before any offset or local-time conversion.
  const calendar = new Date(`${calendarDate}T00:00:00Z`);
  if (calendar.getUTCDate() !== Number(day)) return null;

  const date = new Date(time ? dateTime : `${calendarDate}T00:00:00`);
  if (Number.isNaN(date.getTime())) return null;

  // A date-only end is exclusive: the start of the following local day.
  const exclusive = !time && isEnd;
  if (exclusive) date.setDate(date.getDate() + 1);
  return { date, exclusive };
};

/** Parse feed dates into { start, end, endExclusive } (Dates), or null if invalid. */
export const parseEventRange = (startValue, endValue) => {
  const start = parseOne(startValue, false);
  if (!start) return null;
  const end = parseOne(endValue ?? startValue, true);
  if (!end || (end.exclusive ? end.date <= start.date : end.date < start.date)) return null;
  return { start: start.date, end: end.date, endExclusive: end.exclusive };
};

/** Add calendar months, clamping the day so month ends do not overflow. */
export const addCalendarMonths = (date, months) => {
  const result = new Date(date.getFullYear(), date.getMonth() + months, 1);
  const lastDay = new Date(result.getFullYear(), result.getMonth() + 1, 0).getDate();
  result.setDate(Math.min(date.getDate(), lastDay));
  return result;
};

/** Exclusive end of the window: start of the local day after the day `months` ahead. */
export const windowEnd = (now, months) => {
  const target = addCalendarMonths(now, months);
  return new Date(target.getFullYear(), target.getMonth(), target.getDate() + 1);
};

export const isEventInWindow = (event, now, months) => {
  const range = parseEventRange(event.date, event.endDate);
  if (!range) return false;
  const stillRunning = range.endExclusive ? range.end > now : range.end >= now;
  return stillRunning && range.start < windowEnd(now, months);
};
