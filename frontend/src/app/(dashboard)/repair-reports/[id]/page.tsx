'use client'

import { useParams } from 'next/navigation'
import { RepairReportDetailScreen } from '@/custom/screens/repair-reports/RepairReportDetailScreen'

export default function RepairReportDetailPage() {
  const params = useParams()
  const reportId = params?.id ? decodeURIComponent(params.id as string) : ''
  return <RepairReportDetailScreen reportId={reportId} />
}
