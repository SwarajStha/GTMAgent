// Pinia emails store.
// TODO: Phase 4 — fetch and cache generated outreach drafts.
import { defineStore } from 'pinia'

export const useEmailsStore = defineStore('emails', {
  state: () => ({
    drafts: [] as unknown[],
    loading: false,
  }),
  actions: {
    async generate(_matchId: string) {
      // TODO: Phase 4 — call POST /api/v1/emails/{matchId}/generate
    },
  },
})
