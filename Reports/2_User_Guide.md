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

### 4.6 The agent (power users)

Instead of clicking through the steps, you can give the built-in agent a
plain-language goal — for example, *"find the top 3 supplier matches for the
Krankenhaus Wittmund clinic tender and draft an email for the best one."* The
agent plans and executes the steps and narrates what it did. For safety, actions
that would write data or contact TED run in a **dry-run preview mode by default**;
you opt in explicitly to run them for real.

`[SCREENSHOT: agent run]`

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

---

## 8. Acknowledgment of GenAI Usage

This guide was drafted with the assistance of a Claude-based AI from the team's own
project materials, then reviewed and finalised by the team. The product itself uses
Anthropic Claude for email drafting and orchestration, and open-source models for
matching. `[NEEDS INPUT: confirm wording.]`
