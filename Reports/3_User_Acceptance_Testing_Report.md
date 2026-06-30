# User Acceptance Testing (UAT) Report — GTM Agent

**TUM · CITHN2014 — Foundations and Applications of Generative AI · Project 4**

> **Document status:** DRAFT / structural backbone. Page budget (rubric):
> **≤ 3 pages** excluding title/contents. This document is **mostly a plan until
> the sessions are run** — every **`[NEEDS INPUT]`** marks real data the team must
> collect from ≥ 5 participants before submission. The rubric requires: a user
> case study, a documented survey design, execution with ≥ 5 people, and a result
> analysis.

---

## 1. User Case Study — studying the target user

### 1.1 Target user definition

GTM Agent's target user is a **sales / business-development professional in the
EU construction-technology and infrastructure sector** — the person whose job is
to find relevant public tenders and decide which companies to approach as partners,
subcontractors, or customers. A secondary persona is a **contracting authority /
buyer** who wants a shortlist of credible suppliers for a tender.

### 1.2 Why this user

This user was chosen because the product's value proposition is squarely aimed at
their daily pain: TED publishes tens of thousands of multilingual notices per
week and deliberately hides current bidders, so lead discovery is slow, manual,
and easy to get wrong. A sales user can judge, far better than the team can, three
things the system must get right: (1) are the surfaced leads *actually plausible*
bidders, (2) are the score explanations *trustworthy* enough to act on, and (3) is
the generated outreach *usable* without heavy rewriting.

### 1.3 Recruitment — process, pros, and cons

| Aspect | Detail |
|---|---|
| **Channels** | `[NEEDS INPUT: e.g. TUM entrepreneurship network (UnternehmerTUM / XPRENEURS), TUM CIT alumni in sales roles, direct LinkedIn outreach, personal contacts in construction-tech firms.]` |
| **Target N** | ≥ 5 participants (rubric minimum); aim for 6–7 so 1–2 unusable sessions can be dropped. |
| **Pros of this pool** | Domain-credible feedback; access to people who actually do tender discovery. |
| **Cons / risks** | Hard to schedule busy professionals; small N limits statistical claims; one cold-start (never-seen-the-tool) user recommended to fairly test the User Guide and onboarding. |

> `[NEEDS INPUT: list the actual recruited participants — anonymised IDs (P1…Pn),
> their role, company type/sector, and years of experience. Do NOT include
> personal contact details in the submitted document.]`

---

## 2. User Survey Design — how we study users

### 2.1 Method

A structured **think-aloud** session (~30 minutes per participant), screen-shared,
followed by a short rating questionnaire. Participants narrate their thoughts while
completing three scripted scenarios on a live instance seeded with real TED data.
Sessions are run remotely. `[NEEDS INPUT: confirm format (remote/in-person),
recording consent, and the seeded tenders used.]`

### 2.2 Scenarios (the tasks each user performs)

1. **Lead discovery & justification.** Find a live tender in your sector, identify
   the top-3 most promising candidate companies, and explain why each is credible.
2. **Weight adjustment.** Adjust the matcher so that companies you judge too small
   no longer rank highly; observe whether the ranking responds sensibly.
3. **Email generation & verification.** Generate an outreach email for one of the
   top-3, edit it, rate it, and verify that every factual claim is supported by the
   evidence shown.

