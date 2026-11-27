import { afterEach, describe, expect, it, vi } from 'vitest'
import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import App from '../../App'
import TopRiskAreas from './TopRiskAreas'

const ward = (id, name, score) => ({
  ward_id: id,
  ward_name: name,
  risk_score: score,
  drivers: ['Deprivation'],
  score_method: 'datazone_aggregate',
  score_method_note: 'Population-weighted mean',
  zone_count: 1,
  prediction: {
    period_unit: 'financial_year',
    first_financial_year: '2009/2010',
    last_financial_year: '2025/2026',
    last_observed_count: 23,
    interval_status: 'withheld_after_evaluation',
    forecast_release: {
      observation_source: {
        label: 'SFRS FY2025/26 best-fit ward series',
        last_financial_year: '2025/2026',
        method: 'Whole 2022 DataZones assigned to published electoral wards',
      },
      boundary: { edition: 'WD24' },
      model: { id: 'recency_weighted_linear_trend', version: 1 },
      issue_date: '2026-11-26',
    },
    projections: [{ lead: 1, financial_year: '2026/2027', forecast: 31, lower: null, upper: null }],
  },
})
const geography = (wards) => ({ features: wards.map((properties) => ({ properties })) })
const ready = (...wards) => ({ status: 'ready', data: geography(wards) })
const json = (body) => ({ ok: true, json: async () => body })

vi.mock('../Map/RiskMap', () => ({
  default: ({ geoData, selectedWardId, onSelectWard }) => (
    <div>
      <p aria-label="Map selection">{selectedWardId}</p>
      {geoData?.features.map(({ properties }) => (
        <button
          key={properties.ward_id}
          type="button"
          onClick={() => onSelectWard(properties.ward_id)}
        >
          {'Open ' + properties.ward_name + ' on map'}
        </button>
      ))}
    </div>
  ),
}))

afterEach(() => vi.unstubAllGlobals())

