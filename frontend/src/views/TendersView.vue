<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useTendersStore } from '@/stores/tenders'
import type { TenderItem } from '@/stores/sampleData'

const tendersStore = useTendersStore()
const query = ref('')
const statusFilter = ref('all')
const countryFilter = ref('all')
const sortBy = ref<'deadline' | 'budget' | 'fit'>('deadline')
const selectedId = ref(tendersStore.items[0]?.id ?? '')

onMounted(() => {
  void tendersStore.fetchAll()
})

const money = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'EUR',
  maximumFractionDigits: 0,
})

const dateFormat = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  year: 'numeric',
})

const countries = computed(() =>
  Array.from(new Set(tendersStore.items.map((tender) => tender.buyerCountry))).sort(),
)

const fitRank: Record<TenderItem['fitSignal'], number> = {
  high: 3,
  medium: 2,
  watch: 1,
}

const filteredTenders = computed(() => {
  const normalizedQuery = query.value.trim().toLowerCase()

  return tendersStore.items
    .filter((tender) => {
      const haystack = [
        tender.title,
        tender.buyerName,
        tender.buyerCountry,
        tender.tedNoticeId,
        ...tender.cpvCodes,
      ]
        .join(' ')
        .toLowerCase()

      return (
        (!normalizedQuery || haystack.includes(normalizedQuery)) &&
        (statusFilter.value === 'all' || tender.status === statusFilter.value) &&
        (countryFilter.value === 'all' || tender.buyerCountry === countryFilter.value)
      )
    })
    .sort((a, b) => {
      if (sortBy.value === 'budget') return b.budgetEur - a.budgetEur
      if (sortBy.value === 'fit') return fitRank[b.fitSignal] - fitRank[a.fitSignal]
      return new Date(a.deadline).getTime() - new Date(b.deadline).getTime()
    })
})

const selectedTender = computed(
  () =>
    tendersStore.items.find((tender) => tender.id === selectedId.value) ??
    filteredTenders.value[0] ??
    tendersStore.items[0],
)

const selectedSections = computed(
  () =>
    selectedTender.value?.extractedSections ?? {
      technicalRequirements: ['No technical requirements have been extracted yet.'],
      eligibilityRequirements: ['No eligibility requirements have been extracted yet.'],
      evaluationCriteria: ['No evaluation criteria have been extracted yet.'],
      documentStatus: 'No document status available',
    },
)

const sectionPanels = computed(() => [
  {
    label: 'Technical requirements',
    items: selectedSections.value.technicalRequirements,
  },
  {
    label: 'Eligibility',
    items: selectedSections.value.eligibilityRequirements,
  },
  {
    label: 'Evaluation criteria',
    items: selectedSections.value.evaluationCriteria,
  },
])

function statusClasses(status: TenderItem['status']) {
  return {
    active: 'bg-emerald-50 text-emerald-700',
    review: 'bg-sky-50 text-sky-700',
    restricted: 'bg-rose-50 text-rose-700',
    closing: 'bg-amber-50 text-amber-700',
  }[status]
}

function fitClasses(fit: TenderItem['fitSignal']) {
  return {
    high: 'bg-emerald-600 text-white',
    medium: 'bg-sky-600 text-white',
    watch: 'bg-slate-600 text-white',
  }[fit]
}
</script>

