import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import MapLegend from './MapLegend'

describe('MapLegend', () => {
  it('shows the three risk bands with their score ranges and colour classes', () => {
    const { container } = render(<MapLegend hoveredRiskBand={null} onRiskBandHover={() => {}} />)

    expect(screen.getByText('High Risk (75 - 100)')).toBeInTheDocument()
    expect(screen.getByText('Medium Risk (40 - 74)')).toBeInTheDocument()
    expect(screen.getByText('Low Risk (0 - 39)')).toBeInTheDocument()

    expect(container.querySelector('.color-box.risk-high')).toBeInTheDocument()
    expect(container.querySelector('.color-box.risk-medium')).toBeInTheDocument()
    expect(container.querySelector('.color-box.risk-low')).toBeInTheDocument()
  })

  it('highlights only the hovered band', () => {
    const { container } = render(<MapLegend hoveredRiskBand="medium" onRiskBandHover={() => {}} />)
    const active = container.querySelectorAll('.legend-item.active')
    expect(active).toHaveLength(1)
    expect(active[0]).toHaveTextContent('Medium Risk')
  })

  it('reports hovered bands and clears on mouse leave', async () => {
    const onHover = vi.fn()
    const { container } = render(<MapLegend hoveredRiskBand={null} onRiskBandHover={onHover} />)
    const user = userEvent.setup()

    await user.hover(screen.getByText('High Risk (75 - 100)'))
    expect(onHover).toHaveBeenLastCalledWith('high')

    await user.unhover(container.querySelector('.map-legend'))
    expect(onHover).toHaveBeenLastCalledWith(null)
  })
})
