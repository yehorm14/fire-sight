import { afterEach, describe, expect, it, vi } from 'vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import TopRiskAreas from './TopRiskAreas'

const ward = (id, name, score) => ({
  ward_id: id,
  ward_name: name,
  risk_score: score,
  drivers: ['Deprivation'],
  prediction: { projections: [] },
})

const mockFetch = (data) =>
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, json: async () => data }))

afterEach(() => vi.unstubAllGlobals())

describe('TopRiskAreas', () => {
  it('lists wards from highest to lowest risk, capped at five', async () => {
    mockFetch([
      ward('w1', 'Ward One', 20),
      ward('w2', 'Ward Two', 90),
      ward('w3', 'Ward Three', 55),
      ward('w4', 'Ward Four', 75),
      ward('w5', 'Ward Five', 10),
      ward('w6', 'Ward Six', 60),
    ])
    render(<TopRiskAreas dataSource="mock" />)

    await screen.findByText('Ward Two')
    const names = Array.from(document.querySelectorAll('.top-area-name')).map((n) => n.textContent)
    expect(names).toEqual(['Ward Two', 'Ward Four', 'Ward Six', 'Ward Three', 'Ward One'])
  })

  it('colours scores by band using the legend thresholds', async () => {
    mockFetch([ward('a', 'High', 75), ward('b', 'Medium', 74), ward('c', 'Mid Low', 40), ward('d', 'Low', 39)])
    render(<TopRiskAreas dataSource="mock" />)

    await screen.findByText('High')
    const colourOf = (name) =>
      screen.getByText(name).closest('.top-area-header').querySelector('.top-area-score').style.color
    expect(colourOf('High')).toBe('rgb(239, 68, 68)')
    expect(colourOf('Medium')).toBe('rgb(249, 115, 22)')
    expect(colourOf('Mid Low')).toBe('rgb(249, 115, 22)')
    expect(colourOf('Low')).toBe('rgb(34, 197, 94)')
  })

  it('shows an error with retry when the request fails', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: false }))
    render(<TopRiskAreas dataSource="mock" />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load the risk rankings.')
  })
})

describe('TopRiskAreas model source unavailable', () => {
  it('explains that model data is unavailable and retries', async () => {
    const unavailable = {
      ok: false,
      status: 503,
      json: async () => ({ detail: { error: 'model_unavailable', reasons: ['DataZone scores are not loaded'] } }),
    }
    const fetchMock = vi.fn().mockResolvedValueOnce(unavailable)
      .mockResolvedValueOnce({ ok: true, json: async () => [] })
    vi.stubGlobal('fetch', fetchMock)
    render(<TopRiskAreas dataSource="model" />)

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Model data is unavailable')
    expect(alert).toHaveTextContent('DataZone scores are not loaded')

    fireEvent.click(screen.getByRole('button', { name: 'Retry' }))
    await screen.findByText('No ranked areas available.')
    expect(fetchMock).toHaveBeenCalledTimes(2)
  })
})
