# -*- coding: utf-8 -*-
"""
exports_ml_pipeline.py  v5
==========================
Tender → Top-3 Company Matching Pipeline

Improvements over v1-v4:
  1. Company name normalisation  (case/punct/suffix + fuzzy + consortium)
  2. Hard negative mining        (same country, CPV, value band)
  3. Logistic Regression ranker  (replaces LambdaRank — all 10 features actually used)
  4. Leave-one-out leakage guard (profiles from all awards, test tender excluded at eval)
  5. Two-stage retrieval         (hard filter CPV+country+budget → LR scoring)
  6. Multi-level CPV/NUTS        (4-digit, 2-digit / exact, country-level)
  7. Value range features        (log proximity to median + historical min-max check)
  8. Richer evaluation           (Hit@1/3/5, pool coverage, null explanation)

Run:
    py -3 run_pipeline.py
"""

from __future__ import annotations

import csv
import json
import random
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

# NOTE: the unbuffered-stdout reopen that used to live here was moved into main()
# (see _force_line_buffered_stdio). Reopening sys.stdout/sys.stderr on their fds at
# IMPORT time is hostile to pytest's output capture — it takes ownership of pytest's
# capture file descriptors and closes them when collected, crashing collection with
# "OSError: [Errno 9] Bad file descriptor". The G20 parity test importorskips this
# module, so import must stay side-effect-free.

import numpy as np
import joblib
from rapidfuzz import fuzz
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler

# Pre-import torch/sentence-transformers at module level (Windows DLL fix)
USE_MINILM = True
_MINILM_AVAILABLE = False
if USE_MINILM:
    try:
        import torch  # noqa: F401
        from sentence_transformers import SentenceTransformer as _ST
        _MINILM_AVAILABLE = True
    except (ImportError, OSError) as _e:
        print(f"[Warning] MiniLM unavailable ({_e}), falling back to TF-IDF")
        USE_MINILM = False

# ── Configuration ────────────────────────────────────────────
EXPORTS_DIR    = Path(__file__).parent / "exports"
AWARDS_PATH    = EXPORTS_DIR / "awards_training.csv"
COMPANIES_PATH = EXPORTS_DIR / "companies.csv"
OUTPUT_PATH    = EXPORTS_DIR / "top3_results.json"
REPORT_PATH    = EXPORTS_DIR / "model_report.json"
MODEL_PATH     = EXPORTS_DIR / "company_matcher.joblib"
# Plain-JSON model params for the in-app matcher (app/matching/lr_weights.py):
# coefficients alone are not enough to reproduce predict_proba — the LR was fit
# on StandardScaler-normalised features, so the app also needs the intercept and
# the scaler mean/scale. This file is the contract between v5 (trains) and the
# app (serves), so the app doesn't have to load the sklearn-version-coupled joblib.
MODEL_PARAMS_PATH = EXPORTS_DIR / "model_params.json"

MINILM_MODEL   = "paraphrase-multilingual-MiniLM-L12-v2"
RANDOM_STATE   = 42
NEG_RATIO      = 5          # negatives per positive
TRAIN_FRAC     = 0.80       # chronological split
TOP_K          = 5          # evaluate Hit@1/3/5
# Fraction of awards (chronologically earliest) used to TRAIN the LR; the rest are
# held out to evaluate honest Hit@k on later/unseen tenders. This is a leakage-safe
# split, not a resource cap. Raised 0.50→0.80 (G23) to give the shipped model ~60%
# more training pairs while still holding out ~20% (~4k awards) for the eval that
# produces the reported Hit@k. Company profiles are still built from ALL awards.
TRAIN_SAMPLE   = 0.80       # fraction of awards for training
TEST_SAMPLE    = 500        # tenders to predict at the end

RATES_TO_EUR = {
    "EUR":1.0,"PLN":0.23,"CZK":0.040,"HUF":0.0026,"RON":0.20,
    "BGN":0.51,"HRK":0.133,"DKK":0.134,"SEK":0.088,"NOK":0.087,
    "CHF":1.06,"GBP":1.17,"USD":0.92,"TRY":0.028,"RSD":0.0085,
    "MKD":0.0163,"ALL":0.0105,
}

# Train/serve sync (G20): this feature math has a serving twin in
# backend/app/matching/features.py. Change a feature here → port it there → the app
# regenerates model_params.json from this script. Parity is enforced by
# backend/tests/matching/test_feature_parity_v5.py (this module vs the app, output
# for output) and test_feature_contract.py (FEATURE_NAMES vs the exported artifact).
# Deliberate differences the parity test allows: the app's cpv_features takes a LIST
# of tender CPVs (any-match) and its competition_score is fixed UNKNOWN (a future
# tender's offer count can't be known at prediction time).
FEATURE_NAMES = [
    "semantic_score",
    "cpv_4digit_score", "cpv_2digit_score",
    "nuts_exact_score", "nuts_country_score",
    "value_score", "value_in_range_score",
    "country_match_score",
    "company_size_score",
    "competition_score",
]

# ── 1. Company name normalisation ─────────────────────────────

# Legal-form suffixes to strip (order matters — longest first)
_SUFFIXES = sorted([
    "gmbh & co. kg","gmbh & co kg","sp. z o.o.","s. de r.l. de c.v.",
    "s.a.u.","s.l.u.","s.r.l.","s.p.a.","s.a.","s.l.","s.c.","nv","bv",
    "a/s","as","oy","ab","asa","llp","llc","plc","ltd","inc","corp",
    "gmbh","ag","kg","ohg","ug","kgaa","se","mbh",
    "ood","ead","ad","jsc","ooo","zao","pao",
    "srl","snc","sas","eurl","sarl","sa","scs",
    "sl","sau","sc","cb","slu","aie","utp","aiv",
    "sp","spzoo","sa","zrt","kft","bt","nyrt",
    "as","aps","is","ehf","hf",
], key=len, reverse=True)

