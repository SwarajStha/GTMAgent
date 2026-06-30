# User Guide — GTM Agent

**TUM · CITHN2014 — Foundations and Applications of Generative AI · Project 4**

> **Document status:** DRAFT / structural backbone. Page budget (rubric):
> **≤ 5 pages** excluding title/contents. This guide should be visually appealing,
> short, and to the point — after reading it, a user should understand the product
> *without running it*. Replace every **`[SCREENSHOT]`** marker with a real,
> high-resolution capture and every **`[NEEDS INPUT]`** with a real value before
> submission.

---

## 1. What is GTM Agent?

GTM Agent is a sales-intelligence assistant for companies that bid on, or sell
into, **EU public construction and infrastructure tenders**. It watches the EU's
official procurement journal (TED), finds tenders that match your business, tells
you **which companies are the most credible bidders** to pursue — and explains
*why* — and then drafts a ready-to-edit outreach email in which **every factual
claim is backed by a verifiable source**.

In one sentence: **GTM Agent turns the public flood of EU tenders into a short,
ranked, explained list of sales leads with outreach drafts attached.**

- 🌍 **Live access:** `[NEEDS INPUT: landing page / hosted demo URL, or "runs
  locally — see §6".]`
- 🎥 **60-second pitch video:** `[NEEDS INPUT: link]`

`[SCREENSHOT: dashboard home / hero view]`

---

## 2. Who is it for?

| Role | What they get from GTM Agent |
|---|---|
| **Sales / Business-Development analyst** (primary) | Discovers live tenders in their sector, ranks candidate partner/competitor companies, and generates supplier outreach emails. |
| **Buyer / Contracting authority** (secondary) | Receives a digest recommending the strongest supplier matches for a tender. |
| **Operator / Power user** | Runs the whole pipeline from a single natural-language instruction via the built-in agent. |

---

## 3. The core workflow

The dashboard follows a simple three-column flow:

```
   Active Tenders   →   Lead Analysis (ranked matches)   →   Email Draft
```

1. **Browse tenders** that match your configured sectors.
2. **Open a tender** to see its details and run the matcher.
3. **Review ranked companies** with an explainable score for each.
4. **Generate an outreach email** (or a buyer digest) and edit it.
5. **Rate the result** 👍/👎 — the system learns from your feedback.

**Agent mode (shortcut):** prefer to just *say what you want*? The built-in agent does
steps 1–4 from a single sentence and asks you to confirm if anything is ambiguous —
see §4.6.

`[SCREENSHOT: three-column workflow]`

---

## 4. Features

### 4.1 Tender discovery

The **Tenders** view lists live EU contract notices filtered to your sectors
(by CPV code — e.g. construction `45000000`, IT/services `72000000`). Each row
shows the title, buyer, country, CPV codes, and deadline. Click any tender to open
its detail page, including the raw TED data for traceability.

`[SCREENSHOT: Tenders list + detail]`

### 4.2 Lead matching with explanations

From a tender, click **Find matches** (or call `Run matching`). GTM Agent scores
a pool of ~15,000 candidate companies — built from two years of past EU award
winners — and returns the top matches ranked by a calibrated **win-probability**.

Every match shows a transparent breakdown:

- **Semantic fit** — how closely the company's past work matches this tender.
- **Qualification (CPV) fit** — overlap of procurement categories.
- **Budget fit** — whether the company's typical contract size fits the tender.
- **Location fit** — geographic match (region/country).
- **Win-probability** — the trained model's combined estimate, with the
  top contributing factors named (e.g. *"CPV category +1.56, region +0.56"*).

This means you never get a black-box ranking — you can see *why* a company is
recommended.

`[SCREENSHOT: ranked matches with score breakdown]`

### 4.3 Adjustable weighting

`[NEEDS INPUT / TEAM DECISION: the weight sliders are currently partly cosmetic —
confirm whether real-time, client-side re-ranking is wired before describing it as
a live feature. If wired:]` Move a slider (e.g. raise the importance of location)
and the ranking re-sorts instantly, with no waiting — useful when you know
something the data doesn't (e.g. a company is too small to deliver).

`[SCREENSHOT: weight sliders]`

### 4.4 Evidence-grounded email generation