describe('TopRiskAreas', () => {
  it('ranks the same wards the map uses, caps the ranking at five, and offers all wards in the picker', () => {
    render(
      <TopRiskAreas dataSource="model" result={ready(
        ward('w1', 'Ward One', 20), ward('w2', 'Ward Two', 90),
        ward('w3', 'Ward Three', 55), ward('w4', 'Ward Four', 75),
        ward('w5', 'Ward Five', 10), ward('w6', 'Ward Six', 60),
      )} />,
    )
    const names = Array.from(document.querySelectorAll('.top-area-name')).map((n) => n.textContent)
    expect(names).toEqual(['Ward Two', 'Ward Four', 'Ward Six', 'Ward Three', 'Ward One'])
    expect(within(screen.getByRole('combobox', { name: 'Explore any ward' })).getByRole('option', { name: 'Ward Five' })).toBeVisible()
  })

  it('colours scores by band using the legend thresholds', () => {
    render(<TopRiskAreas dataSource="mock" result={ready(
      ward('a', 'High', 75), ward('b', 'Medium', 74), ward('c', 'Mid Low', 40), ward('d', 'Low', 39),
    )} />)
    const colourOf = (name) =>
      screen.getByRole('button', { name: new RegExp('^' + name + ', ') }).querySelector('.top-area-score').style.color
    expect(colourOf('High')).toBe('rgb(239, 68, 68)')
    expect(colourOf('Medium')).toBe('rgb(249, 115, 22)')
    expect(colourOf('Low')).toBe('rgb(34, 197, 94)')
  })

  it('distinguishes loading, a failed request with retry, and a successful empty result', async () => {
    const retry = vi.fn()
    const { rerender } = render(<TopRiskAreas result={{ status: 'loading' }} />)
    expect(screen.getByRole('status')).toHaveTextContent('Loading Glasgow wards')
    rerender(<TopRiskAreas result={{ status: 'error', error: 'Model data is unavailable.', retry }} />)
    expect(screen.getByRole('alert')).toHaveTextContent('Model data is unavailable.')
    await userEvent.click(screen.getByRole('button', { name: 'Retry wards' }))
    expect(retry).toHaveBeenCalledOnce()
    rerender(<TopRiskAreas result={ready()} />)
    expect(screen.getByRole('status')).toHaveTextContent('No wards are available.')
  })

  it('links map and keyboard selection, compares scores, and drills into one ward with dated evidence', async () => {
    const user = userEvent.setup()
    let zoneAttempts = 0
    const fetcher = vi.fn(async (url) => {
      if (url.endsWith('/api/status')) return json({
        model_loaded: true,
        ward_projection_periods: [{ lead: 1, financial_years: ['2026/2027'] }],
      })
      if (url.includes('/api/strategic/wards.geojson')) {
        return json(geography([ward('w1', 'Linn', 68), ward('w2', 'Southside Central', 54)]))
      }
      if (url.endsWith('/w2/zones')) {
        zoneAttempts += 1
        if (zoneAttempts === 1) return { ok: false, status: 500 }
        return json({ zones: [{ name: 'Govanhill West - 01', datazone_id: 'S01012345', risk_score: 59, drivers: [] }] })
      }
      throw new Error('Unexpected request ' + url)
    })
    vi.stubGlobal('fetch', fetcher)
    render(<App />)
    await screen.findByRole('button', { name: 'Open Linn on map' })
    await user.click(screen.getByRole('button', { name: 'Model', exact: true }))
    const rank = await screen.findByRole('button', { name: 'Linn, 68 out of 100' })
    rank.focus()
    await user.keyboard('{Enter}')
    expect(rank).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByLabelText('Map selection')).toHaveTextContent('w1')
    const linn = screen.getByRole('region', { name: 'Linn evidence' })
    expect(within(linn).getByText('Vulnerability index')).toBeVisible()
    expect(within(linn).getByText('23 fires').parentElement).toHaveTextContent('FY 2025/2026')
    await user.click(within(linn).getByRole('button', { name: 'Pin for comparison' }))

    await user.click(screen.getByRole('button', { name: 'Open Southside Central on map' }))
    expect(screen.getByRole('combobox', { name: 'Explore any ward' })).toHaveValue('w2')
    expect(screen.getByText('Linn · 68/100')).toBeVisible()
    const southside = screen.getByRole('region', { name: 'Southside Central evidence' })
    await user.selectOptions(screen.getByRole('combobox', { name: 'Ward projection' }), '1')
    expect(within(southside).getByText('31 dwelling fires').parentElement).toHaveTextContent('FY 2026/2027')
    expect(within(southside).getByText('23 fires').parentElement).toHaveTextContent('FY 2025/2026')
    expect(within(southside).getByText(/Prediction interval unavailable/)).toBeVisible()
    expect(within(southside).getByText(/SFRS FY2025\/26 best-fit ward series/))
      .toHaveTextContent('WD24 · Observations through FY 2025/2026'.replace('WD24 ·', 'WD24) ·'))
    expect(within(southside).getByText(/Issued 2026-11-26/)).toHaveTextContent('recency_weighted_linear_trend v1')

    await user.click(within(southside).getByRole('button', { name: 'Show DataZones (1)' }))
    expect(await within(southside).findByRole('alert')).toHaveTextContent('Could not load the ward’s DataZones')
    await user.click(within(southside).getByRole('button', { name: 'Retry DataZones' }))
    expect(await within(southside).findByText('Govanhill West - 01 · 59/100')).toBeVisible()
    expect(within(southside).getByText('S01012345')).toBeVisible()

    await user.click(screen.getByRole('button', { name: 'Mock', exact: true }))
    expect(await screen.findByText('Top five by sample score')).toBeVisible()
    expect(screen.queryByText('Observed dwelling fires · SFRS')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Show DataZones/ })).not.toBeInTheDocument()
    expect(screen.queryByText('Linn · 68/100')).not.toBeInTheDocument()
    expect(fetcher.mock.calls.filter(([url]) => url.endsWith('/wards.geojson?source=model'))).toHaveLength(1)
  })
})
