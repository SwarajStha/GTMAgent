<script setup lang="ts">
import { ref } from 'vue'
import { useAgentStore } from '@/stores/agent'

const agentStore = useAgentStore()
const goal = ref('Find the top 3 suppliers for tender 16 and explain why.')
const dryRun = ref(true)
const act = ref(true)

function pretty(value: unknown) {
  return JSON.stringify(value, null, 2)
}

async function run() {
  try {
    await agentStore.runAgent(goal.value, dryRun.value)
  } catch {
    /* error surfaced via agentStore.runError; sample run shown as fallback */
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
          The planner-executor loop picks tools (ingest, match, draft, query) to satisfy a goal.
          Live runs need a server <code>ANTHROPIC_API_KEY</code>.
        </p>
        <textarea
          v-model="goal"
          class="field mt-4 h-28 w-full resize-none py-2 leading-6"
          placeholder="Describe a goal for the agent"
        />
        <label class="mt-3 flex items-center gap-2 text-xs font-bold text-slate-600">
          <input v-model="dryRun" type="checkbox">
          Dry run (validate write-tools without hitting live TED / the DB)
        </label>
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
    </section>

    <section class="min-w-0 space-y-5">
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

        <p class="mt-5 text-xs font-black uppercase tracking-[0.14em] text-slate-400">Output</p>
        <p class="mt-2 whitespace-pre-wrap text-sm leading-6 text-slate-700">{{ agentStore.run.output }}</p>
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

      <article v-if="!agentStore.run && !agentStore.reflection" class="surface p-8 text-center">
        <p class="text-sm font-semibold text-slate-500">
          Run the agent or a reflection cycle to see results here.
        </p>
      </article>
    </section>
  </div>
</template>
