import { defineStore } from 'pinia'
import { awards, type AwardItem } from './sampleData'

interface ApiAward {
  id: number
  ted_notice_id: string
  cpv_code: string | null
  buyer_name: string | null
  buyer_country: string | null
  winner_raw_name: string
  winner_canonical_id: number | null
  winner_canonical_name: string | null
  contract_value_eur: number | null
  award_date: string | null
  n_offers_received: number | null
  ingested_at: string
}

interface ApiAwardList {
  items: ApiAward[]
  total: number
  limit: number
  offset: number
}

function toAwardItem(award: ApiAward): AwardItem {
  return {
    id: award.id,
    tedNoticeId: award.ted_notice_id,
    cpvCode: award.cpv_code,
    buyerName: award.buyer_name,
    buyerCountry: award.buyer_country,
    winnerName: award.winner_canonical_name ?? award.winner_raw_name,
    contractValueEur: award.contract_value_eur,
    awardDate: award.award_date,
    nOffersReceived: award.n_offers_received,
  }
}

export const useAwardsStore = defineStore('awards', {
  state: () => ({
    items: awards as AwardItem[],
    total: 0,
    loading: false,
    error: null as string | null,
    source: 'sample' as 'api' | 'sample',
  }),
  getters: {
    disclosedValue: (state) =>
      state.items.reduce((total, item) => total + (item.contractValueEur ?? 0), 0),
  },
  actions: {
    async fetchAll(params: URLSearchParams = new URLSearchParams()) {
      this.loading = true
      this.error = null
      try {
        if (!params.has('limit')) {
          params.set('limit', '100')
        }
        const response = await fetch(`/api/v1/awards/?${params.toString()}`)
        if (!response.ok) {
          throw new Error(`Awards API returned ${response.status}`)
        }
        const body = (await response.json()) as ApiAwardList
        this.items = body.items.map(toAwardItem)
        this.total = body.total
        this.source = 'api'
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Awards API request failed'
        this.items = awards
        this.total = awards.length
        this.source = 'sample'
      } finally {
        this.loading = false
      }
    },
  },
})
