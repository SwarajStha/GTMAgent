// Pinia matches store.
// TODO: Phase 3 — fetch match results scoped to a tender or company.
import { defineStore } from 'pinia'

export const useMatchesStore = defineStore('matches', {
  state: () => ({
    items: [] as unknown[],
    loading: false,
  }),
  actions: {
    async fetchAll() {
      // TODO: Phase 3 — call GET /api/v1/matches
    },
  },
})