_CONSORTIUM_MARKERS = re.compile(
    r"\b(ute|jv|joint venture|consortium|arbeitsgemeinschaft|arge|ativ|groupement|"
    r"grouping|unión temporal|consorcio|konsortium|konsortsium)\b",
    re.IGNORECASE,
)

def _strip_suffix(s: str) -> str:
    for sfx in _SUFFIXES:
        if s.endswith(sfx):
            s = s[: -len(sfx)].rstrip(" ,.-&")
    return s.strip()

def normalize_name(raw: str) -> str:
    """Lowercase, remove punctuation/suffixes, return canonical key."""
    s = raw.lower().strip()
    s = re.sub(r"[^\w\s]", " ", s)          # punctuation → space
    s = re.sub(r"\s+", " ", s).strip()
    s = _strip_suffix(s)
    return s

def is_consortium(name: str) -> bool:
    return bool(_CONSORTIUM_MARKERS.search(name))

def consortium_members(name: str) -> list[str]:
    """Split 'A - B' or 'A / B' or 'UTE A B' into member tokens."""
    parts = re.split(r"\s*[-/|]\s*|\s+y\s+|\s+und\s+|\s+and\s+", name, flags=re.I)
    return [p.strip() for p in parts if len(p.strip()) > 3]

def names_match(a: str, b: str, threshold: int = 85) -> bool:
    """Fuzzy match two normalised names."""
    if a == b:
        return True
    return fuzz.token_sort_ratio(a, b) >= threshold

def build_name_index(company_names: list[str]) -> dict[str, str]:
    """Map normalize_name(n) → canonical n for fast lookup."""
    return {normalize_name(n): n for n in company_names}

def resolve_winner(raw_winner: str, name_index: dict[str, str],
                   company_names: list[str]) -> Optional[str]:
    """
    Try to match raw_winner against the company pool.
    1. Exact normalised match.
    2. Fuzzy match (threshold 85).
    3. Consortium: check if any member matches.
    Returns canonical company name or None.
    """
    norm = normalize_name(raw_winner)

    # 1. Exact normalised
    if norm in name_index:
        return name_index[norm]

    # 2. Fuzzy
    best_score, best_name = 0, None
    for canon_norm, canon in name_index.items():
        score = fuzz.token_sort_ratio(norm, canon_norm)
        if score > best_score:
            best_score, best_name = score, canon
    if best_score >= 85:
        return best_name

    # 3. Consortium members
    if is_consortium(raw_winner):
        for member in consortium_members(raw_winner):
            m_norm = normalize_name(member)
            if m_norm in name_index:
                return name_index[m_norm]
            for cn, cv in name_index.items():
                if fuzz.token_sort_ratio(m_norm, cn) >= 85:
                    return cv

    return None


# ── 2. Load data ──────────────────────────────────────────────

def load_csv(path: Path) -> list[dict]:
    with path.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))

# ISO 3166-1 alpha-3 → alpha-2 (for NUTS prefix)
_ISO3_TO_ISO2 = {
    "AUT":"AT","BEL":"BE","BGR":"BG","HRV":"HR","CYP":"CY","CZE":"CZ",
    "DNK":"DK","EST":"EE","FIN":"FI","FRA":"FR","DEU":"DE","GRC":"GR",
    "HUN":"HU","IRL":"IE","ITA":"IT","LVA":"LV","LTU":"LT","LUX":"LU",
    "MLT":"MT","NLD":"NL","POL":"PL","PRT":"PT","ROU":"RO","SVK":"SK",
    "SVN":"SI","ESP":"ES","SWE":"SE","GBR":"GB","NOR":"NO","CHE":"CH",
    "TUR":"TR","SRB":"RS","MKD":"MK","ALB":"AL","UKR":"UA","MDA":"MD",
    "BLR":"BY","RUS":"RU","USA":"US","CAN":"CA","AUS":"AU","JPN":"JP",
    "CHN":"CN","IND":"IN","BRA":"BR","ZAF":"ZA","ISL":"IS","LIE":"LI",
}

def load_companies_catalog() -> dict[str, dict]:
    """
    Load companies.csv → dict keyed by canonical_name.
    Returns {name: {country_iso2, nuts_prefix}} for static company info.
    """
    if not COMPANIES_PATH.exists():
        return {}
    catalog: dict[str, dict] = {}
    for row in load_csv(COMPANIES_PATH):
        name = row.get("canonical_name","").strip()
        if not name:
            continue
        iso3    = row.get("country","").strip().upper()
        iso2    = _ISO3_TO_ISO2.get(iso3, iso3[:2] if len(iso3) >= 2 else "")
        catalog[name] = {"country_iso2": iso2, "nuts_prefix": iso2}
        # Also index by resolution_key for fuzzy lookup
        rkey = row.get("resolution_key","").strip()
        if rkey and rkey != name:
            catalog[rkey] = {"country_iso2": iso2, "nuts_prefix": iso2}
    print(f"[Catalog] Loaded {len(catalog)} entries from companies.csv", flush=True)
    return catalog

def to_eur(value_str: str, currency: str) -> Optional[float]:
    try:
        v = float(value_str)
    except (ValueError, TypeError):
        return None
    if v <= 0:
        return None
    rate = RATES_TO_EUR.get(currency.strip().upper())
    return v * rate if rate else None

def parse_date(s: str) -> Optional[str]:
    if not s:
        return None
    return s.strip()[:10]   # YYYY-MM-DD


# ── 3. Build company profiles ─────────────────────────────────

