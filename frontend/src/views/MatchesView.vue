<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from 'vue'
import { useEmailsStore } from '@/stores/emails'
import { useMatchesStore } from '@/stores/matches'
import type { MatchItem } from '@/stores/sampleData'
import { useTendersStore } from '@/stores/tenders'

const matchesStore = useMatchesStore()
const emailsStore = useEmailsStore()
const tendersStore = useTendersStore()
const selectedId = ref(matchesStore.items[0]?.id ?? '')
const statusFilter = ref('all')
// Restore the last-selected tender from the store so it survives navigation.
const tenderFilter = ref(matchesStore.selectedTenderId)
const actionMessage = ref('')
const weights = ref({
  semantic: 0.4,
  budget: 0.2,
  location: 0.2,
  qualification: 0.2,
})

// Centered tender picker (replaces the native <select>, which renders an
// unstylable full-height browser dropdown). Closes on selection / backdrop / Esc.
const tenderPickerOpen = ref(false)
const tenderSearch = ref('')

const selectedTenderLabel = computed(() => {
  if (tenderFilter.value === 'all') return 'All tenders'
  return tendersStore.items.find((t) => t.id === tenderFilter.value)?.title ?? 'All tenders'
})

const pickerTenders = computed(() => {
  const q = tenderSearch.value.trim().toLowerCase()
  if (!q) return tendersStore.items
  return tendersStore.items.filter((t) => t.title.toLowerCase().includes(q))
})

function closeTenderPicker() {
  tenderPickerOpen.value = false
  tenderSearch.value = ''
}

function pickTender(id: string) {
  tenderFilter.value = id
  closeTenderPicker()
}

function onPickerKeydown(event: KeyboardEvent) {
  if (event.key === 'Escape') closeTenderPicker()
}

onMounted(() => window.addEventListener('keydown', onPickerKeydown))
onUnmounted(() => window.removeEventListener('keydown', onPickerKeydown))

onMounted(async () => {
  // Reload the matches for the restored tender selection (a specific tender or
  // the global view), so returning to this screen shows what the operator was
  // last looking at rather than always snapping back to the global top-N.
  const params =
    tenderFilter.value === 'all'
      ? new URLSearchParams()
      : new URLSearchParams({ tender_id: tenderFilter.value })
  await Promise.all([matchesStore.fetchAll(params), tendersStore.fetchAll()])
  selectedId.value = filteredMatches.value[0]?.id ?? matchesStore.items[0]?.id ?? ''
})

const percent = new Intl.NumberFormat('en-US', {
  style: 'percent',
  maximumFractionDigits: 0,
})

const weightTotal = computed(
  () =>
    weights.value.semantic +
    weights.value.budget +
    weights.value.location +
    weights.value.qualification,
)

const selectedTenderFilter = computed(() =>
  tenderFilter.value === 'all'
    ? null
    : tendersStore.items.find((tender) => tender.id === tenderFilter.value),
)

function adjustedScore(match: MatchItem) {
  const total = weightTotal.value || 1
  return (
    match.semanticScore * weights.value.semantic +
    match.budgetScore * weights.value.budget +
    match.locationScore * weights.value.location +
    match.qualificationScore * weights.value.qualification
  ) / total
}

function scoreDelta(match: MatchItem) {
  return adjustedScore(match) - match.finalScore
}

const filteredMatches = computed(() =>
  matchesStore.items
    .filter(
      (match) =>
        (statusFilter.value === 'all' || match.status === statusFilter.value) &&
        (tenderFilter.value === 'all' || match.tenderId === tenderFilter.value),
    )
    .sort((a, b) => adjustedScore(b) - adjustedScore(a))
    .slice(0, tenderFilter.value === 'all' ? matchesStore.items.length : 5),
)

const selectedMatch = computed(
  () =>
    matchesStore.items.find((match) => match.id === selectedId.value) ??
    filteredMatches.value[0] ??
    matchesStore.items[0],
)

// Selecting a tender loads its own matches (existing or empty) rather than
// filtering whatever global slice happened to be loaded — keeps the list and the
// detail panel in sync with the chosen tender.
watch(tenderFilter, async (value) => {
  matchesStore.selectedTenderId = value
  const params =
    value === 'all' ? new URLSearchParams() : new URLSearchParams({ tender_id: value })
  await matchesStore.fetchAll(params)
  selectedId.value = filteredMatches.value[0]?.id ?? ''
})

const selectedTender = computed(() =>
  tendersStore.items.find((tender) => tender.id === selectedMatch.value?.tenderId),
)

