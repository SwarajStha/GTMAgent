<script setup lang="ts">
import { ref } from 'vue'
import { useAgentStore } from '@/stores/agent'

const agentStore = useAgentStore()
const goal = ref('Find the top 3 suppliers for tender 16 and explain why.')
const dryRun = ref(true)
const act = ref(true)
const replyText = ref('')
const command = ref('')

async function submitCommand() {
  const text = command.value.trim()
  if (!text) return
  command.value = ''
  await agentStore.runCommand(text)
}

function pretty(value: unknown) {
  return JSON.stringify(value, null, 2)
}

function medal(index: number) {
  return ['🥇', '🥈', '🥉'][index] ?? `#${index + 1}`
}

async function run() {
  try {
    await agentStore.runAgent(goal.value, dryRun.value)
  } catch {
    /* error surfaced via agentStore.runError; sample run shown as fallback */
  }
}

async function pick(reply: string) {
  if (!reply) return
  replyText.value = ''
  try {
    await agentStore.continueAgent(reply)
  } catch {
    /* error surfaced via agentStore.runError */
  }
}

async function reflect() {
  try {
    await agentStore.runReflection(act.value)
  } catch {
    /* error surfaced via agentStore.reflectError; sample shown as fallback */
  }
}
</script>

<template>
  <div class="grid min-w-0 gap-5 xl:grid-cols-[420px_1fr]">
    <section class="min-w-0 space-y-4">
      <div class="surface p-4">
        <p class="section-kicker">Agent</p>
        <h2 class="mt-1 section-title">Plan &amp; execute a goal</h2>
        <p class="mt-2 text-xs font-semibold leading-5 text-slate-500">
          The agent resolves the tender locally, runs the matching pipeline, and explains the
          result. Live runs need a server <code>ANTHROPIC_API_KEY</code>.
        </p>
        <textarea
          v-model="goal"
          class="field mt-4 h-28 w-full resize-none py-2 leading-6"
          placeholder="Describe a goal for the agent"
        />
        <label class="mt-3 flex items-center gap-2 text-xs font-bold text-slate-600">
          <input v-model="dryRun" type="checkbox">
          Offline mode — only use already-ingested data (no live TED fetch)
        </label>
        <p class="mt-1 text-xs font-semibold leading-5 text-slate-400">
          Uncheck to let the agent fetch from live TED only if the tender or supplier pool is
          missing. Matching still runs either way.
        </p>
        <button class="btn-primary mt-4 w-full" type="button" :disabled="agentStore.runLoading" @click="run">
          {{ agentStore.runLoading ? 'Running…' : 'Run agent' }}
        </button>
        <p v-if="agentStore.runError" class="mt-3 text-xs font-bold text-amber-600">
          {{ agentStore.runError }} — showing a sample run below.
        </p>
      </div>

      <div class="surface p-4">
        <p class="section-kicker">Reflection</p>
        <h3 class="mt-1 text-sm font-black text-slate-950">Self-improvement cycle</h3>
        <p class="mt-2 text-xs font-semibold leading-5 text-slate-500">
          Computes metrics and (when enabled) retrains the matching LR from accumulated feedback.
          No API key required.
        </p>
        <label class="mt-3 flex items-center gap-2 text-xs font-bold text-slate-600">
          <input v-model="act" type="checkbox">
          Act (retrain from feedback when there is enough)
        </label>
        <button
          class="btn-secondary mt-4 w-full"
          type="button"
          :disabled="agentStore.reflectLoading"
          @click="reflect"
        >
          {{ agentStore.reflectLoading ? 'Reflecting…' : 'Run reflection cycle' }}
        </button>
        <p v-if="agentStore.reflectError" class="mt-3 text-xs font-bold text-amber-600">
          {{ agentStore.reflectError }} — showing sample output.
        </p>
      </div>

      <!-- Ops command console (G27): run operator actions without touching env/code. -->
      <div class="surface p-4">
        <p class="section-kicker">Ops console</p>
        <h3 class="mt-1 text-sm font-black text-slate-950">Command palette</h3>
        <p class="mt-2 text-xs font-semibold leading-5 text-slate-500">
          Slash-commands for operator actions.
          <code>/retrain</code>, <code>/reflect</code>, <code>/schedule on|off|status</code>,
          <code>/help</code>.
        </p>
        <div class="mt-3 flex gap-2">
          <input
            v-model="command"
            class="field w-full py-2 font-mono"
            placeholder="/help"
            :disabled="agentStore.commandRunning"
            @keyup.enter="submitCommand"
          >
          <button
            class="btn-secondary shrink-0"
            type="button"
            :disabled="agentStore.commandRunning || !command.trim()"
            @click="submitCommand"
          >
            {{ agentStore.commandRunning ? '…' : 'Run' }}
          </button>
        </div>
        <p class="mt-2 text-xs font-semibold leading-5 text-amber-600">
          <code>/schedule on</code> starts live TED polling (per worker, not persistent).
        </p>
        <ul v-if="agentStore.commandLog.length" class="mt-3 space-y-2">
          <li
            v-for="(entry, index) in agentStore.commandLog"
            :key="index"
            class="rounded border p-2.5 text-xs"
            :class="entry.ok ? 'border-slate-200 bg-slate-50' : 'border-amber-200 bg-amber-50'"
          >
            <p class="font-mono font-bold text-slate-700">{{ entry.command }}</p>
            <pre class="mt-1 whitespace-pre-wrap font-semibold" :class="entry.ok ? 'text-slate-600' : 'text-amber-700'">{{ entry.result }}</pre>
          </li>
        </ul>
      </div>
    </section>

    <section class="min-w-0 space-y-5">
      <!-- Live activity log (streamed status lines). -->
      <article v-if="agentStore.activity.length" class="surface p-5">
        <p class="section-kicker">Activity</p>
        <ul class="mt-3 space-y-1.5">
          <li
            v-for="(line, index) in agentStore.activity"
            :key="index"
            class="flex items-start gap-2 text-sm font-semibold leading-6 text-slate-600"
          >
            <span class="mt-1 h-1.5 w-1.5 shrink-0 rounded-full bg-slate-300" />
            {{ line }}
          </li>
          <li
            v-if="agentStore.runLoading"
            class="flex items-center gap-2 text-sm font-bold text-slate-400"
          >
            <span class="h-1.5 w-1.5 shrink-0 animate-pulse rounded-full bg-indigo-400" />
            working…
          </li>
        </ul>
      </article>

      <!-- Disambiguation picker (agent paused on ask_user). -->
      <article v-if="agentStore.awaiting" class="surface border-indigo-200 p-5">
        <p class="section-kicker text-indigo-500">Needs your input</p>
        <p class="mt-2 text-sm font-bold leading-6 text-slate-800">
          {{ agentStore.awaiting.question }}
        </p>
        <div class="mt-3 flex flex-col gap-2">
          <button
            v-for="(option, index) in agentStore.awaiting.options"
            :key="index"
            type="button"
            class="rounded border border-slate-200 bg-slate-50 px-3 py-2 text-left text-sm font-semibold text-slate-700 hover:border-indigo-300 hover:bg-indigo-50"
            :disabled="agentStore.runLoading"
            @click="pick(String(option.id ?? option.label ?? ''))"
          >
            {{ option.label ?? option.id }}
          </button>
        </div>
        <div class="mt-3 flex gap-2">
          <input
            v-model="replyText"
            class="field w-full py-2"
            placeholder="…or type an answer"
            @keyup.enter="pick(replyText)"
          >
          <button
            class="btn-secondary shrink-0"
            type="button"
            :disabled="agentStore.runLoading || !replyText"
            @click="pick(replyText)"
          >
            Send
          </button>
        </div>
      </article>

      <article v-if="agentStore.run" class="surface p-5">
        <div class="flex items-center justify-between gap-3">
          <p class="section-kicker">Agent run</p>
          <span v-if="agentStore.run.truncated" class="badge bg-amber-50 text-amber-700">truncated</span>
        </div>
        <p class="mt-2 text-sm font-semibold leading-6 text-slate-700">{{ agentStore.run.goal }}</p>

        <p class="mt-5 text-xs font-black uppercase tracking-[0.14em] text-slate-400">Steps</p>
        <ol class="mt-3 space-y-2">
          <li
            v-for="(step, index) in agentStore.run.steps"
            :key="index"
            class="rounded border border-slate-200 bg-slate-50 p-3"
          >
            <p class="text-sm font-black text-slate-950">{{ index + 1 }}. {{ step.tool }}</p>
            <pre class="mt-1 overflow-x-auto text-xs font-semibold text-slate-600">{{ pretty(step.args) }}</pre>
          </li>
          <li v-if="agentStore.run.steps.length === 0" class="text-sm font-semibold text-slate-500">
            No tool calls were made.
          </li>
        </ol>

        <p v-if="agentStore.run.output" class="mt-5 text-xs font-black uppercase tracking-[0.14em] text-slate-400">Output</p>
        <p v-if="agentStore.run.output" class="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-700">{{ agentStore.run.output }}</p>

        <!-- Post-run actions: save the analysis + draft an email to a chosen match. -->
        <div
          v-if="agentStore.resultTenderId && agentStore.run.output"
          class="mt-6 border-t border-slate-200 pt-5"
        >
          <p class="text-xs font-black uppercase tracking-[0.14em] text-slate-400">Actions</p>

          <div class="mt-3 flex flex-wrap items-center gap-3">
            <button
              class="btn-secondary"
              type="button"
              :disabled="agentStore.reportSaving || agentStore.reportSaved"
              @click="agentStore.saveReport()"
            >
              {{ agentStore.reportSaved ? 'Results saved ✓' : agentStore.reportSaving ? 'Saving…' : 'Save results' }}
            </button>
            <span v-if="agentStore.reportSaved" class="text-xs font-semibold text-slate-500">
              Saved to this tender's history.
            </span>
          </div>

          <div v-if="agentStore.topMatches.length" class="mt-4">
            <p class="text-sm font-black text-slate-700">Draft outreach email to:</p>
            <div class="mt-2 flex flex-wrap gap-2">
              <button
                v-for="(m, i) in agentStore.topMatches"
                :key="m.matchId"
                type="button"
                class="rounded border border-slate-200 bg-slate-50 px-3 py-2 text-sm font-semibold text-slate-700 hover:border-indigo-300 hover:bg-indigo-50 disabled:opacity-50"
                :disabled="!!agentStore.emailDraftingId"
                @click="agentStore.draftEmail(m.matchId, m.companyName)"
              >
                {{ medal(i) }} {{ m.companyName }}
                <span v-if="agentStore.emailDraftingId === m.matchId"> — drafting…</span>
              </button>
            </div>
            <p v-if="agentStore.emailDraftedFor" class="mt-3 text-xs font-bold text-emerald-600">
              Email written with {{ agentStore.emailDraftedFor.company }} —
              <router-link to="/emails" class="underline">view in Emails</router-link>
            </p>
          </div>

          <p v-if="agentStore.actionError" class="mt-3 text-xs font-bold text-amber-600">
            {{ agentStore.actionError }}
          </p>
        </div>
      </article>

      <article v-if="agentStore.reflection" class="surface p-5">
        <p class="section-kicker">Reflection result</p>
        <p class="mt-3 whitespace-pre-wrap text-sm leading-6 text-slate-700">{{ agentStore.reflection.narrative }}</p>
        <div class="mt-4 grid gap-4 md:grid-cols-2">
          <div class="rounded bg-slate-50 p-3">
            <p class="text-xs font-black uppercase tracking-[0.14em] text-slate-400">Metrics</p>
            <pre class="mt-2 overflow-x-auto text-xs font-semibold text-slate-600">{{ pretty(agentStore.reflection.metrics) }}</pre>
          </div>
          <div class="rounded bg-slate-50 p-3">
            <p class="text-xs font-black uppercase tracking-[0.14em] text-slate-400">Actions</p>
            <pre class="mt-2 overflow-x-auto text-xs font-semibold text-slate-600">{{ pretty(agentStore.reflection.actions) }}</pre>
          </div>
        </div>
      </article>

      <article
        v-if="!agentStore.run && !agentStore.reflection && !agentStore.activity.length"
        class="surface p-8 text-center"
      >
        <p class="text-sm font-semibold text-slate-500">
          Run the agent or a reflection cycle to see results here.
        </p>
      </article>
    </section>
  </div>
</template>
