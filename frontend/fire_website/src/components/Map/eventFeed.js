// Pure helpers for the events overlay: normalising feed rows and deciding which are in the window.
//
// Date semantics: an event date written as a bare calendar date ("2026-11-23") covers that whole
// LOCAL day, so it stays visible until local midnight ends it. A date with a time component is an
// instant. An optional end date/time makes the event a start..end range; with no end it ends where
// it starts. The window runs from "now" to the end of the local calendar day that is N calendar
// months ahead (day clamped at month end, so 31 Jan + 1 month is 28/29 Feb, not 3 March).

const DATE_ONLY = /^(\d{4})-(\d{2})-(\d{2})$/;

const parseOne = (value, isEnd) => {
  if (typeof value !== 'string') return null;
  const match = DATE_ONLY.exec(value.trim());
  if (match) {
    const [y, m, d] = [Number(match[1]), Number(match[2]), Number(match[3])];
    const check = new Date(y, m - 1, d);
    // Reject rollovers such as 2026-02-31.
    if (check.getFullYear() !== y || check.getMonth() !== m - 1 || check.getDate() !== d) {
      return null;
    }
    // A date-only end is exclusive: the start of the following local day.
    return isEnd
      ? { date: new Date(y, m - 1, d + 1), exclusive: true }
      : { date: check, exclusive: false };
  }
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : { date, exclusive: false };
};

/** Parse feed dates into { start, end, endExclusive } (Dates), or null if invalid. */
export const parseEventRange = (startValue, endValue) => {
  const start = parseOne(startValue, false);
  if (!start) return null;
  const end = parseOne(endValue || startValue, true);
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
