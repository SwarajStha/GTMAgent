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

// One line in the ops command console (G27).
export interface CommandLogEntry {
  command: string
  result: string
  ok: boolean
}

const COMMAND_HELP = [
  '/retrain [n]        retrain the matching model from feedback (min n samples, default 10)',
  '/reflect [observe]  run a reflection cycle (add "observe" to skip the retrain)',
  '/schedule on|off|status   toggle the in-process ingestion scheduler',
  '/help               show this list',
].join('\n')

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
    // ── ops command console (G27) ────────────────────────────────────────────
    commandLog: [] as CommandLogEntry[],
    commandRunning: false,
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
    // Parse and run a slash-command from the ops console (G27). Maps each command
    // to an existing endpoint and appends a one-line result to `commandLog`.
    async runCommand(raw: string) {
      const text = raw.trim()
      if (!text) return
      const [cmd, ...args] = text.split(/\s+/)
      const push = (result: string, ok: boolean) =>
        this.commandLog.unshift({ command: text, result, ok })

      if (cmd === '/help') {
        push(COMMAND_HELP, true)
        return
      }

      this.commandRunning = true
      try {
        if (cmd === '/retrain') {
          const n = Number.parseInt(args[0] ?? '', 10)
          const minSamples = Number.isFinite(n) && n >= 2 ? n : 10
          const body = await this._postJson(
            `/api/v1/feedback/retrain?min_samples=${minSamples}`,
          )
          if (body.status === 'retrained') {
            push(
              `Model retrained on ${body.n_samples} feedback samples ` +
                `(${body.n_pos}👍 / ${body.n_neg}👎). Now serving the feedback-tuned weights.`,
              true,
            )
          } else {
            push(
              `Not enough feedback yet: ${body.n_samples}/${body.min_required} samples ` +
                `(${body.n_pos}👍 / ${body.n_neg}👎). Base model still serving.`,
              true,
            )
          }
        } else if (cmd === '/reflect') {
          const act = !(args[0] === 'observe' || args[0] === '--observe' || args[0] === '--no-act')
          const body = await this._postJson(`/api/v1/agent/reflect?act=${act}`)
          this.reflection = body as unknown as ReflectionResult
          push(
            `Reflection cycle complete${act ? ' (retrain actuated)' : ' (observe only)'}. ` +
              `See the reflection result below.`,
            true,
          )
        } else if (cmd === '/schedule') {
          const sub = (args[0] ?? 'status').toLowerCase()
          const action = sub === 'on' ? 'start' : sub === 'off' ? 'stop' : 'status'
          if (!['on', 'off', 'status'].includes(sub)) {
            push(`Usage: /schedule on|off|status`, false)
            return
          }
          const body = await this._postJson('/api/v1/agent/scheduler', { action })
          const jobs = Array.isArray(body.jobs) ? body.jobs.length : 0
          push(`${body.message} (${body.running ? `${jobs} jobs scheduled` : 'stopped'})`, true)
        } else {
          push(`Unknown command "${cmd}". Type /help for the list.`, false)
        }
      } catch (error) {
        push(error instanceof Error ? error.message : 'Command failed', false)
      } finally {
        this.commandRunning = false
      }
    },
    async _postJson(url: string, body?: Record<string, unknown>) {
      const response = await fetch(url, {
        method: 'POST',
        headers: body ? { 'Content-Type': 'application/json' } : {},
        body: body ? JSON.stringify(body) : undefined,
      })
      const data = await response.json().catch(() => null)
      if (!response.ok) {
        throw new Error(data?.detail ?? `Request failed (${response.status})`)
      }
      return data as Record<string, unknown> & {
        status?: string
        n_samples?: number
        n_pos?: number
        n_neg?: number
        min_required?: number
        message?: string
        running?: boolean
        jobs?: unknown[]
      }
    },
  },
})
