import { render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { PodcastsScreen } from './PodcastsScreen'
import { useEpisodeProfiles, useSpeakerProfiles } from '@/lib/hooks/use-podcasts'

vi.mock('@/components/layout/AppShell', () => ({
  AppShell: ({ children }: { children: React.ReactNode }) => <div>{children}</div>,
}))

vi.mock('@/components/podcasts/EpisodesTab', () => ({
  EpisodesTab: () => <div data-testid="episodes-tab" />,
}))

vi.mock('@/components/podcasts/TemplatesTab', () => ({
  TemplatesTab: () => <div data-testid="templates-tab" />,
}))

vi.mock('@/lib/hooks/use-podcasts', () => ({
  useEpisodeProfiles: vi.fn(),
  useSpeakerProfiles: vi.fn(),
}))

const mockUseEpisodeProfiles = vi.mocked(useEpisodeProfiles)
const mockUseSpeakerProfiles = vi.mocked(useSpeakerProfiles)

const configuredEpisode = { id: 'ep:1', outline_llm: 'm', transcript_llm: 'm' }
const configuredSpeaker = { id: 'sp:1', voice_model: 'v' }

function mockProfiles(episodeProfiles = [configuredEpisode], speakerProfiles = [configuredSpeaker]) {
  mockUseEpisodeProfiles.mockReturnValue({ episodeProfiles } as never)
  mockUseSpeakerProfiles.mockReturnValue({ speakerProfiles } as never)
}

describe('PodcastsScreen', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockProfiles()
  })

  it('renders the header and episodes view by default', () => {
    const { container } = render(<PodcastsScreen />)

    expect(screen.getByText('podcasts.listTitle')).toBeDefined()
    expect(screen.getByTestId('episodes-tab')).toBeDefined()
    expect(container.innerHTML).toContain('custom-page')
  })

  it('warns when profiles need model setup', () => {
    mockProfiles([{ id: 'ep:1' } as never], [configuredSpeaker])
    render(<PodcastsScreen />)

    expect(screen.getByText('podcasts.setupRequired')).toBeDefined()
  })

  it('stays quiet when all profiles are configured', () => {
    render(<PodcastsScreen />)

    expect(screen.queryByText('podcasts.setupRequired')).toBeNull()
  })

  it('exposes both episode and template views', () => {
    render(<PodcastsScreen />)

    expect(screen.getByRole('tab', { name: 'podcasts.episodesTab' })).toBeDefined()
    expect(screen.getByRole('tab', { name: 'podcasts.templatesTab' })).toBeDefined()
  })

  it('selects the episodes view by default', () => {
    render(<PodcastsScreen />)

    // Radix tab activation is not drivable in jsdom (no browser runner);
    // assert the controlled default selection instead.
    expect(
      screen.getByRole('tab', { name: 'podcasts.episodesTab' }).getAttribute('aria-selected')
    ).toBe('true')
    expect(
      screen.getByRole('tab', { name: 'podcasts.templatesTab' }).getAttribute('aria-selected')
    ).toBe('false')
  })
})
