<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useAwardsStore } from '@/stores/awards'

const awardsStore = useAwardsStore()
const search = ref('')
const country = ref('')

const currency = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'EUR',
  maximumFractionDigits: 0,
})

function fmtValue(value: number | null) {
  // -1 / 0 are TED "not disclosed" sentinels — show them as undisclosed.
  if (value == null || value <= 0) return 'Not disclosed'
  return currency.format(value)
}

const disclosedTotal = computed(() => currency.format(awardsStore.disclosedValue))

async function reload() {
  const params = new URLSearchParams()
  if (search.value.trim()) params.set('q', search.value.trim())
  if (country.value.trim()) params.set('buyer_country', country.value.trim().toUpperCase())
  await awardsStore.fetchAll(params)
}

onMounted(reload)
</script>

<template>
  <div class="min-w-0 space-y-5">
    <section class="grid gap-4 sm:grid-cols-3">
      <div class="metric-card">
        <p class="section-kicker">Awards loaded</p>
        <p class="mt-2 text-3xl font-black text-slate-950">{{ awardsStore.total || awardsStore.items.length }}</p>
      </div>
      <div class="metric-card">
        <p class="section-kicker">Disclosed value (page)</p>
        <p class="mt-2 text-3xl font-black text-slate-950">{{ disclosedTotal }}</p>
      </div>
      <div class="metric-card">
        <p class="section-kicker">Source</p>
        <p class="mt-2 text-3xl font-black" :class="awardsStore.source === 'api' ? 'text-emerald-600' : 'text-amber-600'">
          {{ awardsStore.source === 'api' ? 'Live API' : 'Sample' }}
        </p>
      </div>
    </section>

    <section class="surface p-4">
      <p class="section-kicker">Contract award notices</p>
      <h2 class="mt-1 section-title">Who has won past TED awards</h2>
      <form class="mt-4 flex flex-col gap-2 sm:flex-row" @submit.prevent="reload">
        <input v-model="search" class="field w-full sm:flex-1" placeholder="Search winner, buyer, or TED id">
        <input v-model="country" class="field w-full sm:w-40" placeholder="Country (e.g. DEU)">
        <button class="btn-primary px-5" type="submit" :disabled="awardsStore.loading">
          {{ awardsStore.loading ? 'Loading…' : 'Search' }}
        </button>
      </form>
      <p v-if="awardsStore.error" class="mt-3 text-xs font-bold text-amber-600">
        {{ awardsStore.error }} — showing sample data.
      </p>
    </section>

    <section class="surface overflow-hidden">
      <div
        v-for="award in awardsStore.items"
        :key="award.id"
        class="border-b border-slate-100 p-4 last:border-b-0"
      >
        <div class="flex flex-wrap items-start justify-between gap-3">
          <div class="min-w-0">
            <p class="truncate text-sm font-black text-slate-950">{{ award.winnerName }}</p>
            <p class="mt-1 text-xs font-semibold text-slate-500">
              {{ award.buyerName ?? 'Unknown buyer' }} · {{ award.buyerCountry ?? 'N/A' }}
            </p>
          </div>
          <div class="text-right">
            <p class="text-sm font-black text-slate-950">{{ fmtValue(award.contractValueEur) }}</p>
            <p class="mt-1 text-xs font-semibold text-slate-500">{{ award.awardDate ?? 'No date' }}</p>
          </div>
        </div>
        <div class="mt-3 flex flex-wrap items-center gap-2 text-xs font-bold">
          <span class="badge bg-slate-100 text-slate-600">CPV {{ award.cpvCode ?? 'n/a' }}</span>
          <span class="badge bg-sky-50 text-sky-700">{{ award.tedNoticeId }}</span>
          <span v-if="award.nOffersReceived != null" class="badge bg-emerald-50 text-emerald-700">
            {{ award.nOffersReceived }} offers
          </span>
        </div>
      </div>
      <p v-if="awardsStore.items.length === 0" class="p-6 text-center text-sm font-semibold text-slate-500">
        No awards found.
      </p>
    </section>
  </div>
</template>