def build_company_profiles(awards: list[dict]) -> tuple[dict[str, dict], dict[str, dict]]:
    """
    Build company profiles from awards.
    Returns (profiles, award_texts) where award_texts[company][tid] = text.
    """
    profiles: dict[str, dict] = defaultdict(lambda: {
        "texts": [], "nuts_codes": set(),
        "cpv_codes": set(), "values_eur": [],
        "countries": set(),
    })
    award_texts: dict[str, dict[str, str]] = defaultdict(dict)

    for row in awards:
        name = row["winner_canonical_name"].strip()
        if not name:
            continue
        tid     = row.get("ted_notice_id", "")
        text    = " ".join(p for p in [row.get("notice_title",""), row.get("description","")] if p.strip())
        nuts    = row.get("nuts_code","").strip().upper()
        cpv     = row.get("cpv_code","").strip()
        country = row.get("winner_country","").strip().upper()
        v       = to_eur(row.get("contract_value_eur",""), row.get("contract_currency","EUR"))

        if text.strip():
            profiles[name]["texts"].append(text)
            if tid:
                award_texts[name][tid] = text
        if nuts:
            profiles[name]["nuts_codes"].add(nuts)
        if cpv:
            profiles[name]["cpv_codes"].add(cpv)
        if country:
            profiles[name]["countries"].add(country)
        if v:
            profiles[name]["values_eur"].append(v)

    result = {}
    for name, p in profiles.items():
        vals = p["values_eur"]
        result[name] = {
            "profile_text":     " ".join(p["texts"])[:4000],
            "nuts_prefixes":    list(p["nuts_codes"]),
            "cpv_prefixes":     list(p["cpv_codes"]),
            "countries":        list(p["countries"]),
            "median_value_eur": float(np.median(vals)) if vals else None,
            "min_value_eur":    float(np.min(vals))    if vals else None,
            "max_value_eur":    float(np.max(vals))    if vals else None,
            "award_count":      len(p["texts"]),
        }
    print(f"[Profiles] Built {len(result)} company profiles", flush=True)
    return result, dict(award_texts)


# ── 4. Semantic scorer ────────────────────────────────────────

class SemanticScorer:
    def __init__(self, company_profiles: dict[str, dict]) -> None:
        self._profiles = company_profiles
        self._company_names = list(company_profiles.keys())
        self._embeddings: dict[str, np.ndarray] = {}

        if USE_MINILM:
            print(f"[MiniLM] Loading {MINILM_MODEL} …", flush=True)
            self._model = _ST(MINILM_MODEL)
            self._tfidf = None
        else:
            from sklearn.feature_extraction.text import TfidfVectorizer
            print("[Semantic] TF-IDF mode", flush=True)
            self._model = None
            self._tfidf = TfidfVectorizer(ngram_range=(1,2), sublinear_tf=True, max_features=50_000)

    def build_company_embeddings(self) -> None:
        texts = [self._profiles[n]["profile_text"] or "unknown" for n in self._company_names]
        if USE_MINILM:
            print(f"[MiniLM] Encoding {len(texts)} company profiles …", flush=True)
            embs = self._model.encode(texts, batch_size=256, show_progress_bar=True,
                                      normalize_embeddings=True, convert_to_numpy=True)
            for name, emb in zip(self._company_names, embs):
                self._embeddings[name] = emb
        else:
            self._tfidf.fit(texts)
            vecs = self._tfidf.transform(texts)
            for i, name in enumerate(self._company_names):
                self._embeddings[name] = np.asarray(vecs[i].todense()).flatten()

    def get_clean_embedding(self, company: str, exclude_tid: str,
                            award_texts: dict[str, dict[str, str]]) -> np.ndarray:
        """Return company embedding with the specific tender excluded (leave-one-out)."""
        contrib = award_texts.get(company, {})
        if exclude_tid not in contrib:
            return self._embeddings[company]  # tender not in profile, no adjustment needed
        clean_texts = [t for tid, t in contrib.items() if tid != exclude_tid]
        if not clean_texts:
            return np.zeros_like(self._embeddings[company])  # company only won this one tender
        clean_profile = " ".join(clean_texts)[:4000]
        if USE_MINILM:
            emb = self._model.encode([clean_profile], normalize_embeddings=True,
                                     convert_to_numpy=True)[0]
        else:
            vec = self._tfidf.transform([clean_profile])
            emb = np.asarray(vec[0].todense()).flatten()
        return emb

    def batch_encode_texts(self, texts: list[str]) -> np.ndarray:
        if USE_MINILM:
            return self._model.encode(texts, batch_size=256, show_progress_bar=True,
                                      normalize_embeddings=True, convert_to_numpy=True)
        vecs = self._tfidf.transform(texts)
        return np.array([np.asarray(vecs[i].todense()).flatten() for i in range(len(texts))])

    @property
    def company_emb_matrix(self) -> np.ndarray:
        """All company embeddings stacked as (n_companies, dim)."""
        if not hasattr(self, "_matrix"):
            self._matrix = np.array([self._embeddings[n] for n in self._company_names])
        return self._matrix


# ── 5. Feature engineering ────────────────────────────────────

def _norm_cpv(cpv: str) -> str:
    """Normalise CPV: keep only digits, pad/truncate to 8."""
    digits = re.sub(r"\D", "", cpv)
    return digits[:8].ljust(8, "0")

def cpv_features(tender_cpv: str, company_cpv_list: list[str]) -> tuple[float, float, float]:
    """
    Multi-level CPV match: 8-digit / 4-digit / 2-digit.
    Returns (cpv_8, cpv_4, cpv_2) each 1.0=match / 0.0=no match / 0.5=unknown.
    CPV codes are normalised (digits only) before comparison.
    """
    if not tender_cpv or not company_cpv_list:
        return 0.5, 0.5, 0.5
    tn = _norm_cpv(tender_cpv)
    t8, t4, t2 = tn[:8], tn[:4], tn[:2]
    normed = [_norm_cpv(c) for c in company_cpv_list]
    c8_set = {c[:8] for c in normed}
    c4_set = {c[:4] for c in normed}
    c2_set = {c[:2] for c in normed}
    return (
        1.0 if t8 in c8_set else 0.0,
        1.0 if t4 in c4_set else 0.0,
        1.0 if t2 in c2_set else 0.0,
    )

