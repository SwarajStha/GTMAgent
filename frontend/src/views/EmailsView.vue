<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useEmailsStore } from '@/stores/emails'
import { useMatchesStore } from '@/stores/matches'
import type { EmailDraft } from '@/stores/sampleData'

const emailsStore = useEmailsStore()
const matchesStore = useMatchesStore()
const selectedId = ref(emailsStore.drafts[0]?.id ?? '')
const statusFilter = ref('all')
const actionMessage = ref('')
const editing = ref(false)
const draftBody = ref('')

onMounted(async () => {
  await matchesStore.fetchAll()
  selectedId.value = emailsStore.drafts[0]?.id ?? ''
})

const dateFormat = new Intl.DateTimeFormat('en-US', {
  month: 'short',
  day: 'numeric',
  hour: '2-digit',
  minute: '2-digit',
})

const filteredDrafts = computed(() =>
  emailsStore.drafts.filter(
    (draft) => statusFilter.value === 'all' || draft.status === statusFilter.value,
  ),
)

const selectedDraft = computed(
  () =>
    emailsStore.drafts.find((draft) => draft.id === selectedId.value) ??
    filteredDrafts.value[0] ??
    emailsStore.drafts[0],
)

const selectedMatch = computed(() =>
  matchesStore.items.find((match) => match.id === selectedDraft.value?.matchId),
)

const evidenceGroups = computed(() => {
  const draft = selectedDraft.value
  if (!draft) return []
  return [
    {
      label: 'Match rationale',
      items: selectedMatch.value?.explanation ? [selectedMatch.value.explanation] : [],
    },
    {
      label: 'Draft evidence',
      items: draft.evidence,
    },
    {
      label: 'Source placeholders',
      items: [
        'Claim-level source spans will link to document page and character ranges once evidence extraction is available.',
      ],
    },
  ].filter((group) => group.items.length > 0)
})

function statusClasses(status: EmailDraft['status']) {
  return {
    draft: 'bg-slate-100 text-slate-700',
    review: 'bg-amber-50 text-amber-700',
    approved: 'bg-emerald-50 text-emerald-700',
  }[status]
}

async function submitFeedback(rating: 1 | -1) {
  if (!selectedDraft.value) return
  actionMessage.value = ''
  try {
    await emailsStore.submitFeedback(
      selectedDraft.value,
      rating,
      rating === 1 ? 'Email draft looks useful' : 'Email draft needs revision',
    )
    actionMessage.value = rating === 1 ? 'Positive feedback saved' : 'Negative feedback saved'
  } catch {
    actionMessage.value = emailsStore.feedbackError ?? 'Feedback failed'
  }
}

function startEdit() {
  if (!selectedDraft.value) return
  draftBody.value = selectedDraft.value.body
  editing.value = true
  actionMessage.value = ''
}

function cancelEdit() {
  editing.value = false
  draftBody.value = ''
}

function saveEdit() {
  if (!selectedDraft.value) return
  emailsStore.updateDraft(selectedDraft.value.id, {
    body: draftBody.value,
    status: 'review',
  })
  editing.value = false
  actionMessage.value = 'Draft updated locally'
}

function approveDraft() {
  if (!selectedDraft.value) return
  emailsStore.updateDraft(selectedDraft.value.id, { status: 'approved' })
  actionMessage.value = 'Draft approved locally'
}
</script>

