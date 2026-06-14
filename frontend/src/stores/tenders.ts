import { defineStore } from 'pinia'
import { tenders, type TenderItem, type TenderStatus } from './sampleData'

interface ApiTender {
  id: number
  ted_notice_id: string
  title: string | null
  buyer_name: string | null
  buyer_country: string | null
  cpv_codes: string[]
  deadline: string | null
  budget_eur: number | null
  currency: string | null
  status: string
  document_url: string | null
  is_restricted: boolean
  ingested_at: string
  updated_at: string
}

interface ApiTenderList {
  items: ApiTender[]
  total: number
  limit: number
  offset: number
}

const statusMap = new Set<TenderStatus>(['active', 'review', 'restricted', 'closing'])

function toTenderItem(tender: ApiTender): TenderItem {
  const normalizedStatus = tender.is_restricted ? 'restricted' : tender.status
  const status = statusMap.has(normalizedStatus as TenderStatus)
    ? (normalizedStatus as TenderStatus)
    : 'active'
  const deadline = tender.deadline ?? tender.updated_at
  const title = tender.title ?? `TED notice ${tender.ted_notice_id}`
  const buyerName = tender.buyer_name ?? 'Unknown buyer'
  const buyerCountry = tender.buyer_country ?? 'N/A'

  return {
    id: String(tender.id),
    tedNoticeId: tender.ted_notice_id,
    title,
    buyerName,
    buyerCountry,
    cpvCodes: tender.cpv_codes,
    deadline,
    budgetEur: tender.budget_eur ?? 0,
    status,
    documentCount: tender.document_url ? 1 : 0,
    fitSignal: status === 'closing' ? 'high' : status === 'restricted' ? 'watch' : 'medium',
    summary: `${buyerName} published ${title}. Source: ${tender.ted_notice_id}.`,
    extractedSections: {
      technicalRequirements: [
        `${title} is classified under CPV ${tender.cpv_codes.join(', ') || 'not specified'}.`,
        tender.document_url
          ? 'Tender documents are linked and can be used for deeper extraction.'
          : 'No tender document URL has been captured yet.',
        tender.budget_eur
          ? `Estimated budget is ${new Intl.NumberFormat('en-US', {
              style: 'currency',
              currency: tender.currency ?? 'EUR',
              maximumFractionDigits: 0,
            }).format(tender.budget_eur)}.`
          : 'No budget value has been extracted yet.',
      ],
      eligibilityRequirements: [
        status === 'restricted'
          ? 'Restricted access rules require manual review before outreach.'
          : 'Eligibility requirements have not been extracted into structured fields yet.',
        buyerCountry !== 'N/A'
          ? `Buyer country is ${buyerCountry}; local delivery feasibility should be checked.`
          : 'Buyer country is missing and should be validated.',
      ],
      evaluationCriteria: [
        'Match quality should consider semantic fit, budget fit, location, and qualifications.',
        'Source evidence should be reviewed before sending outreach.',
      ],
      documentStatus: tender.document_url ? 'Document URL captured' : 'No document URL captured',
    },
  }
}

export const useTendersStore = defineStore('tenders', {
  state: () => ({
    items: tenders as TenderItem[],
    loading: false,
    error: null as string | null,
    source: 'sample' as 'api' | 'sample',
  }),
  getters: {
    activeCount: (state) => state.items.filter((item) => item.status === 'active').length,
    closingCount: (state) => state.items.filter((item) => item.status === 'closing').length,
    totalPipelineValue: (state) =>
      state.items.reduce((total, item) => total + item.budgetEur, 0),
  },
  actions: {
    async fetchAll(params: URLSearchParams = new URLSearchParams()) {
      this.loading = true
      this.error = null
      try {
        if (!params.has('limit')) {
          params.set('limit', '100')
        }
        const response = await fetch(`/api/v1/tenders/?${params.toString()}`)
        if (!response.ok) {
          throw new Error(`Tender API returned ${response.status}`)
        }
        const body = (await response.json()) as ApiTenderList
        this.items = body.items.map(toTenderItem)
        this.source = 'api'
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Tender API request failed'
        this.items = tenders
        this.source = 'sample'
      } finally {
        this.loading = false
      }
    },
  },
})