def nuts_features(tender_nuts: str, company_nuts_list: list[str]) -> tuple[float, float]:
    """
    Multi-level NUTS match: exact NUTS-2 (4 chars) and country (2 chars).
    Returns (nuts_exact, nuts_country) each 1.0=match / 0.0=no match / 0.5=unknown.
    """
    if not tender_nuts or not company_nuts_list:
        return 0.5, 0.5
    t2  = tender_nuts[:2].upper()
    t4  = tender_nuts[:4].upper()
    c2s = {n[:2].upper() for n in company_nuts_list}
    c4s = {n[:4].upper() for n in company_nuts_list}
    return (
        1.0 if t4 in c4s else 0.0,
        1.0 if t2 in c2s else 0.0,
    )

def value_features(tender_eur: Optional[float],
                   company_median: Optional[float],
                   company_min: Optional[float] = None,
                   company_max: Optional[float] = None) -> tuple[float, float]:
    """
    value_score: continuous proximity (log ratio to median).
    value_in_range: 1.0 if tender value falls within company's historical min-max range.
    """
    if tender_eur is None or company_median is None or company_median <= 0:
        return 0.5, 0.5
    log_ratio = abs(np.log10(max(tender_eur / company_median, 1e-6)))
    v_score   = float(np.clip(1.0 - 0.25 * log_ratio, 0.0, 1.0))
    # value_in_range: is tender within [min*0.1, max*10] (allow 1-decade slack)
    if company_min is not None and company_max is not None:
        in_range = 1.0 if (company_min * 0.1) <= tender_eur <= (company_max * 10) else 0.0
    else:
        in_range = v_score  # fallback to proximity if no range data
    return v_score, in_range

def country_match_score(tender_country: str, company_countries: list[str]) -> float:
    """1.0 if tender buyer country matches any of company's historical winner countries."""
    if not tender_country or not company_countries:
        return 0.5
    tc = tender_country.strip().upper()
    return 1.0 if tc in [c.upper() for c in company_countries] else 0.0

def company_size_score(award_count: int) -> float:
    """Normalised company activity: log scale, capped at 100 awards → 1.0."""
    if award_count <= 0:
        return 0.0
    return float(np.clip(np.log1p(award_count) / np.log1p(100), 0.0, 1.0))

def competition_score(n_offers_str: str) -> float:
    try:
        n = int(n_offers_str)
    except (ValueError, TypeError):
        return 0.5
    return float(np.clip(1.0 / max(n, 1), 0.05, 1.0)) if n > 0 else 0.8

def build_fv(sem: float,
             cpv4: float, cpv2: float,
             nuts_exact: float, nuts_country: float,
             val: float, val_range: float,
             country: float,
             size: float,
             comp: float) -> np.ndarray:
    return np.array([sem, cpv4, cpv2, nuts_exact, nuts_country,
                     val, val_range, country, size, comp], dtype=float)


# ── 6. Hard negative mining ───────────────────────────────────

def build_hard_negative_index(awards: list[dict]) -> dict:
    """
    Index companies by (country, cpv_prefix, value_band) for hard negatives.
    value_band = log10(value) rounded to nearest 0.5.
    """
    idx: dict[tuple, list[str]] = defaultdict(list)
    for row in awards:
        name    = row["winner_canonical_name"].strip()
        country = row.get("winner_country","").strip().upper()
        cpv     = row.get("cpv_code","").strip()[:2]
        v       = to_eur(row.get("contract_value_eur",""), row.get("contract_currency","EUR"))
        band    = round(np.log10(v) * 2) / 2 if v and v > 0 else None
        if name and country:
            idx[(country, cpv, band)].append(name)
            idx[(country, cpv, None)].append(name)
            idx[(country, None, None)].append(name)
    return dict(idx)

def sample_hard_negatives(
    winner: str,
    tender_country: str,
    tender_cpv: str,
    tender_eur: Optional[float],
    hard_idx: dict,
    all_companies: list[str],
    rng: random.Random,
    n: int,
    company_profiles: dict,
) -> list[str]:
    """
    Sample negatives: prefer same-country + same-CPV + similar-value,
    fall back to same-country, then random.
    """
    band = round(np.log10(tender_eur) * 2) / 2 if tender_eur and tender_eur > 0 else None
    country = tender_country.strip().upper()
    cpv     = tender_cpv.strip()[:2]

    pool: list[str] = []
    # Tier 1: same country + CPV + value band
    pool = [c for c in hard_idx.get((country, cpv, band), [])
            if c != winner and c in company_profiles]
    # Tier 2: same country + CPV
    if len(pool) < n:
        pool += [c for c in hard_idx.get((country, cpv, None), [])
                 if c != winner and c in company_profiles and c not in pool]
    # Tier 3: same country
    if len(pool) < n:
        pool += [c for c in hard_idx.get((country, None, None), [])
                 if c != winner and c in company_profiles and c not in pool]
    # Tier 4: random from all
    if len(pool) < n:
        pool += [c for c in rng.sample(all_companies, min(n*3, len(all_companies)))
                 if c != winner and c not in pool]

    # Deduplicate and sample
    seen = set()
    deduped = []
    for c in pool:
        if c not in seen:
            seen.add(c)
            deduped.append(c)
    return deduped[:n]


# ── 7. Build ranked training groups ──────────────────────────

