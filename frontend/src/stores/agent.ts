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

export interface TopMatch {
  matchId: string
  companyName: string
  finalScore: number
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
    // ── post-run actions (Save results / Draft email) ───────────────────────
    // The tender the completed run matched, + its top-N matches (for the email
    // selector). Populated after a run reaches `final`.
    resultTenderId: null as number | null,
    topMatches: [] as TopMatch[],
    reportSaving: false,
    reportSaved: false,
    emailDraftingId: null as string | null,
    emailDraftedFor: null as { company: string; emailId: string } | null,
    actionError: null as string | null,
  }),
  actions: {
    async runAgent(goal: string, dryRun = true) {
      this.runLoading = true
      this.runError = null
      this.run = null
      this.activity = []
      this.awaiting = null
      this.sessionId = null
      this._resetActions()
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
        await this._loadResultActions()
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
        await this._loadResultActions()
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
    _resetActions() {
      this.resultTenderId = null
      this.topMatches = []
      this.reportSaving = false
      this.reportSaved = false
      this.emailDraftingId = null
      this.emailDraftedFor = null
      this.actionError = null
    },
    // The tender the run matched, derived from its find_matches step.
    _deriveTenderId(): number | null {
      const step = this.run?.steps.find((s) => s.tool === 'find_matches')
      const id = step?.args?.tender_id
      return typeof id === 'number' ? id : null
    },
    // After a completed run, load the tender's top-3 matches so the user can
    // pick which one to email (Save results / Draft email actions).
    async _loadResultActions() {
      if (this.awaiting) return // paused — no matches yet
      const tenderId = this._deriveTenderId()
      this.resultTenderId = tenderId
      if (tenderId == null) return
      try {
        const params = new URLSearchParams({ tender_id: String(tenderId), limit: '3' })
        const response = await fetch(`/api/v1/matches/?${params.toString()}`)
        if (!response.ok) return
        const body = (await response.json()) as {
          items: { id: string; final_score: number; company: { name: string } }[]
        }
        this.topMatches = body.items.map((m) => ({
          matchId: m.id,
          companyName: m.company.name,
          finalScore: m.final_score,
        }))
      } catch {
        /* non-fatal — actions just won't show */
      }
    },
    async saveReport() {
      const tenderId = this.resultTenderId
      if (tenderId == null || !this.run) return
      this.reportSaving = true
      this.actionError = null
      try {
        const response = await fetch(`/api/v1/tenders/${tenderId}/reports`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            narrative: this.run.output,
            goal: this.run.goal,
            session_id: this.sessionId,
          }),
        })
        if (!response.ok) {
          throw new Error(`Save returned ${response.status}`)
        }
        this.reportSaved = true
      } catch (error) {
        this.actionError = error instanceof Error ? error.message : 'Could not save results'
      } finally {
        this.reportSaving = false
      }
    },
    async draftEmail(matchId: string, companyName: string) {
      this.emailDraftingId = matchId
      this.actionError = null
      try {
        const response = await fetch(`/api/v1/emails/${matchId}/generate`, { method: 'POST' })
        if (!response.ok) {
          throw new Error(`Email API returned ${response.status}`)
        }
        const body = (await response.json()) as { id: string }
        this.emailDraftedFor = { company: companyName, emailId: body.id }
      } catch (error) {
        this.actionError = error instanceof Error ? error.message : 'Could not draft email'
      } finally {
        this.emailDraftingId = null
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