<template>
  <div class="grid min-w-0 gap-5 xl:grid-cols-[410px_1fr]">
    <section class="min-w-0 space-y-4">
      <div class="surface p-4">
        <p class="section-kicker">Email generation</p>
        <h2 class="mt-1 section-title">Evidence-backed outreach queue</h2>
        <select v-model="statusFilter" class="field mt-4 w-full">
          <option value="all">All drafts</option>
          <option value="draft">Draft</option>
          <option value="review">Review</option>
          <option value="approved">Approved</option>
        </select>
      </div>

      <div class="surface overflow-hidden">
        <button
          v-for="draft in filteredDrafts"
          :key="draft.id"
          class="w-full border-b border-slate-100 p-4 text-left transition last:border-b-0 hover:bg-slate-50"
          :class="selectedDraft?.id === draft.id ? 'bg-emerald-50/60' : 'bg-white'"
          type="button"
          @click="selectedId = draft.id"
        >
          <div class="flex items-start justify-between gap-3">
            <div class="min-w-0">
              <p class="truncate text-sm font-black text-slate-950">{{ draft.companyName }}</p>
              <p class="mt-1 truncate text-xs font-semibold text-slate-500">{{ draft.subject }}</p>
            </div>
            <span class="badge shrink-0" :class="statusClasses(draft.status)">
              {{ draft.status }}
            </span>
          </div>
          <div class="mt-3 flex items-center justify-between text-xs font-bold text-slate-400">
            <span>{{ draft.tone }}</span>
            <span>{{ dateFormat.format(new Date(draft.updatedAt)) }}</span>
          </div>
        </button>
      </div>
    </section>

    <section v-if="selectedDraft" class="min-w-0 space-y-5">
      <article class="surface overflow-hidden">
        <div class="border-b border-slate-200 bg-white p-5">
          <div class="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div class="min-w-0">
              <p class="section-kicker">Draft preview</p>
              <h2 class="mt-2 text-2xl font-black leading-tight text-slate-950">
                {{ selectedDraft.subject }}
              </h2>
              <p class="mt-2 text-sm font-semibold text-slate-500">
                To {{ selectedDraft.recipient }}
              </p>
            </div>
            <div class="flex flex-wrap gap-2">
              <button
                class="btn-secondary"
                type="button"
                :disabled="emailsStore.feedbackLoading"
                @click="submitFeedback(1)"
              >
                Good draft
              </button>
              <button
                class="btn-secondary"
                type="button"
                :disabled="emailsStore.feedbackLoading"
                @click="submitFeedback(-1)"
              >
                Needs work
              </button>
              <button class="btn-secondary" type="button" @click="startEdit">Edit</button>
              <button class="btn-primary" type="button" @click="approveDraft">Approve</button>
            </div>
          </div>
          <p v-if="actionMessage" class="mt-3 text-sm font-bold text-slate-500">
            {{ actionMessage }}
          </p>
        </div>

        <div class="grid gap-0 2xl:grid-cols-[minmax(420px,1fr)_330px]">
          <div class="p-5">
            <div v-if="!editing" class="rounded border border-slate-200 bg-slate-50 p-5">
              <p class="whitespace-pre-line text-sm leading-7 text-slate-700">
                {{ selectedDraft.body }}
              </p>
            </div>
            <div v-else class="space-y-3">
              <textarea
                v-model="draftBody"
                class="field h-80 w-full resize-none p-4 leading-7"
              />
              <div class="flex flex-wrap gap-2">
                <button class="btn-primary" type="button" @click="saveEdit">Save edits</button>
                <button class="btn-secondary" type="button" @click="cancelEdit">Cancel</button>
              </div>
            </div>
          </div>
          <aside class="border-t border-slate-200 bg-slate-50 p-5 2xl:border-l 2xl:border-t-0">
            <p class="section-kicker">Match context</p>
            <p class="mt-2 text-lg font-black text-slate-950">
              {{ selectedDraft.companyName }}
            </p>
            <p class="mt-2 text-sm leading-6 text-slate-600">
              {{ selectedMatch?.explanation }}
            </p>
            <dl class="mt-5 space-y-3">
              <div class="flex items-center justify-between">
                <dt class="text-sm font-bold text-slate-500">Status</dt>
                <dd class="badge" :class="statusClasses(selectedDraft.status)">
                  {{ selectedDraft.status }}
                </dd>
              </div>
              <div class="flex items-center justify-between">
                <dt class="text-sm font-bold text-slate-500">Tone</dt>
                <dd class="text-sm font-black text-slate-900">{{ selectedDraft.tone }}</dd>
              </div>
            </dl>
          </aside>
        </div>
      </article>

      <article class="surface p-5">
        <p class="section-kicker">Evidence used in draft</p>
        <div class="mt-4 grid gap-4 md:grid-cols-2 2xl:grid-cols-3">
          <section
            v-for="group in evidenceGroups"
            :key="group.label"
            class="rounded border border-slate-200 bg-white p-4"
          >
            <p class="text-xs font-black uppercase tracking-[0.12em] text-slate-400">
              {{ group.label }}
            </p>
            <ul class="mt-3 space-y-3">
              <li
                v-for="item in group.items"
                :key="item"
                class="rounded bg-slate-50 p-3 text-sm font-semibold leading-6 text-slate-700"
              >
                {{ item }}
              </li>
            </ul>
          </section>
        </div>
      </article>
    </section>
  </div>
</template>