def build_training_groups(
    awards: list[dict],
    company_profiles: dict[str, dict],
    scorer: SemanticScorer,
    hard_idx: dict,
    name_index: dict[str, str],
    tender_emb_cache: dict[str, np.ndarray],
    award_texts: dict[str, dict[str, str]],
    neg_ratio: int = NEG_RATIO,
    seed: int = RANDOM_STATE,
) -> tuple[list[dict], dict[str, np.ndarray]]:
    """
    Build (query_group, relevance_label, features) for LR training.
    One group = one tender. Positive company label=1, negatives label=0.
    Also returns updated tender_emb_cache.
    """
    rng = random.Random(seed)
    all_companies = list(company_profiles.keys())
    company_emb_matrix = scorer.company_emb_matrix

    records = []
    skipped_no_winner = 0
    skipped_no_profile = 0

    print(f"[Groups] Building ranked groups from {len(awards)} awards …", flush=True)

    # Batch-encode unique tender texts
    unique_tids  = list({r["ted_notice_id"]: r for r in awards}.keys())
    unique_rows  = {r["ted_notice_id"]: r for r in awards}
    missing_tids = [t for t in unique_tids if t not in tender_emb_cache]

    if missing_tids:
        missing_texts = [
            " ".join(filter(None, [unique_rows[t].get("notice_title",""),
                                   unique_rows[t].get("description","")]))
            for t in missing_tids
        ]
        print(f"[Groups] Batch-encoding {len(missing_tids)} tender texts …", flush=True)
        embs = scorer.batch_encode_texts(missing_texts)
        for tid, emb in zip(missing_tids, embs):
            tender_emb_cache[tid] = emb

    # Company name index for fuzzy resolution
    for i, row in enumerate(awards):
        if i % 2000 == 0:
            print(f"  {i}/{len(awards)} …", flush=True)

        raw_winner = row["winner_canonical_name"].strip()
        winner = resolve_winner(raw_winner, name_index, all_companies)

        if winner is None:
            skipped_no_winner += 1
            continue
        if winner not in company_profiles:
            skipped_no_profile += 1
            continue

        tid          = row["ted_notice_id"]
        tender_eur   = to_eur(row.get("contract_value_eur",""), row.get("contract_currency","EUR"))
        tender_nuts  = row.get("nuts_code","")
        tender_cpv   = row.get("cpv_code","")
        tender_cntry = row.get("buyer_country","")
        award_date   = row.get("award_date","")

        t_emb = tender_emb_cache.get(tid)

        def sem(cname: str) -> float:
            c_emb = scorer._embeddings.get(cname)
            if t_emb is None or c_emb is None:
                return 0.5
            return float(np.clip(np.dot(t_emb, c_emb), 0.0, 1.0))

        def make_fv(cname: str) -> np.ndarray:
            prof = company_profiles[cname]
            _c8, c4, c2 = cpv_features(tender_cpv, prof["cpv_prefixes"])
            ne, nc      = nuts_features(tender_nuts, prof["nuts_prefixes"])
            vs, vr      = value_features(tender_eur, prof["median_value_eur"],
                                         prof.get("min_value_eur"), prof.get("max_value_eur"))
            return build_fv(
                sem(cname),
                c4, c2, ne, nc, vs, vr,
                country_match_score(tender_cntry, prof["countries"]),
                company_size_score(prof["award_count"]),
                0.5,
            )

        records.append({
            "label": 1, "tender_id": tid, "award_date": award_date,
            "company": winner, "fv": make_fv(winner),
        })

        # Hard negatives
        negatives = sample_hard_negatives(
            winner, tender_cntry, tender_cpv, tender_eur,
            hard_idx, all_companies, rng, neg_ratio, company_profiles,
        )
        for neg in negatives:
            records.append({
                "label": 0, "tender_id": tid, "award_date": award_date,
                "company": neg, "fv": make_fv(neg),
            })

    pos = sum(1 for r in records if r["label"] == 1)
    print(f"[Groups] Total records: {len(records)} ({pos} pos, {len(records)-pos} neg)", flush=True)
    print(f"[Groups] Skipped: {skipped_no_winner} (winner not in pool), "
          f"{skipped_no_profile} (no profile)", flush=True)
    return records, tender_emb_cache


# ── 8. Leakage-safe chronological split ──────────────────────

def chronological_group_split(
    records: list[dict],
    train_frac: float = TRAIN_FRAC,
) -> tuple[list[dict], list[dict]]:
    """
    Split by unique tender (group), not by individual record.
    Ensures no test tender's info leaks into training set.
    """
    # Get unique tenders sorted by date
    tender_dates: dict[str, str] = {}
    for r in records:
        tid = r["tender_id"]
        if tid not in tender_dates or r["award_date"] < tender_dates[tid]:
            tender_dates[tid] = r["award_date"]

    sorted_tids = sorted(tender_dates.keys(), key=lambda t: tender_dates[t])
    n_cut = max(1, int(len(sorted_tids) * train_frac))
    train_tids = set(sorted_tids[:n_cut])
    test_tids  = set(sorted_tids[n_cut:])

    train = [r for r in records if r["tender_id"] in train_tids]
    test  = [r for r in records if r["tender_id"] in test_tids]
    print(f"[Split] {len(train_tids)} train tenders / {len(test_tids)} test tenders "
          f"(records: {len(train)} / {len(test)})", flush=True)
    return train, test


# ── 9. Logistic Regression ranker ────────────────────────────

def train_lr(
    train_records: list[dict],
    val_records: list[dict],
) -> tuple[LogisticRegression, StandardScaler]:
    """
    Train a Logistic Regression on (tender, company) pairs.
    Label=1 for the true winner, label=0 for hard negatives.
    Returns (model, scaler) — scaler needed at inference time.
    """
    X_tr = np.array([r["fv"] for r in train_records])
    y_tr = np.array([r["label"] for r in train_records], dtype=int)
    X_va = np.array([r["fv"] for r in val_records])
    y_va = np.array([r["label"] for r in val_records], dtype=int)

    scaler = StandardScaler()
    X_tr_s = scaler.fit_transform(X_tr)
    X_va_s = scaler.transform(X_va)

    print("\n[LR] Training Logistic Regression …", flush=True)
    model = LogisticRegression(
        C=1.0,
        max_iter=1000,
        class_weight="balanced",   # compensates for 1:5 pos/neg ratio
        random_state=RANDOM_STATE,
        n_jobs=-1,
    )
    model.fit(X_tr_s, y_tr)

    val_acc = model.score(X_va_s, y_va)
    print(f"[LR] Val accuracy: {val_acc:.4f}", flush=True)
    print(f"[LR] Val positives: {y_va.sum()} / {len(y_va)}", flush=True)

    print("\n[LR] Feature coefficients:", flush=True)
    for feat, coef in zip(FEATURE_NAMES, model.coef_[0]):
        print(f"  {feat:25s}: {coef:+.4f}", flush=True)

    return model, scaler


