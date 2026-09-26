import { QueryClient } from '@tanstack/react-query'
import { isNotFoundError } from '@/lib/utils/error-handler'

export const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 5 * 60 * 1000, // 5 minutes
      gcTime: 10 * 60 * 1000, // 10 minutes
      // Retry transient failures, but never retry 404s: the item was
      // deleted (or never existed) and retrying cannot change that.
      retry: (failureCount, error) => !isNotFoundError(error) && failureCount < 2,
      refetchOnWindowFocus: false,
    },
    mutations: {
      retry: 1,
    },
  },
})

export const QUERY_KEYS = {
  notebooks: ['notebooks'] as const,
  notebook: (id: string) => ['notebooks', id] as const,
  assets: ['assets'] as const,
  asset: (id: string) => ['assets', id] as const,
  maintenanceSources: (code: string) =>
    ['maintenance', 'sources', code] as const,
  notes: (notebookId?: string) => ['notes', notebookId] as const,
  note: (id: string) => ['notes', id] as const,
  sources: (notebookId?: string) => ['sources', notebookId] as const,
  sourcesInfinite: (notebookId: string) => ['sources', 'infinite', notebookId] as const,
  source: (id: string) => ['sources', id] as const,
  settings: ['settings'] as const,
  sourceChatSessions: (sourceId: string) => ['source-chat', sourceId, 'sessions'] as const,
  sourceChatSession: (sourceId: string, sessionId: string) => ['source-chat', sourceId, 'sessions', sessionId] as const,
  notebookChatSessions: (notebookId: string) => ['notebook-chat', notebookId, 'sessions'] as const,
  notebookChatSession: (sessionId: string) => ['notebook-chat', 'sessions', sessionId] as const,
  podcastEpisodes: ['podcasts', 'episodes'] as const,
  tasks: (limit?: number) => ['tasks', limit ?? 50] as const,
  podcastEpisode: (episodeId: string) => ['podcasts', 'episodes', episodeId] as const,
  episodeProfiles: ['podcasts', 'episode-profiles'] as const,
  speakerProfiles: ['podcasts', 'speaker-profiles'] as const,
  languages: ['languages'] as const,
  troubleshootingStatus: ['troubleshooting', 'status'] as const,
  troubleshootingEquipment: ['troubleshooting', 'equipment'] as const,
  troubleshootingEquipmentDetail: (code: string) =>
    ['troubleshooting', 'equipment', code] as const,
  troubleshootingFailureModes: (code: string) =>
    ['troubleshooting', 'equipment', code, 'failure-modes'] as const,
  troubleshootingGuide: (code: string, modeId: string) =>
    ['troubleshooting', 'equipment', code, 'failure-modes', modeId] as const,
  troubleshootingCauses: (code: string, modeId: string) =>
    ['troubleshooting', 'equipment', code, 'failure-modes', modeId, 'causes'] as const,
  troubleshootingEvidence: (code: string, modeId: string) =>
    ['troubleshooting', 'equipment', code, 'failure-modes', modeId, 'evidence'] as const,
  repairReports: ['repair-reports'] as const,
  repairReport: (id: string) => ['repair-reports', id] as const,
  repairReportPreview: (id: string) => ['repair-reports', id, 'preview'] as const,
  repairAnalysisRuns: ['repair-reports', 'runs'] as const,
  repairAnalysisRun: (id: string) => ['repair-reports', 'runs', id] as const,
}
