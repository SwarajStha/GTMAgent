<!--
  AppShell — top nav + sidebar layout.
  TODO: Phase 1 — flesh out nav active states, mobile breakpoint, auth menu.
-->
<script setup lang="ts">
import { RouterLink } from 'vue-router'

const navItems = [
  { to: '/', label: 'Home' },
  { to: '/tenders', label: 'Tenders' },
  { to: '/matches', label: 'Matches' },
  { to: '/emails', label: 'Emails' },
]
</script>

<template>
  <div class="min-h-screen flex flex-col">
    <header class="border-b px-6 py-4 flex items-center gap-6">
      <h1 class="text-lg font-semibold">GTM Agent</h1>
      <nav class="flex gap-4 text-sm">
        <RouterLink v-for="item in navItems" :key="item.to" :to="item.to">
          {{ item.label }}
        </RouterLink>
      </nav>
    </header>
    <main class="flex-1 p-6">
      <slot />
    </main>
  </div>
</template>
