export type TenderStatus = 'active' | 'review' | 'restricted' | 'closing'

export interface TenderItem {
  id: string
  tedNoticeId: string
  title: string
  buyerName: string
  buyerCountry: string
  cpvCodes: string[]
  deadline: string
  budgetEur: number
  status: TenderStatus
  documentCount: number
  fitSignal: 'high' | 'medium' | 'watch'
  summary: string
  extractedSections?: {
    technicalRequirements: string[]
    eligibilityRequirements: string[]
    evaluationCriteria: string[]
    documentStatus: string
  }
}

export interface MatchItem {
  id: string
  tenderId: string
  companyName: string
  companyCountry: string
  website: string
  semanticScore: number
  budgetScore: number
  locationScore: number
  qualificationScore: number
  finalScore: number
  originalFinalScore?: number
  recomputedScore?: number
  status: 'ready' | 'needs-review' | 'blocked'
  explanation: string
  evidence: string[]
}

export interface RecommendedSupplier {
  name: string
  country: string | null
  finalScore: number
  explanation: string | null
}

export interface EmailDraft {
  id: string
  matchId: string
  subject: string
  recipient: string
  companyName: string
  status: 'draft' | 'review' | 'approved'
  tone: 'concise' | 'consultative' | 'technical'
  updatedAt: string
  body: string
  evidence: string[]
  recipientType?: 'supplier' | 'buyer'
  recommendedSuppliers?: RecommendedSupplier[]
}

export const tenders: TenderItem[] = [
  {
    id: 'tender-001',
    tedNoticeId: '2026/S 091-291044',
    title: 'Digital permitting and BIM coordination platform for municipal works',
    buyerName: 'City of Munich Construction Office',
    buyerCountry: 'DE',
    cpvCodes: ['72000000', '71320000'],
    deadline: '2026-07-08',
    budgetEur: 1850000,
    status: 'active',
    documentCount: 8,
    fitSignal: 'high',
    summary:
      'Looks for a cloud platform that connects permitting, site documentation, BIM handover, and reporting for public construction projects.',
    extractedSections: {
      technicalRequirements: [
        'Cloud platform for permitting, BIM coordination, site documentation, and reporting.',
        'Structured handover workflows for public construction projects.',
        'Security posture suitable for municipal deployment.',
      ],
      eligibilityRequirements: [
        'Public-sector implementation references are preferred.',
        'EU hosting and data protection controls should be documented.',
      ],
      evaluationCriteria: [
        'Functional coverage across permitting and BIM workflows.',
        'Implementation risk and evidence from comparable projects.',
        'Security and compliance documentation.',
      ],
      documentStatus: '8 dossier files available',
    },
  },
  {
    id: 'tender-002',
    tedNoticeId: '2026/S 088-278640',
    title: 'Road asset inspection software with mobile field capture',
    buyerName: 'Rijkswaterstaat',
    buyerCountry: 'NL',
    cpvCodes: ['48000000', '71631480'],
    deadline: '2026-06-26',
    budgetEur: 920000,
    status: 'closing',
    documentCount: 5,
    fitSignal: 'high',
    summary:
      'Procurement favors mobile-first inspection workflows, structured defect taxonomies, and exports into an existing asset registry.',
    extractedSections: {
      technicalRequirements: [
        'Mobile-first road asset inspection and offline field capture.',
        'Structured defect taxonomy and asset registry export.',
        'Reporting workflow for road authority teams.',
      ],
      eligibilityRequirements: [
        'Experience with road infrastructure workflows.',
        'Local-language support and integration references are helpful.',
      ],
      evaluationCriteria: [
        'Mobile usability for field inspectors.',
        'Integration fit with existing asset registry.',
        'Delivery confidence before the near deadline.',
      ],
      documentStatus: '5 dossier files available',
    },
  },
  {
    id: 'tender-003',
    tedNoticeId: '2026/S 084-263511',
    title: 'Framework agreement for construction procurement analytics',
    buyerName: 'Region Ile-de-France',
    buyerCountry: 'FR',
    cpvCodes: ['72212482', '72316000'],
    deadline: '2026-07-21',
    budgetEur: 2400000,
    status: 'review',
    documentCount: 11,
    fitSignal: 'medium',
    summary:
      'Multi-year analytics framework for cost benchmarks, supplier performance, award history, and tender preparation dashboards.',
    extractedSections: {
      technicalRequirements: [
        'Procurement analytics for cost benchmarks and supplier performance.',
        'Award-history exploration and dashboard reporting.',
        'Multi-year framework support.',
      ],
      eligibilityRequirements: [
        'Analytics delivery references in public procurement.',
        'Construction-sector award data coverage should be verified.',
      ],
      evaluationCriteria: [
        'Depth of benchmark and supplier analytics.',
        'Data coverage in construction categories.',
        'Usability for procurement preparation teams.',
      ],
      documentStatus: '11 dossier files available',
    },
  },
  {
    id: 'tender-004',
    tedNoticeId: '2026/S 079-245317',
    title: 'Restricted tender for secure infrastructure project data room',
    buyerName: 'Ministry of Transport',
    buyerCountry: 'IT',
    cpvCodes: ['72212730', '72500000'],
    deadline: '2026-08-02',
    budgetEur: 3100000,
    status: 'restricted',
    documentCount: 3,
    fitSignal: 'watch',
    summary:
      'Requires controlled access, audit logging, multilingual collaboration, and a verified EU hosting posture.',
    extractedSections: {
      technicalRequirements: [
        'Secure data room with controlled access and audit logging.',
        'Multilingual collaboration and document workflow support.',
        'Verified EU hosting posture.',
      ],
      eligibilityRequirements: [
        'Restricted tender access must be reviewed manually.',
        'Compliance evidence for hosting and access controls is required.',
      ],
      evaluationCriteria: [
        'Security controls and auditability.',
        'Restricted access compliance.',
        'Relevant infrastructure-project references.',
      ],
      documentStatus: 'Restricted dossier - manual access review',
    },
  },
]