Pick a company and click **Generate email**. GTM Agent writes a tailored outreach
draft using Claude — but under a strict rule: it may only state facts drawn from a
pre-extracted **evidence list** (the tender's real TED ID, CPV codes, deadline,
the company's award history, and the match scores). Any draft that introduces an
unsupported claim is flagged for review rather than shown as final. The email also
**matches the tender's language automatically** (a German tender yields a German
email).

You can also generate a **buyer-facing digest** for a tender: a short summary
recommending its strongest supplier matches.

`[SCREENSHOT: generated email with evidence panel]`

### 4.5 Feedback that improves results

Rate any match or email 👍 / 👎. Positive and negative feedback retrains the
matcher's internal weighting, so the leads it surfaces drift over time toward what
your team actually considers a good lead.

`[SCREENSHOT: feedback control]`

### 4.6 Agent mode (power users)

Instead of clicking through the steps, you can give the built-in **agent** a
plain-language goal — for example, *"find the top 3 supplier matches for the Ilmenau
school tender and explain why."* The agent figures out the steps, runs them, and shows
you a **live activity log** as it works ("Looking up the tender…", "Ranking the
supplier pool…", "Writing the summary…").

What makes it reliable and safe to use:

- **It understands any way you name a tender.** Give it the internal id, the public
  **TED notice number** (e.g. `420398-2026`), or just words from the title. If your
  wording matches several tenders, the agent **stops and asks you to pick one** from a
  short list — then continues from your choice (you never have to restate the goal).
- **The ranking is the trained model, not the chatbot.** The agent runs the same
  matching pipeline the manual flow uses; the AI only decides *which step to run* and
  *explains the result*. It cannot invent a company.
- **It works on your local data and won't surprise you.** By default it only uses
  tenders/companies already loaded — the **"Offline mode"** toggle (on by default)
  means it makes no live calls to the EU TED service.
- **One-click follow-ups.** When the agent finishes, you can **Save results** (the
  ranked suppliers + explanation are stored against that tender and viewable later
  under *Saved analyses*) and **Draft email** to any of the top-3 matches — you pick
  🥇, 🥈, or 🥉; it confirms *"Email written with [company]"* and links you to the
  Emails screen.

`[SCREENSHOT: agent run — live activity log + disambiguation picker]`
`[SCREENSHOT: agent result — Save results + 🥇/🥈/🥉 Draft-email buttons]`

---

## 5. A typical session (walkthrough)

1. Open the **Tenders** view; spot *"Czechia – Carriageway resurfacing works –
   D11."*
2. Open it and click **Find matches.** The top results are genuine Czech road
   builders (EUROVIA, STRABAG, SWIETELSKY).
3. Open the #1 match; read its score breakdown and evidence.
4. Click **Generate email**; review the draft — every claim links to its source.
5. Edit, then 👍 the draft. Done — a sourced lead and outreach in under a minute.

---

## 6. Getting started

`[NEEDS INPUT: if a hosted demo exists, this section should simply be the URL +
login. The steps below are the local-run fallback for graders/teammates.]`

**Prerequisites:** Docker Desktop, Python 3.11, Node 20.

```sh
# 1. Start everything
cp backend/.env.example backend/.env     # then set ANTHROPIC_API_KEY
docker compose up --build

# 2. Open the app
#    Dashboard:  http://localhost:5173
#    API + docs: http://localhost:8000/docs
```

For the full local development loop, ingestion CLI, and database access, see the
project `README.md`.

---

## 7. Frequently asked questions

**Does GTM Agent send emails automatically?** No — it only drafts them for your
review. You stay in control.

**Where does the company data come from?** Exclusively from public EU procurement
records (TED contract and award notices). No private or scraped personal data.

**Can it handle other languages?** Yes — tenders and companies across the EU's
languages are handled natively by a multilingual model; emails are written in the
tender's language.

**What sectors are covered?** Construction and IT/services by default, configurable
by CPV code. `[NEEDS INPUT: confirm the final shipped sector list.]`

**Can the agent take actions on its own?** No surprising ones. The agent ranks and
explains using data already in the system, asks you before proceeding when a request is
ambiguous, and never contacts the EU TED service in the default "Offline mode" — and it
never sends an email (it only drafts).

---

## 8. Acknowledgment of GenAI Usage

This guide was drafted with the assistance of a Claude-based AI from the team's own
project materials, then reviewed and finalised by the team. The product itself uses
Anthropic Claude for email drafting and orchestration, and open-source models for
matching. `[NEEDS INPUT: confirm wording.]`