# ── 10. Evaluation ────────────────────────────────────────────

def hard_filter(
    tender_cpv: str,
    tender_country: str,
    tender_eur: Optional[float],
    company_profiles: dict[str, dict],
    max_candidates: int = 200,
) -> list[str]:
    """
    Stage 1: narrow 14k companies → ≤max_candidates using CPV + country + value.
    Progressively relaxes filters if not enough candidates found.
    """
    t2  = _norm_cpv(tender_cpv)[:2] if tender_cpv else ""
    t4  = _norm_cpv(tender_cpv)[:4] if tender_cpv else ""
    tc  = tender_country.strip().upper()

    def passes_value(prof: dict) -> bool:
        if tender_eur is None:
            return True
        med = prof.get("median_value_eur")
        if med and med > 0:
            ratio = tender_eur / med
            return 0.01 <= ratio <= 100
        return True

    # Tier 1: CPV-4 + country + value
    pool = [c for c, p in company_profiles.items()
            if t4 and any(_norm_cpv(x)[:4] == t4 for x in p["cpv_prefixes"])
            and tc and tc in [co.upper() for co in p["countries"]]
            and passes_value(p)]
    if len(pool) >= 5:
        return pool[:max_candidates]

    # Tier 2: CPV-2 + country
    pool = [c for c, p in company_profiles.items()
            if t2 and any(_norm_cpv(x)[:2] == t2 for x in p["cpv_prefixes"])
            and tc and tc in [co.upper() for co in p["countries"]]]
    if len(pool) >= 5:
        return pool[:max_candidates]

    # Tier 3: CPV-2 only
    pool = [c for c, p in company_profiles.items()
            if t2 and any(_norm_cpv(x)[:2] == t2 for x in p["cpv_prefixes"])]
    if len(pool) >= 5:
        return pool[:max_candidates]

    # Tier 4: country only
    pool = [c for c, p in company_profiles.items()
            if tc and tc in [co.upper() for co in p["countries"]]]
    if len(pool) >= 5:
        return pool[:max_candidates]

    # Fallback: all companies
    return list(company_profiles.keys())[:max_candidates]