<template>
  <div class="space-y-5">
    <section class="surface p-4">
      <div class="flex flex-col gap-4 xl:flex-row xl:items-end xl:justify-between">
        <div>
          <p class="section-kicker">Tender intake</p>
          <h2 class="mt-1 section-title">Find the opportunities worth qualifying</h2>
          <p class="mt-2 text-sm font-semibold text-slate-500">
            Source: {{ tendersStore.source === 'api' ? 'Backend API' : 'Sample data' }}
            <span v-if="tendersStore.error">· {{ tendersStore.error }}</span>
          </p>
        </div>
        <div class="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <input v-model="query" class="field" type="search" placeholder="Search buyer, CPV, title">
          <select v-model="statusFilter" class="field">
            <option value="all">All statuses</option>
            <option value="active">Active</option>
            <option value="closing">Closing</option>
            <option value="review">Review</option>
            <option value="restricted">Restricted</option>
          </select>
          <select v-model="countryFilter" class="field">
            <option value="all">All countries</option>
            <option v-for="country in countries" :key="country" :value="country">
              {{ country }}
            </option>
          </select>
          <select v-model="sortBy" class="field">
            <option value="deadline">Soonest deadline</option>
            <option value="budget">Largest budget</option>
            <option value="fit">Highest fit</option>
          </select>
        </div>
      </div>
    </section>

    <section class="grid min-w-0 gap-5 xl:grid-cols-[1fr_390px]">
      <div class="surface min-w-0 overflow-hidden">
        <div class="grid grid-cols-[1fr_120px_120px_130px] border-b border-slate-200 bg-slate-50 px-4 py-3 text-xs font-black uppercase tracking-[0.12em] text-slate-400 max-lg:hidden">
          <span>Tender</span>
          <span>Country</span>
          <span>Deadline</span>
          <span class="text-right">Budget</span>
        </div>

        <div
          v-if="filteredTenders.length === 0"
          class="p-8 text-center text-sm font-semibold text-slate-500"
        >
          No tenders matched the current filters.
        </div>

        <button
          v-for="tender in filteredTenders"
          :key="tender.id"
          class="grid w-full gap-3 border-b border-slate-100 px-4 py-4 text-left transition last:border-b-0 hover:bg-slate-50 lg:grid-cols-[1fr_120px_120px_130px] lg:items-center"
          :class="selectedTender?.id === tender.id ? 'bg-emerald-50/60' : 'bg-white'"
          type="button"
          @click="selectedId = tender.id"
        >
          <span class="min-w-0">
            <span class="flex flex-wrap items-center gap-2">
              <span class="truncate text-sm font-black text-slate-950">{{ tender.title }}</span>
              <span class="badge" :class="statusClasses(tender.status)">{{ tender.status }}</span>
              <span class="badge" :class="fitClasses(tender.fitSignal)">{{ tender.fitSignal }}</span>
            </span>
            <span class="mt-1 block text-sm font-semibold text-slate-500">
              {{ tender.buyerName }} · {{ tender.tedNoticeId }}
            </span>
          </span>
          <span class="text-sm font-black text-slate-700">{{ tender.buyerCountry }}</span>
          <span class="text-sm font-semibold text-slate-600">
            {{ dateFormat.format(new Date(tender.deadline)) }}
          </span>
          <span class="text-sm font-black text-slate-950 lg:text-right">
            {{ money.format(tender.budgetEur) }}
          </span>
        </button>
      </div>

      <aside v-if="selectedTender" class="surface h-max p-5">
        <p class="section-kicker">Tender detail</p>
        <h3 class="mt-2 text-xl font-black leading-tight text-slate-950">
          {{ selectedTender.title }}
        </h3>
        <p class="mt-3 text-sm leading-6 text-slate-600">{{ selectedTender.summary }}</p>

        <dl class="mt-5 grid grid-cols-2 gap-3">
          <div class="rounded bg-slate-50 p-3">
            <dt class="text-xs font-black uppercase tracking-[0.12em] text-slate-400">Buyer</dt>
            <dd class="mt-1 text-sm font-black text-slate-800">{{ selectedTender.buyerName }}</dd>
          </div>
          <div class="rounded bg-slate-50 p-3">
            <dt class="text-xs font-black uppercase tracking-[0.12em] text-slate-400">Docs</dt>
            <dd class="mt-1 text-sm font-black text-slate-800">
              {{ selectedTender.documentCount }} files
            </dd>
          </div>
          <div class="rounded bg-slate-50 p-3">
            <dt class="text-xs font-black uppercase tracking-[0.12em] text-slate-400">Deadline</dt>
            <dd class="mt-1 text-sm font-black text-slate-800">
              {{ dateFormat.format(new Date(selectedTender.deadline)) }}
            </dd>
          </div>
          <div class="rounded bg-slate-50 p-3">
            <dt class="text-xs font-black uppercase tracking-[0.12em] text-slate-400">Budget</dt>
            <dd class="mt-1 text-sm font-black text-slate-800">
              {{ money.format(selectedTender.budgetEur) }}
            </dd>
          </div>
        </dl>

        <div class="mt-5">
          <p class="text-sm font-black text-slate-700">CPV codes</p>
          <div class="mt-2 flex flex-wrap gap-2">
            <span
              v-for="code in selectedTender.cpvCodes"
              :key="code"
              class="badge bg-white text-slate-600 ring-1 ring-slate-200"
            >
              {{ code }}
            </span>
          </div>
        </div>

        <div class="mt-5 rounded border border-slate-200 bg-slate-50 p-4">
          <p class="section-kicker">Dossier status</p>
          <p class="mt-2 text-sm font-bold leading-6 text-slate-700">
            {{ selectedSections.documentStatus }}
          </p>
        </div>
      </aside>
    </section>

    <section v-if="selectedTender" class="grid gap-5 lg:grid-cols-3">
      <article
        v-for="panel in sectionPanels"
        :key="panel.label"
        class="surface p-5"
      >
        <p class="section-kicker">{{ panel.label }}</p>
        <ul class="mt-4 space-y-3">
          <li
            v-for="item in panel.items"
            :key="item"
            class="rounded border border-slate-200 bg-slate-50 p-3 text-sm font-semibold leading-6 text-slate-700"
          >
            {{ item }}
          </li>
        </ul>
      </article>
    </section>
  </div>
</template>
