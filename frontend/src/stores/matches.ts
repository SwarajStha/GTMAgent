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
  // v5 LR feature columns (null on legacy fixed-weight matches). Surfaced here
  // for the planned feature-breakdown UI; the view does not render them yet.
  cpv_4digit_score?: number | null
  cpv_2digit_score?: number | null
  nuts_exact_score?: number | null
  nuts_country_score?: number | null
  value_score?: number | null
  value_in_range_score?: number | null
  country_match_score?: number | null
  company_size_score?: number | null
  competition_score?: number | null
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

export interface MatchWeights {
  semantic: number
  budget: number
  location: number
  qualification: number
}

// The unified pipeline writes a calibrated LR win-probability as final_score,
// which tops out around ~0.8 for strong matches (see the smoke records) — the
// previous 0.8 "ready" cut-off therefore almost never fired. 0.6 marks a
// genuinely strong match while still separating the long tail of weak ones.
const READY_SCORE = 0.6

function toMatchStatus(match: ApiMatch): MatchItem['status'] {
  if (match.is_disqualified) return 'blocked'
  return match.final_score >= READY_SCORE ? 'ready' : 'needs-review'
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
    // Persist the operator's tender selection here (not in local component
    // state) so navigating away from the Matches screen and back restores the
    // chosen tender + its per-tender matches, instead of snapping to "All
    // tenders" and reloading the global top-N (which drops niche matches).
    selectedTenderId: 'all' as string,
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
    async runMatching(tenderId: string, topN?: number, weights?: MatchWeights) {
      this.loading = true
      this.error = null
      try {
        const query = topN ? `?top_n=${topN}` : ''
        // G16: when the operator supplies weights, post them so the backend
        // re-ranks in weighted mode and persists the choice (otherwise the
        // default trained-LR scorer runs with no body).
        const init: RequestInit = weights
          ? {
              method: 'POST',
              headers: { 'Content-Type': 'application/json' },
              body: JSON.stringify(weights),
            }
          : { method: 'POST' }
        const response = await fetch(`/api/v1/matches/run/${tenderId}${query}`, init)
        if (!response.ok) {
          throw new Error(`Run matching returned ${response.status}`)
        }
        const result = (await response.json()) as { mode: string }
        // Refresh THIS tender's matches, not the global list. A plain fetchAll()
        // returns the top-N matches by score across *all* tenders, so a niche
        // tender whose matches score below the global top-100 would show an empty
        // list even though matching succeeded. Filtering by tender_id always
        // surfaces the rows we just wrote.
        await this.fetchAll(new URLSearchParams({ tender_id: tenderId }))
        this.source = 'api'
        return result.mode
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Run matching failed'
        throw error
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
