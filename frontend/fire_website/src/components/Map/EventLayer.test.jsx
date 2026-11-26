import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { act, render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const cfg = vi.hoisted(() => ({ EVENTS_API_URL: 'https://feed.test/events', EVENTS_DEMO_MODE: false }))
vi.mock('../../config', () => cfg)
vi.mock('react-leaflet', () => ({
  Pane: ({ children }) => <div data-testid="pane">{children}</div>,
  Popup: ({ children }) => <div>{children}</div>,
  Marker: ({ children }) => <div data-testid="marker">{children}</div>,
}))

import EventLayer from './EventLayer'

const pad = (n) => String(n).padStart(2, '0')
const dayOffset = (n) => {
  const d = new Date()
  d.setDate(d.getDate() + n)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
const ev = (id, date, attendance = 5000) => ({
  id, name: `Event ${id}`, date, lat: 55.86, lng: -4.25, estimatedAttendance: attendance,
})
const ok = (body) => ({ ok: true, json: async () => body })

describe('EventLayer feed states', () => {
  beforeEach(() => {
    cfg.EVENTS_API_URL = 'https://feed.test/events'
    cfg.EVENTS_DEMO_MODE = false
  })
  afterEach(() => vi.unstubAllGlobals())

  it('keeps a successful empty feed empty (no invented events)', async () => {
    const fetchMock = vi.fn().mockResolvedValue(ok([]))
    vi.stubGlobal('fetch', fetchMock)
    await act(async () => {
      render(<EventLayer timeFrame="In 1 year" />)
    })
    expect(fetchMock).toHaveBeenCalledOnce()
    expect(screen.queryAllByTestId('marker')).toHaveLength(0)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.queryByRole('note')).not.toBeInTheDocument()
  })

  it('keeps a feed whose events are all filtered out empty', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      ok({ events: [ev('old', dayOffset(-30)), ev('small', dayOffset(2), 10)] })))
    await act(async () => {
      render(<EventLayer timeFrame="Current" />)
    })
    expect(screen.queryAllByTestId('marker')).toHaveLength(0)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it("shows today's date-only event", async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(ok([ev('today', dayOffset(0))])))
    render(<EventLayer timeFrame="Current" />)
    expect(await screen.findAllByTestId('marker')).toHaveLength(1)
  })

  it('shows a failure with retry and recovers on retry', async () => {
    const fetchMock = vi.fn()
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValueOnce(ok([ev('a', dayOffset(3))]))
    vi.stubGlobal('fetch', fetchMock)
    render(<EventLayer timeFrame="Current" />)
    expect(await screen.findByRole('alert')).toHaveTextContent('could not be loaded')
    expect(screen.queryAllByTestId('marker')).toHaveLength(0)
    await userEvent.setup().click(screen.getByRole('button', { name: 'Retry' }))
    expect(await screen.findAllByTestId('marker')).toHaveLength(1)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })

  it('treats an HTTP error as a failure', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false, json: async () => ({}) }))
    render(<EventLayer timeFrame="Current" />)
    expect(await screen.findByRole('alert')).toBeInTheDocument()
  })

  it('shows an error and retry for a malformed feed response', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(ok({ events: {} })))
    render(<EventLayer timeFrame="Current" />)
    expect(await screen.findByRole('alert')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
    expect(screen.queryAllByTestId('marker')).toHaveLength(0)
  })

  it('keeps valid events when the feed also contains invalid rows', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(
      ok({ events: [null, ev('bad', '2026-02-31T12:00:00Z'), ev('good', dayOffset(1))] })))
    render(<EventLayer timeFrame="Current" />)
    expect(await screen.findByText('Event good')).toBeInTheDocument()
    expect(screen.queryAllByTestId('marker')).toHaveLength(1)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('shows no events and no error when no feed is configured', () => {
    cfg.EVENTS_API_URL = ''
    const fetchMock = vi.fn()
    vi.stubGlobal('fetch', fetchMock)
    render(<EventLayer timeFrame="In 1.5 years" />)
    expect(screen.queryAllByTestId('marker')).toHaveLength(0)
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(fetchMock).not.toHaveBeenCalled()
  })

  it('uses labelled sample events only in explicit demo mode', async () => {
    cfg.EVENTS_API_URL = ''
    cfg.EVENTS_DEMO_MODE = true
    render(<EventLayer timeFrame="In 1.5 years" />)
    expect(await screen.findByRole('note')).toHaveTextContent('Demo mode')
    expect((await screen.findAllByTestId('marker')).length).toBeGreaterThan(0)
  })
})
