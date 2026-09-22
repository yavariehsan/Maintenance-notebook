import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import MaintenanceGuidePage from './page'

vi.mock('@/custom/screens/maintenance/SmartMaintenanceGuideScreen', () => ({
  SmartMaintenanceGuideScreen: () => <div data-testid="guide-screen" />,
}))

describe('MaintenanceGuidePage', () => {
  it('renders the Smart Maintenance Guide screen adapter', () => {
    render(<MaintenanceGuidePage />)

    expect(screen.getByTestId('guide-screen')).toBeDefined()
  })
})
