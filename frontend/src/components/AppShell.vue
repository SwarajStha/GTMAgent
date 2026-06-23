<script setup lang="ts">
import { RouterLink } from 'vue-router'

const navItems = [
  { to: '/', label: 'Command', short: 'CM' },
  { to: '/tenders', label: 'Tenders', short: 'TD' },
  { to: '/matches', label: 'Matches', short: 'MT' },
  { to: '/emails', label: 'Emails', short: 'EM' },
  { to: '/awards', label: 'Awards', short: 'AW' },
  { to: '/companies', label: 'Companies', short: 'CO' },
  { to: '/agent', label: 'Agent', short: 'AG' },
]

const pipelineSteps = [
  { label: 'Ingest', value: 'Live' },
  { label: 'Extract', value: 'Queued' },
  { label: 'Match', value: 'Scored' },
  { label: 'Draft', value: 'Review' },
]
</script>

<template>
  <div class="min-h-screen bg-slate-100 text-slate-950">
    <div class="mx-auto flex min-h-screen w-full max-w-[1560px] flex-col lg:flex-row">
      <aside
        class="border-b border-slate-200 bg-white px-4 py-4 lg:sticky lg:top-0 lg:h-screen lg:w-72 lg:border-b-0 lg:border-r lg:px-5 lg:py-6"
      >
        <div class="flex items-center justify-between gap-4 lg:block">
          <RouterLink to="/" class="group flex items-center gap-3">
            <span
              class="grid h-10 w-10 shrink-0 place-items-center rounded bg-emerald-600 text-sm font-black text-white shadow-sm"
            >
              GT
            </span>
            <span>
              <span class="block text-base font-black tracking-normal">GTM Agent</span>
              <span class="block text-xs font-medium text-slate-500">Tender intelligence desk</span>
            </span>
          </RouterLink>

          <div class="hidden rounded-full bg-emerald-50 px-3 py-1 text-xs font-bold text-emerald-700 sm:block">
            Main synced
          </div>
        </div>

        <nav class="mt-5 grid grid-cols-4 gap-2 lg:grid-cols-1">
          <RouterLink
            v-for="item in navItems"
            :key="item.to"
            v-slot="{ isExactActive }"
            :to="item.to"
            class="min-w-0"
          >
            <span
              class="flex h-12 items-center gap-3 rounded px-3 text-sm font-bold transition"
              :class="
                isExactActive
                  ? 'bg-slate-950 text-white shadow-sm'
                  : 'text-slate-600 hover:bg-slate-100 hover:text-slate-950'
              "
            >
              <span
                class="grid h-7 w-7 shrink-0 place-items-center rounded border text-[10px] font-black"
                :class="isExactActive ? 'border-white/20 bg-white/10' : 'border-slate-200 bg-white'"
              >
                {{ item.short }}
              </span>
              <span class="hidden truncate sm:block">{{ item.label }}</span>
            </span>
          </RouterLink>
        </nav>

        <section class="mt-6 hidden lg:block">
          <p class="text-xs font-black uppercase tracking-[0.14em] text-slate-400">Pipeline</p>
          <div class="mt-3 space-y-2">
            <div
              v-for="step in pipelineSteps"
              :key="step.label"
              class="flex items-center justify-between border-l-2 border-slate-200 bg-slate-50 px-3 py-2"
            >
              <span class="text-sm font-semibold text-slate-700">{{ step.label }}</span>
              <span class="text-xs font-black text-slate-500">{{ step.value }}</span>
            </div>
          </div>
        </section>

        <section class="mt-6 hidden border-t border-slate-200 pt-5 lg:block">
          <p class="text-xs font-black uppercase tracking-[0.14em] text-slate-400">Focus</p>
          <p class="mt-2 text-sm leading-6 text-slate-600">
            Review closing tenders first, then approve evidence-backed outreach drafts.
          </p>
        </section>
      </aside>

      <div class="min-w-0 flex-1">
        <header class="sticky top-0 z-10 border-b border-slate-200 bg-white/90 px-4 py-3 backdrop-blur md:px-8">
          <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
            <div>
              <p class="text-xs font-black uppercase tracking-[0.14em] text-slate-400">
                Construction tech GTM pipeline
              </p>
              <h1 class="mt-1 text-xl font-black text-slate-950 md:text-2xl">
                Opportunity operations
              </h1>
            </div>
            <div class="flex flex-wrap items-center gap-2 text-xs font-bold">
              <span class="rounded-full bg-sky-50 px-3 py-1 text-sky-700">TED source active</span>
              <span class="rounded-full bg-amber-50 px-3 py-1 text-amber-700">3 drafts pending</span>
              <span class="rounded-full bg-emerald-50 px-3 py-1 text-emerald-700">4 matches scored</span>
            </div>
          </div>
        </header>

        <main class="px-4 py-5 md:px-8 md:py-7">
          <slot />
        </main>
      </div>
    </div>
  </div>
</template>
