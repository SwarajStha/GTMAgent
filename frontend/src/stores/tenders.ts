// Pinia tender store.
// TODO: Phase 2 — fetch tender list/detail and cache results client-side.
import { defineStore } from 'pinia'

export const useTendersStore = defineStore('tenders', {
  state: () => ({
    items: [] as unknown[],
    loading: false,
  }),
  actions: {
    async fetchAll() {
      // TODO: Phase 2 — call GET /api/v1/tenders
    },
  },
})
