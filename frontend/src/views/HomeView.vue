<script setup lang="ts">
import { ref, onMounted } from 'vue'

const backendStatus = ref<string>('checking...')

onMounted(async () => {
  try {
    const res = await fetch('/health')
    if (!res.ok) {
      backendStatus.value = 'unreachable'
      return
    }
    const body = await res.json()
    backendStatus.value = body.status ?? 'unknown'
  } catch {
    backendStatus.value = 'unreachable'
  }
})
</script>

<template>
  <section class="space-y-2">
    <h2 class="text-2xl font-bold">GTM Agent — running</h2>
    <p class="text-sm text-gray-600">
      B2B lead-generation pipeline for the construction-tech sector.
    </p>
    <p class="text-xs text-gray-500">Backend status: {{ backendStatus }}</p>
  </section>
</template>