export const matches: MatchItem[] = [
  {
    id: 'match-001',
    tenderId: 'tender-001',
    companyName: 'BuildFlow Systems',
    companyCountry: 'DE',
    website: 'buildflow.example',
    semanticScore: 0.94,
    budgetScore: 0.88,
    locationScore: 0.97,
    qualificationScore: 0.91,
    finalScore: 0.93,
    status: 'ready',
    explanation:
      'Strong product overlap with BIM coordination, German public-sector references, and budget range alignment.',
    evidence: [
      'BIM handover and permit workflow are both first-class capabilities.',
      'Recent municipal deployment in Bavaria matches buyer context.',
      'ISO 27001 certification satisfies the stated security preference.',
    ],
  },
  {
    id: 'match-002',
    tenderId: 'tender-002',
    companyName: 'InfraLens Mobile',
    companyCountry: 'NL',
    website: 'infralens.example',
    semanticScore: 0.9,
    budgetScore: 0.83,
    locationScore: 0.95,
    qualificationScore: 0.87,
    finalScore: 0.89,
    status: 'ready',
    explanation:
      'Best fit for mobile inspection capture, road asset workflows, and local buyer language expectations.',
    evidence: [
      'Supports offline inspection capture and structured defect coding.',
      'Existing integrations with road asset registries reduce delivery risk.',
      'Dutch-language support is explicitly available.',
    ],
  },
  {
    id: 'match-003',
    tenderId: 'tender-003',
    companyName: 'ProcureSight Analytics',
    companyCountry: 'FR',
    website: 'procuresight.example',
    semanticScore: 0.82,
    budgetScore: 0.9,
    locationScore: 0.92,
    qualificationScore: 0.79,
    finalScore: 0.84,
    status: 'needs-review',
    explanation:
      'Good analytics fit, but construction-specific award history coverage should be validated before outreach.',
    evidence: [
      'Dashboard and supplier performance modules map well to the framework scope.',
      'Budget fit is strong for a multi-year analytics contract.',
      'Construction award data depth is unclear from public materials.',
    ],
  },
  {
    id: 'match-004',
    tenderId: 'tender-004',
    companyName: 'VaultWorks EU',
    companyCountry: 'IE',
    website: 'vaultworks.example',
    semanticScore: 0.77,
    budgetScore: 0.86,
    locationScore: 0.61,
    qualificationScore: 0.72,
    finalScore: 0.73,
    status: 'blocked',
    explanation:
      'Secure data room capability is relevant, but restricted access rules and hosting requirements need manual review.',
    evidence: [
      'Audit logging and controlled data-room access are present.',
      'EU hosting statement is broad and needs a compliance citation.',
      'No clear Italian public infrastructure reference found.',
    ],
  },
]

export const emailDrafts: EmailDraft[] = [
  {
    id: 'email-001',
    matchId: 'match-001',
    subject: 'Munich BIM permitting tender - BuildFlow fit',
    recipient: 'partnerships@buildflow.example',
    companyName: 'BuildFlow Systems',
    status: 'approved',
    tone: 'consultative',
    updatedAt: '2026-06-12T09:20:00Z',
    body:
      'Hi BuildFlow team,\n\nWe found a Munich municipal tender seeking a cloud platform for permitting, BIM coordination, and site documentation. Your public-sector references in Bavaria and ISO 27001 posture look directly relevant.\n\nThe current deadline is July 8, 2026. I can send the notice summary and evidence table if this is in your target pipeline.\n\nBest,\nGTM Agent',
    evidence: [
      'Tender asks for permitting, BIM handover, and reporting in one workflow.',
      'BuildFlow lists municipal deployments in Bavaria.',
      'Security preference maps to ISO 27001.',
    ],
  },
  {
    id: 'email-002',
    matchId: 'match-002',
    subject: 'Road inspection software opportunity in the Netherlands',
    recipient: 'sales@infralens.example',
    companyName: 'InfraLens Mobile',
    status: 'review',
    tone: 'concise',
    updatedAt: '2026-06-12T08:10:00Z',
    body:
      'Hi InfraLens team,\n\nA Dutch road authority tender is closing on June 26 and prioritizes mobile field capture, defect taxonomies, and asset-registry exports. That appears close to InfraLens Mobile.\n\nWould you like the parsed tender profile and match rationale?\n\nBest,\nGTM Agent',
    evidence: [
      'Mobile-first capture is a stated workflow need.',
      'Tender requires exports into an existing asset registry.',
      'Company has Dutch-language product support.',
    ],
  },
  {
    id: 'email-003',
    matchId: 'match-003',
    subject: 'Check before outreach: procurement analytics framework',
    recipient: 'bd@procuresight.example',
    companyName: 'ProcureSight Analytics',
    status: 'draft',
    tone: 'technical',
    updatedAt: '2026-06-11T16:45:00Z',
    body:
      'Hi ProcureSight team,\n\nWe identified a French regional framework for procurement analytics covering cost benchmarks, supplier performance, and award history. Your analytics modules appear relevant, but we need to confirm construction-specific award coverage before recommending outreach.\n\nBest,\nGTM Agent',
    evidence: [
      'Framework scope includes benchmarks, supplier performance, and award history.',
      'Company positioning matches procurement analytics.',
      'Construction-sector coverage needs validation.',
    ],
  },
]
