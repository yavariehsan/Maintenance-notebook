import { useQuery } from '@tanstack/react-query'
import { troubleshootingApi } from '@/lib/api/troubleshooting'
import { QUERY_KEYS } from '@/lib/api/query-client'

/**
 * Read-only TanStack Query hooks for the troubleshooting runtime API.
 *
 * Hierarchy (no preloading, no polling — data is precomputed and static):
 * status → equipment → failure modes → selected guide → causes/evidence.
 * Dependent queries stay disabled until their identifiers exist. There are
 * intentionally no mutation hooks: troubleshooting knowledge is read-only.
 */

export function useTroubleshootingStatus() {
  return useQuery({
    queryKey: QUERY_KEYS.troubleshootingStatus,
    queryFn: () => troubleshootingApi.getStatus(),
  })
}

export function useTroubleshootingEquipment() {
  return useQuery({
    queryKey: QUERY_KEYS.troubleshootingEquipment,
    queryFn: () => troubleshootingApi.listEquipment(),
  })
}

export function useTroubleshootingEquipmentDetail(code: string | null) {
  return useQuery({
    queryKey: QUERY_KEYS.troubleshootingEquipmentDetail(code ?? ''),
    queryFn: () => troubleshootingApi.getEquipment(code as string),
    enabled: !!code,
  })
}

export function useTroubleshootingFailureModes(code: string | null) {
  return useQuery({
    queryKey: QUERY_KEYS.troubleshootingFailureModes(code ?? ''),
    queryFn: () => troubleshootingApi.listFailureModes(code as string),
    enabled: !!code,
  })
}

export function useTroubleshootingGuide(
  code: string | null,
  modeId: string | null,
) {
  return useQuery({
    queryKey: QUERY_KEYS.troubleshootingGuide(code ?? '', modeId ?? ''),
    queryFn: () => troubleshootingApi.getGuide(code as string, modeId as string),
    enabled: !!code && !!modeId,
  })
}

export function useTroubleshootingCauses(
  code: string | null,
  modeId: string | null,
) {
  return useQuery({
    queryKey: QUERY_KEYS.troubleshootingCauses(code ?? '', modeId ?? ''),
    queryFn: () => troubleshootingApi.listCauses(code as string, modeId as string),
    enabled: !!code && !!modeId,
  })
}

export function useTroubleshootingEvidence(
  code: string | null,
  modeId: string | null,
) {
  return useQuery({
    queryKey: QUERY_KEYS.troubleshootingEvidence(code ?? '', modeId ?? ''),
    queryFn: () => troubleshootingApi.listEvidence(code as string, modeId as string),
    enabled: !!code && !!modeId,
  })
}
