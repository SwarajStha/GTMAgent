<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink } from 'vue-router'
import { useEmailsStore } from '@/stores/emails'
import { useMatchesStore } from '@/stores/matches'
import { useTendersStore } from '@/stores/tenders'

const tendersStore = useTendersStore()
const matchesStore = useMatchesStore()
const emailsStore = useEmailsStore()
const backendStatus = ref<'checking' | 'ok' | 'unreachable'>('checking')

onMounted(async () => {
  void Promise.all([tendersStore.fetchAll(), matchesStore.fetchAll()])
  try {
    const res = await fetch('/health')
    if (!res.ok) {
      backendStatus.value = 'unreachable'
      return
    }
    const body = (await res.json()) as { status?: string }
    backendStatus.value = body.status === 'ok' ? 'ok' : 'unreachable'
  } catch {
    backendStatus.value = 'unreachable'
  }
})

const money = new Intl.NumberFormat('en-US', {
  style: 'currency',
  currency: 'EUR',
  maximumFractionDigits: 0,
})

const percent = new Intl.NumberFormat('en-US', {
  style: 'percent',
  maximumFractionDigits: 0,
})

const topMatches = computed(() =>
  [...matchesStore.items].sort((a, b) => b.finalScore - a.finalScore).slice(0, 3),
)

const closingTender = computed(() =>
  tendersStore.items.find((tender) => tender.status === 'closing') ?? tendersStore.items[0],
)

const metrics = computed(() => [
  {
    label: 'Pipeline value',
    value: money.format(tendersStore.totalPipelineValue),
    detail: `${tendersStore.items.length} tenders tracked`,
  },
  {
    label: 'Ready matches',
    value: matchesStore.readyCount.toString(),
    detail: `${percent.format(matchesStore.averageScore)} avg score`,
  },
  {
    label: 'Draft queue',
    value: emailsStore.drafts.length.toString(),
    detail: `${emailsStore.reviewCount} need review`,
  },
  {
    label: 'Backend',
    value: backendStatus.value === 'ok' ? 'Online' : backendStatus.value,
    detail: 'FastAPI health check',
  },
])
</script>

<template>
  <div class="space-y-6">
    <section class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
      <article v-for="metric in metrics" :key="metric.label" class="metric-card">
        <p class="section-kicker">{{ metric.label }}</p>
        <p class="mt-3 text-2xl font-black text-slate-950">{{ metric.value }}</p>
        <p class="mt-1 text-sm font-semibold text-slate-500">{{ metric.detail }}</p>
      </article>
    </section>

    <section class="grid gap-5 xl:grid-cols-[1.35fr_0.65fr]">
      <article class="surface overflow-hidden">
        <div class="border-b border-slate-200 p-5">
          <p class="section-kicker">Priority tender</p>
          <div class="mt-3 flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
            <div>
              <h2 class="max-w-3xl text-2xl font-black leading-tight text-slate-950">
                {{ closingTender.title }}
              </h2>
              <p class="mt-2 text-sm font-semibold text-slate-500">
                {{ closingTender.buyerName }} · {{ closingTender.buyerCountry }} ·
                {{ money.format(closingTender.budgetEur) }}
              </p>
            </div>
            <RouterLink to="/tenders" class="btn-primary shrink-0">Review tenders</RouterLink>
          </div>
        </div>
        <div class="grid gap-4 p-5 lg:grid-cols-[0.95fr_1.05fr]">
          <div class="rounded bg-slate-50 p-4">
            <p class="text-sm font-black text-slate-700">Tender signal</p>
            <p class="mt-2 text-sm leading-6 text-slate-600">{{ closingTender.summary }}</p>
            <div class="mt-4 flex flex-wrap gap-2">
              <span
                v-for="code in closingTender.cpvCodes"
                :key="code"
                class="badge bg-white text-slate-600 ring-1 ring-slate-200"
              >
                CPV {{ code }}
              </span>
            </div>
          </div>

          <div>
            <div class="flex items-center justify-between">
              <p class="text-sm font-black text-slate-700">Best next matches</p>
              <RouterLink to="/matches" class="text-sm font-black text-emerald-700">
                Open scoring
              </RouterLink>
            </div>
            <div class="mt-3 space-y-3">
              <div
                v-for="match in topMatches"
                :key="match.id"
                class="rounded border border-slate-200 bg-white p-3"
              >
                <div class="flex items-center justify-between gap-3">
                  <div class="min-w-0">
                    <p class="truncate text-sm font-black text-slate-900">{{ match.companyName }}</p>
                    <p class="text-xs font-semibold text-slate-500">{{ match.companyCountry }}</p>
                  </div>
                  <span class="text-lg font-black text-slate-950">
                    {{ percent.format(match.finalScore) }}
                  </span>
                </div>
                <div class="mt-3 h-2 rounded-full bg-slate-100">
                  <div
                    class="h-2 rounded-full bg-emerald-500"
                    :style="{ width: `${Math.round(match.finalScore * 100)}%` }"
                  />
                </div>
              </div>
            </div>
          </div>
        </div>
      </article>

      <article class="surface p-5">
        <p class="section-kicker">Operating queue</p>
        <h2 class="mt-2 section-title">Today</h2>
        <div class="mt-5 space-y-4">
          <div class="border-l-4 border-amber-400 pl-4">
            <p class="text-sm font-black text-slate-900">Closing tender review</p>
            <p class="mt-1 text-sm text-slate-600">1 opportunity closes within 14 days.</p>
          </div>
          <div class="border-l-4 border-emerald-500 pl-4">
            <p class="text-sm font-black text-slate-900">Approved email ready</p>
            <p class="mt-1 text-sm text-slate-600">1 draft has enough evidence to send.</p>
          </div>
          <div class="border-l-4 border-sky-500 pl-4">
            <p class="text-sm font-black text-slate-900">Manual validation</p>
            <p class="mt-1 text-sm text-slate-600">2 records need compliance or sector checks.</p>
          </div>
        </div>
      </article>
    </section>
  </div>
</template>
