import { render, screen, fireEvent } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { SettingsScreen } from './SettingsScreen'
import { useSettings } from '@/lib/hooks/use-settings'

vi.mock('@/components/layout/AppShell', () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))

vi.mock('@/app/(dashboard)/settings/components/SettingsForm', () => ({
  SettingsForm: () => <div data-testid="settings-form" />,
}))

vi.mock('@/lib/hooks/use-settings', () => ({
  useSettings: vi.fn(),
}))

const mockUseSettings = vi.mocked(useSettings)

describe('SettingsScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUseSettings.mockReturnValue({ refetch: vi.fn() } as never)
  })

  it('renders the settings header and form', () => {
    const { container } = render(<SettingsScreen />)

    expect(screen.getByText('navigation.settings')).toBeDefined()
    expect(screen.getByTestId('settings-form')).toBeDefined()
    expect(container.innerHTML).toContain('custom-page')
  })

  it('refreshes settings on demand', () => {
    const refetch = vi.fn()
    mockUseSettings.mockReturnValue({ refetch } as never)
    const { container } = render(<SettingsScreen />)

    const buttons = container.querySelectorAll('button')
    fireEvent.click(buttons[0])
    expect(refetch).toHaveBeenCalled()
  })
})
