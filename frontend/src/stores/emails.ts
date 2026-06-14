import { defineStore } from 'pinia'
import { emailDrafts, type EmailDraft } from './sampleData'

interface ApiEmailContextTender {
  id: number
  ted_notice_id: string
  title: string | null
  buyer_name: string | null
  buyer_country: string | null
  deadline: string | null
  budget_eur: number | null
}

interface ApiEmailContextCompany {
  id: string
  name: string
  country: string | null
  website: string | null
}

interface ApiEmail {
  id: string
  match_id: string
  subject: string
  body: string
  evidence: {
    match_explanation?: string | null
    document_snippets?: Array<{ filename: string; snippet: string }>
    tender?: { title?: string | null; ted_notice_id?: string }
    company?: { website?: string | null }
  } | null
  status: string
  sent_at: string | null
  created_at: string
  updated_at: string
  tender: ApiEmailContextTender
  company: ApiEmailContextCompany
}

type FeedbackRating = 1 | -1

function toDraftStatus(status: string): EmailDraft['status'] {
  if (status === 'approved' || status === 'review') return status
  return 'draft'
}

function toEvidenceItems(email: ApiEmail): string[] {
  const snippets =
    email.evidence?.document_snippets?.map((item) => `${item.filename}: ${item.snippet}`) ?? []
  return [
    email.evidence?.match_explanation ?? `Tender: ${email.tender.title ?? email.tender.ted_notice_id}`,
    ...snippets,
  ].slice(0, 4)
}

function recipientFor(company: ApiEmailContextCompany): string {
  const website = company.website?.replace(/^https?:\/\//, '').replace(/\/$/, '')
  return website ? `sales@${website}` : 'sales@example.com'
}

function toEmailDraft(email: ApiEmail): EmailDraft {
  return {
    id: email.id,
    matchId: email.match_id,
    subject: email.subject,
    recipient: recipientFor(email.company),
    companyName: email.company.name,
    status: toDraftStatus(email.status),
    tone: 'consultative',
    updatedAt: email.updated_at,
    body: email.body,
    evidence: toEvidenceItems(email),
  }
}

export const useEmailsStore = defineStore('emails', {
  state: () => ({
    drafts: emailDrafts as EmailDraft[],
    loading: false,
    feedbackLoading: false,
    error: null as string | null,
    feedbackError: null as string | null,
    source: 'sample' as 'api' | 'sample',
  }),
  getters: {
    reviewCount: (state) => state.drafts.filter((draft) => draft.status === 'review').length,
    approvedCount: (state) => state.drafts.filter((draft) => draft.status === 'approved').length,
  },
  actions: {
    async generate(matchId: string) {
      this.loading = true
      this.error = null
      try {
        const response = await fetch(`/api/v1/emails/${matchId}/generate`, {
          method: 'POST',
        })
        if (!response.ok) {
          throw new Error(`Email API returned ${response.status}`)
        }
        const body = (await response.json()) as ApiEmail
        const draft = toEmailDraft(body)
        this.drafts = [draft, ...this.drafts.filter((item) => item.id !== draft.id)]
        this.source = 'api'
        return draft
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Email API request failed'
        this.source = 'sample'
        throw error
      } finally {
        this.loading = false
      }
    },
    async submitFeedback(draft: EmailDraft, rating: FeedbackRating, comment?: string) {
      this.feedbackLoading = true
      this.feedbackError = null
      try {
        const response = await fetch('/api/v1/feedback/', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            match_id: draft.matchId,
            email_id: draft.id,
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
    updateDraft(draftId: string, updates: Partial<Pick<EmailDraft, 'body' | 'status'>>) {
      this.drafts = this.drafts.map((draft) =>
        draft.id === draftId
          ? {
              ...draft,
              ...updates,
              updatedAt: new Date().toISOString(),
            }
          : draft,
      )
    },
  },
})
