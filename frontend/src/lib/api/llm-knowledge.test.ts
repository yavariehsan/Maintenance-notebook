import { describe, it, expect, vi, beforeEach } from 'vitest'

import apiClient from '@/lib/api/client'
import { llmKnowledgeApi } from './llm-knowledge'

vi.mock('@/lib/api/client', () => ({
  default: {
    get: vi.fn(),
    post: vi.fn(),
    put: vi.fn(),
    patch: vi.fn(),
    delete: vi.fn(),
  },
}))

const getMock = vi.mocked(apiClient.get)
const postMock = vi.mocked(apiClient.post)

describe('llmKnowledgeApi guide path', () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it('opens the guide with GET only and never triggers generation', async () => {
    getMock.mockResolvedValue({ data: null })
    await llmKnowledgeApi.listBuilds()
    await llmKnowledgeApi.listRecords('llm_knowledge_build:12', 'repair_report:aaa')
    await llmKnowledgeApi.getGuide('llm_knowledge_build:12', 'repair_report:aaa')

    expect(getMock.mock.calls.map((call) => call[0])).toEqual([
      '/repair-reports/llm-builds',
      '/repair-reports/llm-builds/llm_knowledge_build%3A12/records',
      '/troubleshooting/llm/guide',
    ])
    // Opening/selecting the guide must not trigger a new generation POST.
    expect(postMock).not.toHaveBeenCalled()
  })

  it('starts generation only through the explicit builds POST', async () => {
    postMock.mockResolvedValue({ data: { build: { id: 'llm_knowledge_build:12' } } })
    await llmKnowledgeApi.startBuild(['repair_report:aaa'])
    expect(postMock).toHaveBeenCalledWith('/repair-reports/llm-builds', {
      report_ids: ['repair_report:aaa'],
    })
  })
})