4. **Agent mode (natural-language operation).** Instead of clicking through Scenarios
   1–3, state a single plain-language goal (e.g. *"find the top 3 suppliers for the
   Ilmenau school tender and explain why"*). Observe whether the agent resolves the
   right tender (including handling the **disambiguation prompt** when the name is
   partial), whether the streamed progress is understandable, and whether the result's
   **Save results** / **Draft email** actions do what the user expects.

A sixth participant (cold-start, never briefed) runs Scenario 1 only, as a test of
onboarding and the User Guide.

> **Why test agent mode separately.** It is the product's most novel interaction and
> its highest-trust surface (the user delegates the *steps*, not just the analysis), so
> the UAT specifically probes: did the agent ask before doing anything ambiguous, and
> was it transparent about what it did? `[NEEDS INPUT: capture per-participant notes on
> whether they trusted the agent to drive vs. preferred manual clicking.]`

### 2.3 What we evaluate (metrics)

| Dimension | How measured |
|---|---|
| **Task success** | Did the user complete each scenario unaided? (yes / partial / no) |
| **Time on task** | Minutes per scenario |
| **Lead quality** (perceived) | 1–5: "the surfaced companies are plausible bidders" |
| **Explanation trust** | 1–5: "I understand and trust why a company was ranked" |
| **Email usability** | 1–5: "I could send this with minor edits" + count of factual errors found |
| **Agent trust & transparency** | 1–5: "the agent did what I asked and I understood what it did"; + did it ask before any ambiguous action? (yes/no) |
| **Overall usefulness / NPS** | 1–10 likelihood to recommend |
| **Qualitative** | Top friction points, confusions, missing features (open notes) |

> `[TEAM DECISION: settle the dashboard "top-K" (how many candidates to show per
> tender) empirically from this UAT — the plan left K=5 as a default to validate.]`

---

## 3. Performing the Survey — execution

> `[NEEDS INPUT: this whole section is to be filled after the sessions. Summarise
> when sessions ran, with how many participants, on which build/commit, and any
> deviations from the plan. Keep raw per-user data in an appendix or CSV.]`

| Participant | Role / sector | Sc.1 | Sc.2 | Sc.3 | Sc.4 (agent) | Time (min) |
|---|---|:--:|:--:|:--:|:--:|:--:|
| P1 | `[NEEDS INPUT]` | ⬜ | ⬜ | ⬜ | ⬜ | — |
| P2 | `[NEEDS INPUT]` | ⬜ | ⬜ | ⬜ | ⬜ | — |
| P3 | `[NEEDS INPUT]` | ⬜ | ⬜ | ⬜ | ⬜ | — |
| P4 | `[NEEDS INPUT]` | ⬜ | ⬜ | ⬜ | ⬜ | — |
| P5 | `[NEEDS INPUT]` | ⬜ | ⬜ | ⬜ | ⬜ | — |
| P6 (cold-start) | `[NEEDS INPUT]` | ⬜ | n/a | n/a | ⬜ | — |

---

## 4. Result Analysis and Evaluation

> `[NEEDS INPUT: complete after data collection. Structure provided below.]`

### 4.1 Quantitative summary

`[NEEDS INPUT: report mean/median for each metric in §2.3 — task success rate,
average time on task, mean ratings for lead quality / explanation trust / email
usability, overall NPS. A small bar chart per metric is recommended for the PDF.]`

### 4.2 Key findings

`[NEEDS INPUT: 3–5 headline findings, e.g. "users trusted the CPV/location
explanation but wanted the semantic-fit score explained in plain language",
"X% could send the email with only minor edits", "weight sliders were discovered
without prompting by N of M users".]`

### 4.3 Feedback incorporated

For each substantive piece of feedback, state whether the team could act on it
within the project timeline:

| Feedback | Severity | Action taken / planned | Status |
|---|---|---|---|
| `[NEEDS INPUT]` | | | |

### 4.4 Limitations of the UAT

Small sample (N≈5–7) means findings are indicative, not statistically robust;
participants used a seeded instance rather than their own live data; think-aloud
can bias toward verbal users. These are acceptable for an MVP acceptance test and
are noted honestly. `[NEEDS INPUT: adjust to what actually happened.]`

### 4.5 Conclusion

`[NEEDS INPUT: one paragraph — did the product solve a real problem for the target
user? What is the single most important improvement the UAT surfaced?]`

---

## 5. Acknowledgment of GenAI Usage

This report's structure and plan were drafted with a Claude-based AI assistant from
the team's project materials and the course rubric, then completed with real,
team-collected UAT data and reviewed by the team. No participant data was generated
by AI. `[NEEDS INPUT: confirm wording once real data is added.]`