def evaluate(
    test_awards: list[dict],
    company_profiles: dict[str, dict],
    scorer: SemanticScorer,
    lr_model: LogisticRegression,
    lr_scaler: StandardScaler,
    tender_emb_cache: dict[str, np.ndarray],
    name_index: dict[str, str],
    award_texts: dict[str, dict[str, str]],
    k_values: list[int] = [1, 3, 5],
) -> dict[str, Any]:
    all_companies = list(company_profiles.keys())
    company_emb_matrix = scorer.company_emb_matrix

    # Encode any test tenders not in cache
    missing = [r for r in test_awards if r["ted_notice_id"] not in tender_emb_cache]
    if missing:
        texts = [" ".join(filter(None,[r.get("notice_title",""),r.get("description","")]))
                 for r in missing]
        print(f"[Eval] Encoding {len(missing)} test tenders …", flush=True)
        embs = scorer.batch_encode_texts(texts)
        for r, emb in zip(missing, embs):
            tender_emb_cache[r["ted_notice_id"]] = emb

    print(f"\n[Eval] Two-stage scoring for {len(test_awards)} tenders …", flush=True)

    results = []
    null_reasons: dict[str, int] = defaultdict(int)
    filter_sizes = []

    for i, row in enumerate(test_awards):
        if i % 5 == 0:
            print(f"  {i}/{len(test_awards)} …", flush=True)

        tid          = row["ted_notice_id"]
        raw_winner   = row["winner_canonical_name"].strip()
        tender_eur   = to_eur(row.get("contract_value_eur",""), row.get("contract_currency","EUR"))
        tender_nuts  = row.get("nuts_code","")
        tender_cpv   = row.get("cpv_code","")
        tender_cntry = row.get("buyer_country","")

        winner = resolve_winner(raw_winner, name_index, all_companies)

        # ── Stage 1: Hard filter ──────────────────────────────
        candidates = hard_filter(tender_cpv, tender_cntry, tender_eur,
                                 company_profiles, max_candidates=200)

        filter_sizes.append(len(candidates))

        # ── Stage 2: LR scoring on filtered candidates ────────
        t_emb = tender_emb_cache.get(tid)
        cand_indices = [all_companies.index(c) for c in candidates if c in all_companies]

        if t_emb is not None and cand_indices:
            cand_matrix = company_emb_matrix[cand_indices]
            sem_scores  = np.clip(cand_matrix @ t_emb, 0.0, 1.0)
        else:
            sem_scores = np.full(len(candidates), 0.5)

        # Build full feature matrix for all candidates
        fv_rows = []
        for j, cname in enumerate(candidates):
            prof = company_profiles.get(cname, {})
            _c8, c4, c2 = cpv_features(tender_cpv, prof.get("cpv_prefixes", []))
            ne, nc      = nuts_features(tender_nuts, prof.get("nuts_prefixes", []))
            vs, vr      = value_features(tender_eur, prof.get("median_value_eur"),
                                         prof.get("min_value_eur"), prof.get("max_value_eur"))
            fv_rows.append(build_fv(
                float(sem_scores[j]),
                c4, c2, ne, nc, vs, vr,
                country_match_score(tender_cntry, prof.get("countries", [])),
                company_size_score(prof.get("award_count", 0)),
                0.5,
            ))

        X_cands = lr_scaler.transform(np.array(fv_rows))
        lr_scores = lr_model.predict_proba(X_cands)[:, 1]  # P(label=1)

        ranked_local = np.argsort(lr_scores)[::-1]
        ranked_companies = [candidates[i] for i in ranked_local]

        top_k = {k: ranked_companies[:k] for k in k_values}
        top5_scored = [
            {"rank": r+1, "company": ranked_companies[r],
             "score": round(float(lr_scores[ranked_local[r]]), 4)}
            for r in range(min(5, len(ranked_companies)))
        ]

        if winner is None:
            in_pool     = False
            hit         = {k: False for k in k_values}
            null_reason = "winner_unresolvable"
            null_reasons[null_reason] += 1
        elif winner not in candidates:
            in_pool     = True
            hit         = {k: False for k in k_values}
            null_reason = "winner_filtered_out"
            null_reasons[null_reason] += 1
        else:
            in_pool     = True
            hit         = {k: (winner in top_k[k]) for k in k_values}
            null_reason = None

        results.append({
            "ted_notice_id":   tid,
            "notice_title":    row.get("notice_title","")[:100],
            "buyer_name":      row.get("buyer_name",""),
            "buyer_country":   tender_cntry,
            "raw_winner":      raw_winner,
            "resolved_winner": winner,
            "winner_in_pool":  in_pool,
            "null_reason":     null_reason,
            "n_candidates":    len(candidates),
            "hit_at_1":        hit.get(1),
            "hit_at_3":        hit.get(3),
            "hit_at_5":        hit.get(5),
            "top_5":           top5_scored,
        })

    print(f"\n[Filter] Avg candidates after Stage 1: {np.mean(filter_sizes):.0f} "
          f"(min {min(filter_sizes)}, max {max(filter_sizes)})", flush=True)

    # Aggregate metrics — all tenders counted, misses are False not excluded
    n_total   = len(results)
    n_unresolvable  = sum(1 for r in results if r["null_reason"] == "winner_unresolvable")
    n_filtered_out  = sum(1 for r in results if r["null_reason"] == "winner_filtered_out")

    metrics: dict[str, Any] = {
        "total_tenders":         n_total,
        "winner_unresolvable":   n_unresolvable,
        "winner_filtered_out":   n_filtered_out,
        "null_breakdown":        dict(null_reasons),
        "winner_in_pool_rate":   round(sum(1 for r in results if r["winner_in_pool"]) / n_total, 4) if n_total else 0,
    }
    for k in k_values:
        hits = sum(1 for r in results if r[f"hit_at_{k}"])
        metrics[f"hit_at_{k}"] = round(hits / n_total, 4) if n_total else 0.0
        metrics[f"hit_at_{k}_count"] = f"{hits}/{n_total}"

    print(f"\n[Eval Results]")
    print(f"  Total tenders:     {n_total}")
    print(f"  Winner unresolvable: {n_unresolvable}  (not in company pool)")
    print(f"  Winner filtered out: {n_filtered_out}  (hard filter removed them)")
    print(f"  Winner-in-pool:    {metrics['winner_in_pool_rate']:.0%}")
    for k in k_values:
        print(f"  Hit@{k}:            {metrics[f'hit_at_{k}']:.2%}  ({metrics[f'hit_at_{k}_count']})")

    return {"metrics": metrics, "results": results}


# ── Main ──────────────────────────────────────────────────────

def _force_line_buffered_stdio() -> None:
    """Reopen stdout/stderr line-buffered for live progress during a real run.

    Kept OUT of module import (only called from main()) so importing this module —
    e.g. the G20 parity test's importorskip — never touches process file descriptors,
    which would corrupt pytest's output capture.
    """
    sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1)
    sys.stderr = open(sys.stderr.fileno(), mode="w", encoding="utf-8", buffering=1)