const scoreBreakdown = computed(() => {
  if (!selectedMatch.value) return []
  return [
    { label: 'Semantic', value: selectedMatch.value.semanticScore },
    { label: 'Budget', value: selectedMatch.value.budgetScore },
    { label: 'Location', value: selectedMatch.value.locationScore },
    { label: 'Qualification', value: selectedMatch.value.qualificationScore },
  ]
})

function statusClasses(status: MatchItem['status']) {
  return {
    ready: 'bg-emerald-50 text-emerald-700',
    'needs-review': 'bg-amber-50 text-amber-700',
    blocked: 'bg-rose-50 text-rose-700',
  }[status]
}

function resetWeights() {
  weights.value = {
    semantic: 0.4,
    budget: 0.2,
    location: 0.2,
    qualification: 0.2,
  }
}

const emailDrafted = ref(false)

async function generateEmail() {
  if (!selectedMatch.value) return
  actionMessage.value = ''
  emailDrafted.value = false
  try {
    const draft = await emailsStore.generate(selectedMatch.value.id)
    actionMessage.value = `Draft generated: ${draft.subject}`
    emailDrafted.value = true
  } catch {
    actionMessage.value = emailsStore.error ?? 'Email generation failed'
  }
}

async function findMatches() {
  if (tenderFilter.value === 'all') return
  actionMessage.value = ''
  try {
    const mode = await matchesStore.runMatching(tenderFilter.value)
    selectedId.value = filteredMatches.value[0]?.id ?? ''
    actionMessage.value = filteredMatches.value.length
      ? `Matching complete (${mode === 'weighted' ? 'weighted' : 'trained model'}) — ranked suppliers updated`
      : 'Matching complete — no eligible suppliers passed the filters for this tender'
  } catch {
    actionMessage.value = matchesStore.error ?? 'Run matching failed'
  }
}

async function applyWeights() {
  // G16: persist the operator's slider weights — re-rank server-side in weighted
  // mode and reload, so the override is durable (not just a client-side preview).
  if (tenderFilter.value === 'all') return
  actionMessage.value = ''
  try {
    await matchesStore.runMatching(tenderFilter.value, undefined, { ...weights.value })
    selectedId.value = filteredMatches.value[0]?.id ?? ''
    actionMessage.value = 'Weights applied — tender re-ranked and saved'
  } catch {
    actionMessage.value = matchesStore.error ?? 'Apply weights failed'
  }
}

async function emailBuyer() {
  if (tenderFilter.value === 'all') return
  actionMessage.value = ''
  try {
    const draft = await emailsStore.generateBuyer(tenderFilter.value)
    actionMessage.value = `Buyer email drafted: ${draft.subject}`
  } catch {
    actionMessage.value = emailsStore.error ?? 'Buyer email failed'
  }
}

async function submitFeedback(rating: 1 | -1) {
  if (!selectedMatch.value) return
  actionMessage.value = ''
  try {
    await matchesStore.submitFeedback(
      selectedMatch.value.id,
      rating,
      rating === 1 ? 'Looks relevant from the match view' : 'Needs review from the match view',
    )
    actionMessage.value = rating === 1 ? 'Positive feedback saved' : 'Negative feedback saved'
  } catch {
    actionMessage.value = matchesStore.feedbackError ?? 'Feedback failed'
  }
}
</script>

