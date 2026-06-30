import { defineStore } from 'pinia'
import {
  agentRunSample,
  reflectionSample,
  type AgentAwaiting,
  type AgentRunResult,
  type AgentStepItem,
  type ReflectionResult,
} from './sampleData'

interface ApiReflectResponse {
  id: string
  metrics: Record<string, unknown>
  actions: Record<string, unknown>
  narrative: string
}

// One Server-Sent Event from the agent stream.
interface AgentEvent {
  type: 'status' | 'step' | 'awaiting_input' | 'final' | 'error'
  message?: string
  session_id?: string
  tool?: string
  args?: Record<string, unknown>
  question?: string
  options?: { id?: string; label?: string }[]
  goal?: string
  steps?: AgentStepItem[]
  output?: string
  truncated?: boolean
}

export const useAgentStore = defineStore('agent', {
  state: () => ({
    run: null as AgentRunResult | null,
    reflection: null as ReflectionResult | null,
    // Live progress lines streamed from the backend (the "blooping…" updates).
    activity: [] as string[],
    // Set when the agent paused on ask_user and needs the user to pick.
    awaiting: null as AgentAwaiting | null,
    sessionId: null as string | null,
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
      this.run = null
      this.activity = []
      this.awaiting = null
      this.sessionId = null
      try {
        const response = await fetch('/api/v1/agent/run', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ goal, dry_run: dryRun }),
        })
        if (!response.ok || !response.body) {
          const detail = await response.json().catch(() => null)
          throw new Error(detail?.detail ?? `Agent API returned ${response.status}`)
        }
        await this._consumeStream(response.body, goal)
        this.source = 'api'
      } catch (error) {
        this.runError = error instanceof Error ? error.message : 'Agent run failed'
        this.run = { ...agentRunSample, goal }
        this.source = 'sample'
        throw error
      } finally {
        this.runLoading = false
      }
    },
    async continueAgent(reply: string) {
      if (!this.sessionId) return
      const goal = this.run?.goal ?? ''
      this.runLoading = true
      this.runError = null
      this.activity.push(`You: ${reply}`)
      this.awaiting = null
      try {
        const response = await fetch(`/api/v1/agent/run/${this.sessionId}/continue`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ reply }),
        })
        if (!response.ok || !response.body) {
          const detail = await response.json().catch(() => null)
          throw new Error(detail?.detail ?? `Agent API returned ${response.status}`)
        }
        await this._consumeStream(response.body, goal)
        this.source = 'api'
      } catch (error) {
        this.runError = error instanceof Error ? error.message : 'Agent continue failed'
        throw error
      } finally {
        this.runLoading = false
      }
    },
    // Reads the SSE body, splitting on the `\n\n` frame boundary, and applies
    // each `data:` event to the store as it arrives.
    async _consumeStream(body: ReadableStream<Uint8Array>, goal: string) {
      const reader = body.getReader()
      const decoder = new TextDecoder()
      const steps: AgentStepItem[] = [...(this.run?.steps ?? [])]
      let buffer = ''
      for (;;) {
        const { done, value } = await reader.read()
        if (done) break
        buffer += decoder.decode(value, { stream: true })
        const frames = buffer.split('\n\n')
        buffer = frames.pop() ?? ''
        for (const frame of frames) {
          const line = frame.split('\n').find((l) => l.startsWith('data:'))
          if (!line) continue
          let event: AgentEvent
          try {
            event = JSON.parse(line.slice(5).trim())
          } catch {
            continue
          }
          this._applyEvent(event, goal, steps)
        }
      }
    },
    _applyEvent(event: AgentEvent, goal: string, steps: AgentStepItem[]) {
      switch (event.type) {
        case 'status':
          if (event.message) this.activity.push(event.message)
          if (event.session_id) this.sessionId = event.session_id
          break
        case 'step':
          if (event.tool) {
            steps.push({ tool: event.tool, args: event.args ?? {} })
            this.run = {
              goal,
              steps: [...steps],
              output: this.run?.output ?? '',
              truncated: false,
            }
          }
          break
        case 'awaiting_input':
          this.sessionId = event.session_id ?? this.sessionId
          this.awaiting = {
            sessionId: event.session_id ?? this.sessionId ?? '',
            question: event.question ?? 'Which option do you want?',
            options: event.options ?? [],
          }
          break
        case 'final':
          this.run = {
            goal: event.goal ?? goal,
            steps: event.steps ?? steps,
            output: event.output ?? '',
            truncated: Boolean(event.truncated),
          }
          this.awaiting = null
          break
        case 'error':
          this.runError = event.message ?? 'Agent error'
          break
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