def main() -> None:
    _force_line_buffered_stdio()
    print("=" * 60)
    print("Tender → Top-3 Company Matching Pipeline  v5")
    print("=" * 60)

    # 1. Load
    print("\n[Load] Reading CSV files …", flush=True)
    awards = load_csv(AWARDS_PATH)
    awards = [r for r in awards if r.get("winner_canonical_name","").strip()]
    print(f"  Awards: {len(awards)}", flush=True)

    # 2. Chronological split: companies known from ALL data, model trained on first half
    awards_sorted = sorted(awards, key=lambda r: r.get("award_date",""))
    n_train = int(len(awards_sorted) * TRAIN_SAMPLE)
    train_awards = awards_sorted[:n_train]
    test_pool    = awards_sorted[n_train:]

    # Company profiles built from ALL awards — no empty profiles.
    # award_texts stores per-tender text contributions for leave-one-out at eval time.
    company_profiles, award_texts = build_company_profiles(awards)
    all_companies = list(company_profiles.keys())
    name_index    = build_name_index(all_companies)

    # Test tenders: new/unseen tenders whose true winner IS in the known company pool
    rng_main = random.Random(RANDOM_STATE)
    test_awards = rng_main.sample(test_pool, min(TEST_SAMPLE, len(test_pool)))
    print(f"[Sample] Train pairs: {len(train_awards)} | "
          f"Test pool: {len(test_pool)} | Evaluating: {len(test_awards)}", flush=True)

    # 4. Semantic scorer
    scorer = SemanticScorer(company_profiles)
    scorer.build_company_embeddings()

    # 5. Hard negative index
    hard_idx = build_hard_negative_index(train_awards)

    # 6. Build ranked training groups
    tender_emb_cache: dict[str, np.ndarray] = {}
    records, tender_emb_cache = build_training_groups(
        train_awards, company_profiles, scorer,
        hard_idx, name_index, tender_emb_cache, award_texts,
    )

    # 7. Leakage-safe group split
    train_recs, test_recs = chronological_group_split(records)

    # Further split train → train/val (85/15)
    unique_train_tids = list({r["tender_id"] for r in train_recs})
    n_val_tids = max(1, int(len(unique_train_tids) * 0.15))
    val_tids   = set(unique_train_tids[-n_val_tids:])
    val_recs   = [r for r in train_recs if r["tender_id"] in val_tids]
    tr_recs    = [r for r in train_recs if r["tender_id"] not in val_tids]

    print(f"[Data] Train groups: {len(tr_recs)} recs | Val: {len(val_recs)} | Test split: {len(test_recs)}", flush=True)

    # 8. Train Logistic Regression
    lr_model, lr_scaler = train_lr(tr_recs, val_recs)

    # 9. Save model
    EXPORTS_DIR.mkdir(exist_ok=True)
    joblib.dump({"model": lr_model, "scaler": lr_scaler}, MODEL_PATH)
    print(f"\n[Model] Saved → {MODEL_PATH}", flush=True)

    # 9b. Save plain-JSON params the in-app matcher loads (coef + intercept +
    # scaler), so it can reproduce predict_proba without the joblib. Keep the
    # feature order identical to FEATURE_NAMES — the app indexes by it.
    model_params = {
        "feature_names":  FEATURE_NAMES,
        "coefficients":   lr_model.coef_[0].tolist(),
        "intercept":      float(lr_model.intercept_[0]),
        "scaler_mean":    lr_scaler.mean_.tolist(),
        "scaler_scale":   lr_scaler.scale_.tolist(),
        "trained_at":     datetime.utcnow().isoformat() + "Z",
    }
    with MODEL_PARAMS_PATH.open("w", encoding="utf-8") as f:
        json.dump(model_params, f, ensure_ascii=False, indent=2)
    print(f"[Model] Params → {MODEL_PARAMS_PATH}", flush=True)

    # 10. Evaluate on held-out test tenders
    eval_output = evaluate(
        test_awards, company_profiles, scorer, lr_model, lr_scaler,
        tender_emb_cache, name_index, award_texts, k_values=[1, 3, 5],
    )

    # 11. Save outputs
    with OUTPUT_PATH.open("w", encoding="utf-8") as f:
        json.dump(eval_output["results"], f, ensure_ascii=False, indent=2)
    print(f"\n[Output] Results → {OUTPUT_PATH}", flush=True)

    report = {
        "generated_at":      datetime.utcnow().isoformat() + "Z",
        "model":             "Logistic Regression",
        "feature_names":     FEATURE_NAMES,
        "lr_coefficients":   dict(zip(FEATURE_NAMES, lr_model.coef_[0].tolist())),
        "train_awards":      len(train_awards),
        "test_awards":       len(test_awards),
        "neg_ratio":         NEG_RATIO,
        "hard_negatives":    True,
        **eval_output["metrics"],
    }
    with REPORT_PATH.open("w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    print(f"[Output] Report → {REPORT_PATH}", flush=True)

    print("\n[Model Report]", flush=True)
    print(f"  generated_at    : {report['generated_at']}", flush=True)
    print(f"  model           : {report['model']}", flush=True)
    print(f"  train_awards    : {report['train_awards']}", flush=True)
    print(f"  test_awards     : {report['test_awards']}", flush=True)
    print(f"  neg_ratio       : {report['neg_ratio']}", flush=True)
    print(f"  winner_in_pool  : {report['winner_in_pool_rate']:.0%}", flush=True)
    print(f"  hit@1           : {report['hit_at_1']:.2%}  ({report['hit_at_1_count']})", flush=True)
    print(f"  hit@3           : {report['hit_at_3']:.2%}  ({report['hit_at_3_count']})", flush=True)
    print(f"  hit@5           : {report['hit_at_5']:.2%}  ({report['hit_at_5_count']})", flush=True)
    print(f"  LR coefficients:", flush=True)
    for feat, coef in report['lr_coefficients'].items():
        print(f"    {feat:25s}: {coef:+.4f}", flush=True)

    # 12. Print sample predictions
    print("\n[Sample predictions]", flush=True)
    for entry in eval_output["results"][:5]:
        print(f"\n  {entry['ted_notice_id']} | {entry['notice_title'][:60]}")
        print(f"  Buyer: {entry['buyer_name']} ({entry['buyer_country']})")
        print(f"  Winner: {entry['raw_winner']}")
        print(f"  Resolved: {entry['resolved_winner']} | In pool: {entry['winner_in_pool']}")
        print(f"  Hit@1={entry['hit_at_1']}  Hit@3={entry['hit_at_3']}  Hit@5={entry['hit_at_5']}")
        for rec in entry["top_5"]:
            marker = " ✓" if rec["company"] == entry["resolved_winner"] else ""
            print(f"    #{rec['rank']} {rec['company'][:60]} ({rec['score']}){marker}")

    # 13. Summary
    m = eval_output["metrics"]
    print(f"""
╔══════════════════════════════════════════════════════╗
║           PIPELINE v5 SUMMARY  (honest eval)         ║
╠══════════════════════════════════════════════════════╣
║ Model          : Logistic Regression (10 features)   ║
║ Train awards   : {len(train_awards):<6}                             ║
║ Test tenders   : {len(test_awards):<6}  (all, no pre-filter)        ║
║ Unresolvable   : {m['winner_unresolvable']:<6}  (winner not in pool)         ║
║ Filtered out   : {m['winner_filtered_out']:<6}  (hard filter miss)           ║
║ Winner-in-pool : {m['winner_in_pool_rate']:.0%}                               ║
║ Hit@1          : {m['hit_at_1']:.2%}  ({m['hit_at_1_count']})                    ║
║ Hit@3          : {m['hit_at_3']:.2%}  ({m['hit_at_3_count']})                    ║
║ Hit@5          : {m['hit_at_5']:.2%}  ({m['hit_at_5_count']})                    ║
╚══════════════════════════════════════════════════════╝
""", flush=True)


if __name__ == "__main__":
    main()
