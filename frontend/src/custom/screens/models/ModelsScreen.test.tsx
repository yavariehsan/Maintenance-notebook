import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { ModelsScreen } from './ModelsScreen'
import { useProviders } from '@/lib/hooks/use-providers'
import { useCredentials, useCredentialStatus, useEnvStatus } from '@/lib/hooks/use-credentials'
import { useModels, useModelDefaults } from '@/lib/hooks/use-models'
import type { ProviderInfo } from '@/lib/api/providers'
import type { Credential } from '@/lib/api/credentials'

vi.mock('@/components/layout/AppShell', () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))

vi.mock('@/components/settings', () => ({
  MigrationBanner: ({ providersToMigrate }: { providersToMigrate: string[] }) =>
    providersToMigrate.length > 0 ? <div data-testid="migration-banner" /> : null,
  DefaultModelSelectors: () => <div data-testid="default-selectors" />,
  ProviderSection: ({ provider }: { provider: ProviderInfo }) => (
    <div data-testid="provider-section">{provider.display_name}</div>
  ),
}))

vi.mock('@/lib/hooks/use-models', () => ({
  useModels: vi.fn(),
  useModelDefaults: vi.fn(),
}))

vi.mock('@/lib/hooks/use-credentials', () => ({
  useCredentials: vi.fn(),
  useCredentialStatus: vi.fn(),
  useEnvStatus: vi.fn(),
}))

vi.mock('@/lib/hooks/use-providers', () => ({
  useProviders: vi.fn(),
}))

const mockUseModels = vi.mocked(useModels)
const mockUseModelDefaults = vi.mocked(useModelDefaults)
const mockUseCredentials = vi.mocked(useCredentials)
const mockUseCredentialStatus = vi.mocked(useCredentialStatus)
const mockUseEnvStatus = vi.mocked(useEnvStatus)
const mockUseProviders = vi.mocked(useProviders)

const providers: ProviderInfo[] = [
  { name: 'openai', display_name: 'OpenAI', modalities: ['language'], docs_url: null, env_configured: false },
  { name: 'anthropic', display_name: 'Anthropic', modalities: ['language'], docs_url: null, env_configured: false },
]

const credential = {
  id: 'credential:1',
  name: 'Anthropic Prod',
  provider: 'anthropic',
  modalities: ['language'],
  has_api_key: true,
  created: '2026-01-01T00:00:00Z',
  updated: '2026-01-01T00:00:00Z',
  model_count: 0,
} as Credential

function mockAll(overrides = {}) {
  const base = {
    credentials: { data: [credential], isLoading: false },
    models: { data: [], isLoading: false },
    defaults: { data: null, isLoading: false },
    credentialStatus: { data: { configured: {}, source: {}, encryption_configured: true } },
    envStatus: { data: {} },
    providers: { data: providers, isLoading: false, isError: false },
    ...overrides,
  }
  mockUseCredentials.mockReturnValue(base.credentials as never)
  mockUseModels.mockReturnValue(base.models as never)
  mockUseModelDefaults.mockReturnValue(base.defaults as never)
  mockUseCredentialStatus.mockReturnValue(base.credentialStatus as never)
  mockUseEnvStatus.mockReturnValue(base.envStatus as never)
  mockUseProviders.mockReturnValue(base.providers as never)
}

describe('ModelsScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockAll()
  })

  it('shows a loading state while provider data loads', () => {
    mockAll({ providers: { data: undefined, isLoading: true, isError: false } })
    const { container } = render(<ModelsScreen />)

    expect(container.querySelector('.animate-spin')).not.toBeNull()
  })

  it('warns when encryption is not configured', () => {
    mockAll({
      credentialStatus: { data: { configured: {}, source: {}, encryption_configured: false } },
    })
    render(<ModelsScreen />)

    expect(screen.getByText('apiKeys.encryptionRequired')).toBeDefined()
  })

  it('shows an error state when providers fail to load', () => {
    mockAll({ providers: { data: undefined, isLoading: false, isError: true } })
    render(<ModelsScreen />)

    expect(screen.getByText('apiKeys.providersLoadFailed')).toBeDefined()
  })

  it('renders configured providers first with selectors and help', () => {
    mockAll({
      models: { data: [], isLoading: false },
      defaults: { data: { default_chat_model: 'm' }, isLoading: false },
    })
    render(<ModelsScreen />)

    const sections = screen.getAllByTestId('provider-section')
    expect(sections.map((el) => el.textContent)).toEqual(['Anthropic', 'OpenAI'])
    expect(screen.getByTestId('default-selectors')).toBeDefined()
    expect(screen.getByText('apiKeys.learnMore')).toBeDefined()
  })
})
