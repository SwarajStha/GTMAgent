import { defineStore } from 'pinia'
import {
  agentRunSample,
  reflectionSample,
  type AgentRunResult,
  type ReflectionResult,
} from './sampleData'

interface ApiAgentStep {
  tool: string
  args: Record<string, unknown>
}

interface ApiAgentResponse {
  goal: string
  steps: ApiAgentStep[]
  output: string
  truncated: boolean
}

interface ApiReflectResponse {
  id: string
  metrics: Record<string, unknown>
  actions: Record<string, unknown>
  narrative: string
}

export const useAgentStore = defineStore('agent', {
  state: () => ({
    run: null as AgentRunResult | null,
    reflection: null as ReflectionResult | null,
    runLoading: false,
    reflectLoading: false,
    runError: null as string | null,
    reflectError: null as string | null,
    source: 'api' as 'api' | 'sample',
  }),
  actions: {
    async runAgent(goal: string, dryRun = true) {
      this.runLoading = true
      this.runError = null
      try {
        const response = await fetch('/api/v1/agent/run', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ goal, dry_run: dryRun }),
        })
        if (!response.ok) {
          const detail = await response.json().catch(() => null)
          throw new Error(detail?.detail ?? `Agent API returned ${response.status}`)
        }
        const body = (await response.json()) as ApiAgentResponse
        this.run = body
        this.source = 'api'
        return body
      } catch (error) {
        this.runError = error instanceof Error ? error.message : 'Agent run failed'
        this.run = { ...agentRunSample, goal }
        this.source = 'sample'
        throw error
      } finally {
        this.runLoading = false
      }
    },
    async runReflection(act = true) {
      this.reflectLoading = true
      this.reflectError = null
      try {
        const response = await fetch(`/api/v1/agent/reflect?act=${act}`, { method: 'POST' })
        if (!response.ok) {
          throw new Error(`Reflection API returned ${response.status}`)
        }
        const body = (await response.json()) as ApiReflectResponse
        this.reflection = body
        return body
      } catch (error) {
        this.reflectError = error instanceof Error ? error.message : 'Reflection failed'
        this.reflection = reflectionSample
        throw error
      } finally {
        this.reflectLoading = false
      }
    },
  },
})
