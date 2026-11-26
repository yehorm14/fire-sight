import { describe, expect, it } from 'vitest'
import { addCalendarMonths, isEventInWindow, parseEventRange, windowEnd } from './eventFeed'

const at = (y, m, d, h = 0, min = 0) => new Date(y, m - 1, d, h, min)

describe('isEventInWindow', () => {
  it('keeps a date-only event for today visible after midnight', () => {
    const now = at(2026, 11, 23, 15, 30)
    expect(isEventInWindow({ date: '2026-11-23' }, now, 1)).toBe(true)
    expect(isEventInWindow({ date: '2026-11-23' }, at(2026, 11, 23, 23, 59), 1)).toBe(true)
  })

  it('drops a date-only event once its local day has ended', () => {
    expect(isEventInWindow({ date: '2026-11-22' }, at(2026, 11, 23, 0, 0), 1)).toBe(false)
  })

  it('treats a timed event as an instant', () => {
    const now = at(2026, 11, 23, 15, 0)
    expect(isEventInWindow({ date: '2026-11-23T10:00:00' }, now, 1)).toBe(false)
    expect(isEventInWindow({ date: '2026-11-23T18:00:00' }, now, 1)).toBe(true)
  })

  it('keeps the whole local day at a daylight-saving boundary', () => {
    const event = { date: '2026-03-08' }
    expect(isEventInWindow(event, at(2026, 3, 8, 23, 59), 1)).toBe(true)
    expect(isEventInWindow(event, at(2026, 3, 9), 1)).toBe(false)
  })

  it('compares timed events by their absolute offsets', () => {
    const now = new Date('2026-11-23T15:00:00Z')
    expect(isEventInWindow({ date: '2026-11-23T15:30:00+01:00' }, now, 1)).toBe(false)
    expect(isEventInWindow({ date: '2026-11-23T14:30:00-01:00' }, now, 1)).toBe(true)
  })

  it('shows a multi-day event that started earlier but has not ended', () => {
    const now = at(2026, 11, 23, 12)
    expect(isEventInWindow({ date: '2026-11-21', endDate: '2026-11-24' }, now, 1)).toBe(true)
    expect(isEventInWindow({ date: '2026-11-21', endDate: '2026-11-22' }, now, 1)).toBe(false)
  })

  it('includes the last calendar day of the window and excludes the next', () => {
    const now = at(2026, 11, 23, 12)
    expect(isEventInWindow({ date: '2026-12-23' }, now, 1)).toBe(true)
    expect(isEventInWindow({ date: '2026-12-24' }, now, 1)).toBe(false)
  })

  it('clamps month-end windows instead of overflowing', () => {
    const now = at(2027, 1, 31, 9)
    expect(addCalendarMonths(now, 1)).toEqual(at(2027, 2, 28))
    expect(windowEnd(now, 1)).toEqual(at(2027, 3, 1))
    expect(isEventInWindow({ date: '2027-02-28' }, now, 1)).toBe(true)
    expect(isEventInWindow({ date: '2027-03-01' }, now, 1)).toBe(false)
  })

  it('handles leap-day and year rollover', () => {
    expect(addCalendarMonths(at(2027, 8, 31), 6)).toEqual(at(2028, 2, 29))
    expect(addCalendarMonths(at(2026, 11, 30), 18)).toEqual(at(2028, 5, 30))
  })

  it.each([
    '2026-02-31T12:00:00Z',
    '2026-04-31T12:00:00+01:00',
    '02/31/2026',
    '2026-02-28T24:00:00Z',
    '2026-02-28T12:60:00Z',
    '2026-02-28T12:00:60Z',
    '2026-02-28T12:00:00+24:00',
    '2026-02-28T12:00:00+01:60',
  ])('rejects the malformed date or time %s', (value) => {
    expect(parseEventRange(value)).toBeNull()
    expect(parseEventRange('2026-01-01', value)).toBeNull()
  })

  it('retains leap-day timestamps and applies explicit time offsets', () => {
    const range = parseEventRange('2028-02-29T10:15:30.125+05:30')
    expect(range.start.toISOString()).toBe('2028-02-29T04:45:30.125Z')
    expect(range.end).toEqual(range.start)
  })

  it('rejects invalid or impossible dates', () => {
    const now = at(2026, 11, 23)
    expect(isEventInWindow({ date: '2026-02-31' }, now, 12)).toBe(false)
    expect(isEventInWindow({ date: 'soon' }, now, 12)).toBe(false)
    expect(isEventInWindow({ date: '2026-12-02', endDate: '2026-12-01' }, now, 12)).toBe(false)
  })
})
