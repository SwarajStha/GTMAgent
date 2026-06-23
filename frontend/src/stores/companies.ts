import { defineStore } from 'pinia'
import { companies, type CompanyItem } from './sampleData'

interface ApiCompany {
  id: number
  canonical_name: string
  resolution_key: string
  aliases: string[]
  country: string | null
  created_at: string
  award_count: number
  total_contract_value_eur: number | null
  latest_award_date: string | null
}

interface ApiCompanyList {
  items: ApiCompany[]
  total: number
  limit: number
  offset: number
}

function toCompanyItem(company: ApiCompany): CompanyItem {
  return {
    id: company.id,
    canonicalName: company.canonical_name,
    country: company.country,
    aliases: company.aliases ?? [],
    awardCount: company.award_count,
    totalContractValueEur: company.total_contract_value_eur,
    latestAwardDate: company.latest_award_date,
  }
}

export const useCompaniesStore = defineStore('companies', {
  state: () => ({
    items: companies as CompanyItem[],
    total: 0,
    loading: false,
    error: null as string | null,
    source: 'sample' as 'api' | 'sample',
  }),
  getters: {
    totalAwards: (state) => state.items.reduce((total, item) => total + item.awardCount, 0),
  },
  actions: {
    async fetchAll(params: URLSearchParams = new URLSearchParams()) {
      this.loading = true
      this.error = null
      try {
        if (!params.has('limit')) {
          params.set('limit', '100')
        }
        const response = await fetch(`/api/v1/companies/?${params.toString()}`)
        if (!response.ok) {
          throw new Error(`Companies API returned ${response.status}`)
        }
        const body = (await response.json()) as ApiCompanyList
        this.items = body.items.map(toCompanyItem)
        this.total = body.total
        this.source = 'api'
      } catch (error) {
        this.error = error instanceof Error ? error.message : 'Companies API request failed'
        this.items = companies
        this.total = companies.length
        this.source = 'sample'
      } finally {
        this.loading = false
      }
    },
  },
})