<template>
  <div class="grid min-w-0 gap-5 xl:grid-cols-[430px_1fr]">
    <section class="min-w-0 space-y-4">
      <div class="surface p-4">
        <p class="section-kicker">Match scoring</p>
        <h2 class="mt-1 section-title">Rank companies by evidence fit</h2>
        <button
          type="button"
          class="field mt-4 flex w-full items-center justify-between gap-2 text-left"
          @click="tenderPickerOpen = true"
        >
          <span class="truncate">{{ selectedTenderLabel }}</span>
          <span class="shrink-0 text-slate-400">▾</span>
        </button>
        <select v-model="statusFilter" class="field mt-4 w-full">
          <option value="all">All matches</option>
          <option value="ready">Ready</option>
          <option value="needs-review">Needs review</option>
          <option value="blocked">Blocked</option>
        </select>
        <p class="mt-3 text-xs font-bold text-slate-500">
          {{ selectedTenderFilter ? 'Showing top 5 for selected tender' : 'Showing all ranked matches' }}
        </p>
        <div v-if="tenderFilter !== 'all'" class="mt-4 flex flex-wrap gap-2">
          <button
            class="btn-secondary h-8 px-3 text-xs"
            type="button"
            :disabled="matchesStore.loading"
            @click="findMatches"
          >
            {{ matchesStore.loading ? 'Matching...' : 'Find matches' }}
          </button>
          <button
            class="btn-secondary h-8 px-3 text-xs"
            type="button"
            :disabled="emailsStore.loading"
            @click="emailBuyer"
          >
            Email buyer (top suppliers)
          </button>
        </div>
      </div>

      <div class="surface p-4">
        <div class="flex items-center justify-between gap-3">
          <div>
            <p class="section-kicker">Weight sliders</p>
            <h3 class="mt-1 text-sm font-black text-slate-950">Live preview + saved re-rank</h3>
          </div>
          <button class="btn-secondary h-8 px-3 text-xs" type="button" @click="resetWeights">
            Reset
          </button>
        </div>
        <div class="mt-4 space-y-4">
          <label class="block">
            <span class="flex items-center justify-between text-xs font-black text-slate-600">
              <span>Semantic</span>
              <span>{{ Math.round(weights.semantic * 100) }}</span>
            </span>
            <input v-model.number="weights.semantic" class="mt-2 w-full" type="range" min="0" max="1" step="0.05">
          </label>
          <label class="block">
            <span class="flex items-center justify-between text-xs font-black text-slate-600">
              <span>Budget</span>
              <span>{{ Math.round(weights.budget * 100) }}</span>
            </span>
            <input v-model.number="weights.budget" class="mt-2 w-full" type="range" min="0" max="1" step="0.05">
          </label>
          <label class="block">
            <span class="flex items-center justify-between text-xs font-black text-slate-600">
              <span>Location</span>
              <span>{{ Math.round(weights.location * 100) }}</span>
            </span>
            <input v-model.number="weights.location" class="mt-2 w-full" type="range" min="0" max="1" step="0.05">
          </label>
          <label class="block">
            <span class="flex items-center justify-between text-xs font-black text-slate-600">
              <span>Qualification</span>
              <span>{{ Math.round(weights.qualification * 100) }}</span>
            </span>
            <input v-model.number="weights.qualification" class="mt-2 w-full" type="range" min="0" max="1" step="0.05">
          </label>
        </div>
        <div class="mt-4 border-t border-slate-100 pt-4">
          <button
            class="btn-primary h-9 w-full px-3 text-xs"
            type="button"
            :disabled="tenderFilter === 'all' || matchesStore.loading"
            @click="applyWeights"
          >
            {{ matchesStore.loading ? 'Re-ranking…' : 'Apply weights & re-rank (save)' }}
          </button>
          <p class="mt-2 text-xs font-semibold leading-5 text-slate-500">
            {{
              tenderFilter === 'all'
                ? 'Select a tender above to save weighted re-ranking. Sliders preview live for any view.'
                : 'Saves these weights and re-ranks this tender server-side (weighted mode). Re-run “Find matches” for the trained model.'
            }}
          </p>
        </div>
      </div>

      <div class="surface overflow-hidden">
        <button
          v-for="match in filteredMatches"
          :key="match.id"
          class="w-full border-b border-slate-100 p-4 text-left transition last:border-b-0 hover:bg-slate-50"
          :class="selectedMatch?.id === match.id ? 'bg-emerald-50/60' : 'bg-white'"
          type="button"
          @click="selectedId = match.id"
        >
          <div class="flex items-start justify-between gap-4">
            <div class="min-w-0">
              <p class="truncate text-sm font-black text-slate-950">{{ match.companyName }}</p>
              <p class="mt-1 text-xs font-semibold text-slate-500">
                {{ match.companyCountry }} · {{ match.website }}
              </p>
            </div>
            <span class="text-xl font-black text-slate-950">
              {{ percent.format(adjustedScore(match)) }}
            </span>
          </div>
          <div class="mt-3 h-2 rounded-full bg-slate-100">
            <div
              class="h-2 rounded-full bg-emerald-500"
              :style="{ width: `${Math.round(adjustedScore(match) * 100)}%` }"
            />
          </div>
          <div class="mt-3 flex items-center justify-between">
            <span class="badge" :class="statusClasses(match.status)">{{ match.status }}</span>
            <span class="text-xs font-black text-slate-400">
              Δ {{ scoreDelta(match) >= 0 ? '+' : '' }}{{ percent.format(scoreDelta(match)) }}
            </span>
          </div>
        </button>
      </div>
    </section>

    <section v-if="selectedMatch" class="min-w-0 space-y-5">
      <article class="surface p-5">
        <div class="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
          <div>
            <p class="section-kicker">Selected company</p>
            <h2 class="mt-2 text-3xl font-black leading-tight text-slate-950">
              {{ selectedMatch.companyName }}
            </h2>
            <p class="mt-2 text-sm font-semibold text-slate-500">
              {{ selectedMatch.companyCountry }} · {{ selectedMatch.website }}
            </p>
          </div>
          <div class="rounded bg-slate-950 px-5 py-4 text-white">
            <p class="text-xs font-black uppercase tracking-[0.14em] text-white/60">Adjusted score</p>
            <p class="mt-1 text-3xl font-black">{{ percent.format(adjustedScore(selectedMatch)) }}</p>
            <p class="mt-1 text-xs font-black text-white/60">
              Base {{ percent.format(selectedMatch.finalScore) }}
            </p>
          </div>
        </div>

        <p class="mt-5 text-sm leading-6 text-slate-600">{{ selectedMatch.explanation }}</p>

        <div class="mt-5 flex flex-wrap items-center gap-2">
          <button
            class="btn-primary"
            type="button"
            :disabled="emailsStore.loading"
            @click="generateEmail"
          >
            {{ emailsStore.loading ? 'Generating...' : 'Generate email' }}
          </button>
          <button
            class="btn-secondary"
            type="button"
            :disabled="matchesStore.feedbackLoading"
            @click="submitFeedback(1)"
          >
            Good fit
          </button>
          <button
            class="btn-secondary"
            type="button"
            :disabled="matchesStore.feedbackLoading"
            @click="submitFeedback(-1)"
          >
            Poor fit
          </button>
          <span v-if="actionMessage" class="text-sm font-bold text-slate-500">
            {{ actionMessage }}
            <RouterLink v-if="emailDrafted" to="/emails" class="ml-1 text-emerald-700 underline">
              view in Emails
            </RouterLink>
          </span>
        </div>

        <div class="mt-6 grid gap-4 md:grid-cols-2">
          <div v-for="score in scoreBreakdown" :key="score.label" class="rounded bg-slate-50 p-4">
            <div class="flex items-center justify-between">
              <p class="text-sm font-black text-slate-700">{{ score.label }}</p>
              <p class="text-sm font-black text-slate-950">{{ percent.format(score.value) }}</p>
            </div>
            <div class="mt-3 h-2 rounded-full bg-white">
              <div
                class="h-2 rounded-full bg-sky-500"
                :style="{ width: `${Math.round(score.value * 100)}%` }"
              />
            </div>
          </div>
        </div>
      </article>

      <section class="grid gap-5 lg:grid-cols-2">
        <article class="surface p-5">
          <p class="section-kicker">Tender context</p>
          <h3 class="mt-2 text-lg font-black leading-tight text-slate-950">
            {{ selectedTender?.title }}
          </h3>
          <p class="mt-3 text-sm leading-6 text-slate-600">{{ selectedTender?.summary }}</p>
        </article>

        <article class="surface p-5">
          <p class="section-kicker">Evidence</p>
          <ul class="mt-4 space-y-3">
            <li
              v-for="item in selectedMatch.evidence"
              :key="item"
              class="rounded border border-slate-200 bg-white p-3 text-sm font-semibold leading-6 text-slate-700"
            >
              {{ item }}
            </li>
          </ul>
        </article>
      </section>
    </section>

    <Teleport to="body">
      <div
        v-if="tenderPickerOpen"
        class="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4"
        @click="closeTenderPicker"
      >
        <div
          class="flex max-h-[72vh] w-full max-w-xl flex-col rounded-lg border border-slate-200 bg-white shadow-xl"
          @click.stop
        >
          <div class="flex items-center gap-2 border-b border-slate-200 p-3">
            <input
              v-model="tenderSearch"
              class="field w-full"
              placeholder="Search tenders…"
            >
            <button
              class="btn-secondary h-10 shrink-0 px-3 text-xs"
              type="button"
              @click="closeTenderPicker"
            >
              Close
            </button>
          </div>
          <div class="overflow-y-auto p-1">
            <button
              type="button"
              class="block w-full rounded px-3 py-2 text-left text-sm font-semibold leading-5 hover:bg-slate-100"
              :class="tenderFilter === 'all' ? 'bg-emerald-50 text-emerald-700' : 'text-slate-700'"
              @click="pickTender('all')"
            >
              All tenders
            </button>
            <button
              v-for="tender in pickerTenders"
              :key="tender.id"
              type="button"
              class="block w-full rounded px-3 py-2 text-left text-sm font-semibold leading-5 hover:bg-slate-100"
              :class="tenderFilter === tender.id ? 'bg-emerald-50 text-emerald-700' : 'text-slate-700'"
              @click="pickTender(tender.id)"
            >
              {{ tender.title }}
            </button>
            <p
              v-if="pickerTenders.length === 0"
              class="px-3 py-6 text-center text-sm font-semibold text-slate-400"
            >
              No tenders match “{{ tenderSearch }}”.
            </p>
          </div>
        </div>
      </div>
    </Teleport>
  </div>
</template>
