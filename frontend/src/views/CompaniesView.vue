<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useCompaniesStore } from '@/stores/companies'

const companiesStore = useCompaniesStore()
const search = ref('')
const country = ref('')

const currency = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'EUR',
  maximumFractionDigits: 0,
})

function fmtValue(value: number | null) {
  if (value == null || value <= 0) return 'Not disclosed'
  return currency.format(value)
}

const totalAwards = computed(() => companiesStore.totalAwards)

async function reload() {
  const params = new URLSearchParams()
  if (search.value.trim()) params.set('q', search.value.trim())
  if (country.value.trim()) params.set('country', country.value.trim().toUpperCase())
  await companiesStore.fetchAll(params)
}

onMounted(reload)
</script>

<template>
  <div class="min-w-0 space-y-5">
    <section class="grid gap-4 sm:grid-cols-3">
      <div class="metric-card">
        <p class="section-kicker">Companies loaded</p>
        <p class="mt-2 text-3xl font-black text-slate-950">{{ companiesStore.total || companiesStore.items.length }}</p>
      </div>
      <div class="metric-card">
        <p class="section-kicker">Awards (page)</p>
        <p class="mt-2 text-3xl font-black text-slate-950">{{ totalAwards }}</p>
      </div>
      <div class="metric-card">
        <p class="section-kicker">Source</p>
        <p class="mt-2 text-3xl font-black" :class="companiesStore.source === 'api' ? 'text-emerald-600' : 'text-amber-600'">
          {{ companiesStore.source === 'api' ? 'Live API' : 'Sample' }}
        </p>
      </div>
    </section>

    <section class="surface p-4">
      <p class="section-kicker">Supplier pool</p>
      <h2 class="mt-1 section-title">Canonical companies from award winners</h2>
      <p class="mt-2 text-xs font-semibold leading-5 text-slate-500">
        The matcher's supplier pool is derived from these past award winners (a known V1 constraint).
      </p>
      <form class="mt-4 flex flex-col gap-2 sm:flex-row" @submit.prevent="reload">
        <input v-model="search" class="field w-full sm:flex-1" placeholder="Search company name">
        <input v-model="country" class="field w-full sm:w-40" placeholder="Country (e.g. CZE)">
        <button class="btn-primary px-5" type="submit" :disabled="companiesStore.loading">
          {{ companiesStore.loading ? 'Loading…' : 'Search' }}
        </button>
      </form>
      <p v-if="companiesStore.error" class="mt-3 text-xs font-bold text-amber-600">
        {{ companiesStore.error }} — showing sample data.
      </p>
    </section>

    <section class="surface overflow-hidden">
      <div
        v-for="company in companiesStore.items"
        :key="company.id"
        class="border-b border-slate-100 p-4 last:border-b-0"
      >
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <p class="truncate text-sm font-black text-slate-950">{{ company.canonicalName }}</p>
            <p class="mt-1 truncate text-xs font-semibold text-slate-500">
              {{ company.country ?? 'N/A' }}
              <span v-if="company.aliases.length"> · aka {{ company.aliases.join(', ') }}</span>
            </p>
          </div>
          <div class="text-right">
            <p class="text-sm font-black text-slate-950">{{ company.awardCount }} awards</p>
            <p class="mt-1 text-xs font-semibold text-slate-500">{{ fmtValue(company.totalContractValueEur) }}</p>
          </div>
        </div>
        <div class="mt-3 flex flex-wrap items-center gap-2 text-xs font-bold">
          <span class="badge bg-slate-100 text-slate-600">Latest {{ company.latestAwardDate ?? 'n/a' }}</span>
        </div>
      </div>
      <p v-if="companiesStore.items.length === 0" class="p-6 text-center text-sm font-semibold text-slate-500">
        No companies found.
      </p>
    </section>
  </div>
</template>
