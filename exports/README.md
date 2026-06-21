# GTM Awards Dataset — for ML matching

Export of EU TED **Contract Award Notices (CANs)** and the canonical companies
that won them. This is the historical "who-won-what" signal for training the
tender↔company matching model.

- **Source:** TED v3 API, notice types `can-*`, CPV `45000000` (construction)
  + `72000000` (IT services), last ~24 months.
- **Generated:** 2026-06-17
- **Rows:** 21,015 awards · 15,129 companies · 17 currencies

## Files

| File | What it is |
|---|---|
| `awards_training.csv` | **Start here.** One row per award, already joined to the winning company (no join needed). UTF-8, header row. |
| `companies.csv` | The canonical company dimension (deduplicated legal entities). |

## `awards_training.csv` columns

| Column | Meaning |
|---|---|
| `ted_notice_id` | Award notice id (unique) |
| `cpv_code` | Procurement category (first CPV) |
| `notice_title` | Contract title — **original language** (multilingual) |
| `description` | Full scope text — **original language**; richest semantic signal |
| `procedure_type` | eForms code: `open` / `restricted` / `neg-w-call` / … |
| `nuts_code` | NUTS-3 region of the work (buyer region if work region absent) |
| `buyer_name`, `buyer_country` | The contracting authority |
| `winner_raw_name` | Winner name exactly as printed on this notice |
| `winner_canonical_name` | **Deduplicated** company name (use this to group) |
| `winner_registration_id` | Winner tax/registration id (dedup key; may be blank) |
| `winner_identifier`, `winner_country` | Winner id + country as on the notice |
| `contract_value_eur` | Contract value — **see currency caveat below** |
| `contract_currency` | Currency of the value above |
| `award_date` | Date awarded |
| `n_offers_received` | Number of bids (competition signal) |

## The training structure

One company wins many awards. Group by `winner_canonical_name` (or
`winner_registration_id`) to get each company's history of won notices — the
titles, descriptions, CPV categories, regions, procedure types and values it
actually wins. That distribution is what the model learns to match against.

```sql
-- e.g. each company's award history
SELECT winner_canonical_name, count(*), array_agg(cpv_code), array_agg(nuts_code)
FROM awards_training GROUP BY winner_canonical_name ORDER BY 2 DESC;
```

## Caveats (please read — these bite)

1. **`contract_value_eur` is NOT converted to EUR.** Despite the name, the
   value is in `contract_currency` (17 currencies present — PLN, CHF, …).
   Always read the value + currency together; convert before comparing.
2. **`-1` and `0` are "not disclosed" sentinels**, not real amounts. Treat as
   missing.
3. **Titles/descriptions are multilingual** (each in the notice's own
   language — DE, PL, EL, BG, …). Use a multilingual embedder
   (e.g. `multilingual-e5`), not an English-only one.
4. **`winner_canonical_name` is deduplicated; `winner_raw_name` is not.**
   Dedup is by `registration_id` (tax id) when present, else normalised name.
   Tax-id quality varies, so a few near-duplicate companies may remain.
5. **~25 of the earliest rows predate the enrichment columns** and have blank
   `notice_title` / `description` / `procedure_type` / `nuts_code`. Negligible
   share; filter them out if it matters.

Questions → Swaraj.
