import { defineStore } from 'pinia'
import { matches, type MatchItem } from './sampleData'

interface ApiTenderSummary {
  id: number
  ted_notice_id: string
  title: string | null
  buyer_name: string | null
  buyer_country: string | null
  deadline: string | null
  budget_eur: number | null
  status: string
}

interface ApiCompanySummary {
  id: string
  name: string
  country: string | null
  website: string | null
}

interface ApiMatch {
  id: string
  tender_id: number
  company_id: string
  semantic_score: number
  budget_score: number
  location_score: number
  qualification_score: number
  final_score: number
  weights: Record<string, unknown> | null
  explanation: string | null
  is_disqualified: boolean
  created_at: string
  updated_at: string
  tender: ApiTenderSummary
  company: ApiCompanySummary
}

interface ApiMatchList {
  items: ApiMatch[]
  total: number
  limit: number
  offset: number
}

type FeedbackRating = 1 | -1

function toMatchStatus(match: ApiMatch): MatchItem['status'] {
  if (match.is_disqualified) return 'blocked'
  return match.final_score >= 0.8 ? 'ready' : 'needs-review'
}

function toEvidence(match: ApiMatch): string[] {
  return [
    match.explanation ?? 'No explanation has been stored for this match yet.',
    `Tender: ${match.tender.title ?? match.tender.ted_notice_id}`,
    `Company profile: ${match.company.name}`,
  ]
}

function toMatchItem(match: ApiMatch): MatchItem {
  return {
    id: match.id,
    tenderId: String(match.tender_id),
    companyName: match.company.name,
    companyCountry: match.company.country ?? 'N/A',
    website: match.company.website ?? 'No website',
    semanticScore: match.semantic_score,
    budgetScore: match.budget_score,
    locationScore: match.location_score,
    qualificationScore: match.qualification_score,
    finalScore: match.final_score,
    status: toMatchStatus(match),
    explanation: match.explanation ?? 'No explanation has been stored for this match yet.',
    evidence: toEvidence(match),
  }
}

export const useMatchesStore = defineStore('matches', {
  state: () => ({
    items: matches as MatchItem[],
    loading: false,
    feedbackLoading: false,
    error: null as string | null,
    feedbackError: null as string | null,
    source: 'sample' as 'api' | 'sample',
  }),
  getters: {
    readyCount: (state) => state.items.filter((item) => item.status === 'ready').length,
    averageScore: (state) =>
      state.items.length === 0
        ? 0
        : state.items.reduce((total, item) => total + item.finalScore, 0) / state.items.length,
  },
  actions: {
    async fetchAll(params: URLSearchParams = new URLSearchParams()) {
      this.loading = true
      this.error = null
      try {
        if (!params.has('limit')) {
          params.set('limit', '100')
        }
        const response = await fetch(`/api/v1/matches/?${params.toString()}`)
        if (!response.ok) {
          throw new Error(`Match API returned ${response.status}`)
        }
        const body = (await response.json()) as ApiMatchList
        this.items = body.items.map(toMatchItem)
        this.source = 'api'
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Match API request failed'
        this.items = matches
        this.source = 'sample'
      } finally {
        this.loading = false
      }
    },
    async submitFeedback(matchId: string, rating: FeedbackRating, comment?: string) {
      this.feedbackLoading = true
      this.feedbackError = null
      try {
        const response = await fetch('/api/v1/feedback/', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            match_id: matchId,
            rating,
            comment,
          }),
        })
        if (!response.ok) {
          throw new Error(`Feedback API returned ${response.status}`)
        }
      } catch (error) {
        this.feedbackError =
          error instanceof Error ? error.message : 'Feedback API request failed'
        throw error
      } finally {
        this.feedbackLoading = false
      }
    },
  },
})
