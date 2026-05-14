"""
Tender GTM Pipeline / 投标 GTM 流水线
=====================================
Process / 流程：
  1. Import / 导入 tenders.json + company_profile.json
  2. MiniLM semantic similarity calculation / 计算语义相似度 (Tender description vs Company capability / 投标描述 vs 公司能力描述)
  3. Rule-based scoring / 规则打分 (Budget/Region/Qualification/Deadline / 预算/地区/资质/截止日期)
  4. Feature merging / 合并特征 → Dual-domain LR training / 双领域 LR 训练
  5. Manual weight adjustment / 人工调权 → Real-time score recalculation / 实时重算分数
  6. Explainable output / 解释性输出

Dependencies / 依赖：
  pip install sentence-transformers scikit-learn numpy

Note / 注意：
  When USE_MINILM = False, TF-IDF cosine is used as an alternative (No model download required, slightly worse performance).
  USE_MINILM = False 时用 TF-IDF cosine 替代（无需下载模型，效果略差）。
  For local execution, set USE_MINILM = True for better accuracy.
  本地运行时把 USE_MINILM = True，效果更准确。
"""

import json
import numpy as np
from pathlib import Path
from dataclasses import dataclass
from typing import Optional
from sklearn.linear_model import LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import Pipeline
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity


# ─────────────────────────────────────────────────────────────
# Configuration / 配置
# ─────────────────────────────────────────────────────────────

DATA_DIR      = Path(__file__).parent / "data"
TENDERS_PATH  = DATA_DIR / "tenders.json"
COMPANY_PATH  = DATA_DIR / "company_profile.json"
MINIML_MODEL  = "all-MiniLM-L6-v2"
USE_MINILM    = True   # ← Set to True locally to enable actual MiniLM / 本地改成 True 启用真正的 MiniLM

CONSTRUCTION_FEATURES = ["semantic_score", "budget_match", "region_match", "qual_match", "days_norm"]
IT_FEATURES           = ["semantic_score", "budget_match", "region_match", "qual_match", "days_norm"]
MISSING_FILL          = 0.5


# ─────────────────────────────────────────────────────────────
# Step 0: Load JSON / 加载 JSON
# ─────────────────────────────────────────────────────────────

def load_data():
    with open(TENDERS_PATH, encoding="utf-8") as f:
        tenders = json.load(f)
    with open(COMPANY_PATH, encoding="utf-8") as f:
        company = json.load(f)
    print(f"[Load/加载] {len(tenders)} tenders / 条投标, Company / 公司：{company['company_name']}")
    return tenders, company


# ─────────────────────────────────────────────────────────────
# Step 1: Semantic Similarity / 语义相似度
#   USE_MINILM=True  → sentence-transformers MiniLM (Recommended / 推荐)
#   USE_MINILM=False → TF-IDF cosine (Offline demo / 离线演示)
# ─────────────────────────────────────────────────────────────

class SemanticScorer:
    def __init__(self):
        self._company_texts: dict[str, str] = {}
        if USE_MINILM:
            from sentence_transformers import SentenceTransformer, util as st_util
            print(f"[MiniLM] Loading / 加载 {MINIML_MODEL} ...")
            self._model = SentenceTransformer(MINIML_MODEL)
            self._st_util = st_util
            self._company_embs: dict[str, np.ndarray] = {}
        else:
            print("[Semantic/语义] Using TF-IDF cosine (Offline mode) / 使用 TF-IDF cosine（离线模式）")
            self._tfidf = TfidfVectorizer()
            self._company_vecs: dict[str, np.ndarray] = {}

    def build_company_embeddings(self, company: dict):
        """Pre-encode company capability descriptions (runs only once) / 预编码公司能力描述（只跑一次）"""
        profiles = company["capability_profiles"]
        self._company_texts = profiles

        if USE_MINILM:
            for domain, text in profiles.items():
                self._company_embs[domain] = self._model.encode(
                    text, convert_to_numpy=True
                )
        else:
            # TF-IDF: Fit all texts together to ensure consistent vocabulary / 把所有文本一起 fit，保证词表一致
            all_texts = list(profiles.values())
            self._tfidf.fit(all_texts)
            for domain, text in profiles.items():
                self._company_vecs[domain] = self._tfidf.transform([text]).toarray()

        print(f"[Semantic/语义] Company capability vectors established / 公司能力向量已建立：{list(profiles.keys())}")

    def score(self, tender: dict) -> float:
        domain = tender.get("domain", "hybrid")
        if domain not in self._company_texts:
            domain = "hybrid"
        text = tender.get("project_description", "")
        if not text:
            return MISSING_FILL

        if USE_MINILM:
            emb = self._model.encode(text, convert_to_numpy=True)
            cosine = float(self._st_util.cos_sim(emb, self._company_embs[domain])[0][0])
        else:
            vec = self._tfidf.transform([text]).toarray()
            cosine = float(cosine_similarity(vec, self._company_vecs[domain])[0][0])

        # Map to 0~1 / 映射到 0~1
        score = np.clip((cosine - 0.05) / 0.90, 0.0, 1.0)
        return round(float(score), 4)


# ─────────────────────────────────────────────────────────────
# Step 2: Rule-based Scoring / 规则打分
# ─────────────────────────────────────────────────────────────

def score_budget(tender: dict, company: dict) -> float:
    budget = tender.get("budget_cny_wan")
    if budget is None:
        return MISSING_FILL
    lo = company["budget_range_wan"]["min"]
    hi = company["budget_range_wan"]["max"]
    if lo <= budget <= hi:
        return 1.0
    elif budget < lo:
        return round(float(budget / lo), 4)
    else:
        return round(float(hi / budget), 4)


def score_region(tender: dict, company: dict) -> float:
    region = tender.get("region", "")
    for r in company.get("regions", []):
        if r in region or region in r:
            return 1.0
    return 0.3


def score_qualification(tender: dict, company: dict) -> float:
    required = tender.get("qualification_requirements", [])
    if not required:
        return 1.0
    held = company.get("qualifications", [])
    matched = 0
    for req in required:
        req_kw = set(req.replace("及以上", "").replace("认证", "").split())
        for h in held:
            h_kw = set(h.replace("及以上", "").replace("认证", "").split())
            if len(req_kw & h_kw) >= 2:
                matched += 1
                break
    return round(matched / len(required), 4)


def score_deadline(tender: dict) -> float:
    days = tender.get("deadline_days")
    if days is None:
        return MISSING_FILL
    return round(float(np.clip(days / 60.0, 0.0, 1.0)), 4)


# ─────────────────────────────────────────────────────────────
# Step 3: Feature Merging / 合并特征
# ─────────────────────────────────────────────────────────────

@dataclass
class ScoredTender:
    tender_id: str
    domain: str
    features: dict
    feature_vector: np.ndarray
    result: Optional[int]


def build_vector(features: dict, domain: str) -> np.ndarray:
    keys = CONSTRUCTION_FEATURES if domain != "it" else IT_FEATURES
    return np.array([features.get(k, MISSING_FILL) for k in keys], dtype=float)


def process_tenders(tenders, company, semantic_scorer) -> list[ScoredTender]:
    print("\n[Feature Scoring / 特征打分]")
    scored = []
    for t in tenders:
        domain = t.get("domain", "hybrid")
        features = {
            "semantic_score": semantic_scorer.score(t),
            "budget_match":   score_budget(t, company),
            "region_match":   score_region(t, company),
            "qual_match":     score_qualification(t, company),
            "days_norm":      score_deadline(t),
        }
        vec = build_vector(features, domain)
        scored.append(ScoredTender(
            tender_id=t["tender_id"], domain=domain,
            features=features, feature_vector=vec,
            result=t.get("result"),
        ))
        print(
            f"  {t['tender_id']} [{domain:12s}] "
            + "  ".join(f"{k.split('_')[0]}={v:.2f}" for k, v in features.items())
            + f"  y={t.get('result','?')}"
        )
    return scored


# ─────────────────────────────────────────────────────────────
# Step 4: Dual-domain LR / 双领域 LR
# ─────────────────────────────────────────────────────────────

class DomainLR:
    def __init__(self, domain: str, C: float = 1.0):
        self.domain = domain
        self.feature_names = CONSTRUCTION_FEATURES if domain != "it" else IT_FEATURES
        self.pipeline = Pipeline([
            ("scaler", StandardScaler()),
            ("lr",     LogisticRegression(C=C, max_iter=1000, random_state=42)),
        ])
        self.trained = False

    def fit(self, samples: list[ScoredTender]):
        labeled = [s for s in samples if s.result is not None]
        if len(labeled) < 2:
            print(f"[{self.domain}] Insufficient samples / 样本不足 ({len(labeled)}), skipping training / 跳过训练")
            return self
        if len(labeled) < 20:
            print(f"[Warning/警告] {self.domain} only has / 仅 {len(labeled)} records/条, coefficients are for reference only / 系数仅供参考")
        X = np.array([s.feature_vector for s in labeled])
        y = np.array([s.result for s in labeled])
        self.pipeline.fit(X, y)
        self.trained = True
        print(f"[{self.domain}] Training completed / 训练完成, Sample count / 样本数={len(labeled)}")
        return self

    def predict_proba(self, vec: np.ndarray) -> float:
        if not self.trained:
            return float(np.mean(vec))
        return float(self.pipeline.predict_proba(vec.reshape(1, -1))[0][1])

    def recommended_weights(self) -> dict:
        if not self.trained:
            n = len(self.feature_names)
            return {k: round(1/n, 4) for k in self.feature_names}
        coefs = self.pipeline.named_steps["lr"].coef_[0]
        pos = np.maximum(coefs, 0)
        total = pos.sum() or 1.0
        return {k: round(float(v/total), 4) for k, v in zip(self.feature_names, pos)}

    def explain(self, vec: np.ndarray, top_n: int = 3) -> list[dict]:
        if not self.trained:
            return []
        x_s = self.pipeline.named_steps["scaler"].transform(vec.reshape(1, -1))[0]
        contribs = x_s * self.pipeline.named_steps["lr"].coef_[0]
        items = [
            {"feature": k, "value": round(float(v), 3),
             "contribution": round(float(c), 3),
             "direction": "Positive/正向" if c >= 0 else "Negative/负向"}
            for k, v, c in zip(self.feature_names, vec, contribs)
        ]
        return sorted(items, key=lambda x: abs(x["contribution"]), reverse=True)[:top_n]


class TenderMatcher:
    def __init__(self):
        self.models = {
            "construction": DomainLR("construction"),
            "it":           DomainLR("it"),
        }

    def fit(self, scored: list[ScoredTender]):
        print("\n[LR Training / LR 训练]")
        hybrid = [s for s in scored if s.domain == "hybrid"]
        self.models["construction"].fit(
            [s for s in scored if s.domain == "construction"] + hybrid)
        self.models["it"].fit(
            [s for s in scored if s.domain == "it"] + hybrid)

    def score(self, s: ScoredTender, custom_weights: Optional[dict] = None,
              hybrid_ratio: float = 0.5) -> dict:

        def _prob(d: str) -> float:
            if custom_weights:
                keys = self.models[d].feature_names
                total_w = sum(custom_weights.get(k, 0) for k in keys)
                if total_w == 0:
                    return float(np.mean(s.feature_vector))
                return sum(custom_weights.get(k, 0) * s.features.get(k, MISSING_FILL)
                           for k in keys) / total_w
            return self.models[d].predict_proba(s.feature_vector)

        domain = s.domain
        if domain == "construction":
            prob = _prob("construction")
            explain = self.models["construction"].explain(s.feature_vector)
            breakdown = {"construction": round(prob, 4)}
        elif domain == "it":
            prob = _prob("it")
            explain = self.models["it"].explain(s.feature_vector)
            breakdown = {"it": round(prob, 4)}
        else:
            p_c, p_it = _prob("construction"), _prob("it")
            prob = hybrid_ratio * p_c + (1 - hybrid_ratio) * p_it
            explain = (self.models["construction"].explain(s.feature_vector)[:2]
                       + self.models["it"].explain(s.feature_vector)[:2])
            breakdown = {"construction": round(p_c, 4),
                         "it": round(p_it, 4), "final": round(prob, 4)}

        return {
            "tender_id": s.tender_id, "domain": domain,
            "probability": round(prob, 4), "score": round(prob * 100, 1),
            "recommend": _label(prob),
            "breakdown": breakdown, "top_factors": explain,
        }


def _label(p):
    if p >= 0.70: return "Strongly Recommend / 强烈建议投标"
    if p >= 0.50: return "Recommend / 建议投标"
    if p >= 0.35: return "Consider / 可考虑"
    return "Not Recommended / 不建议投标"


# ─────────────────────────────────────────────────────────────
# Step 5: Manual Weight Adjustment / 人工调权
# ─────────────────────────────────────────────────────────────

def interactive_adjust(matcher: TenderMatcher, scored: list[ScoredTender],
                       domain: str = "construction") -> dict:
    print("\n" + "="*55)
    print("  Sales Weight Adjustment Simulation / Sales 调权模拟")
    print("="*55)

    rec = matcher.models[domain].recommended_weights()
    print(f"\n[LR Recommended Weights / LR 推荐权重]  ({domain})")
    for k, v in rec.items():
        print(f"  {k:25s}  {v:.3f}  {'▓'*int(v*40)}")

    # Simulate Sales increasing semantic weight / 模拟 Sales 把语义权重调高
    adjusted = dict(rec)
    adjusted["semantic_score"] = 0.50
    total = sum(adjusted.values())
    adjusted = {k: round(v/total, 4) for k, v in adjusted.items()}

    print(f"\n[Weights After Sales Adjustment / Sales 调整后权重]  (Normalized after raising semantic to 0.50 / semantic 调高到 0.50 后归一化)")
    for k, v in adjusted.items():
        print(f"  {k:25s}  {v:.3f}  {'▓'*int(v*40)}")

    targets = [s for s in scored if s.domain in (domain, "hybrid")]
    print(f"\n[Comparison / 对比]")
    for s in targets:
        d = matcher.score(s)["score"]
        a = matcher.score(s, custom_weights=adjusted)["score"]
        diff = a - d
        print(f"  {s.tender_id}  Default/默认={d:5.1f}  Adjusted/调整后={a:5.1f}  "
              f"{'↑' if diff>0 else '↓'}{abs(diff):.1f}")

    return adjusted


# ─────────────────────────────────────────────────────────────
# Main Pipeline / 主流程
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":

    tenders, company = load_data()

    scorer = SemanticScorer()
    scorer.build_company_embeddings(company)
    scored = process_tenders(tenders, company, scorer)

    matcher = TenderMatcher()
    matcher.fit(scored)

    print("\n[Default Scoring / 默认评分]")
    results = [matcher.score(s) for s in scored]
    for r in results:
        print(f"  {r['tender_id']}  [{r['domain']:12s}]  {r['score']:5.1f}/100  {r['recommend']}")
        for f in r["top_factors"]:
            sign = "+" if f["direction"] == "Positive/正向" else "-"
            print(f"    [{sign}] {f['feature']:25s} val={f['value']:.2f}  contrib={f['contribution']:+.3f}")

    adjusted = interactive_adjust(matcher, scored)

    # Write out JSON for Dashboard consumption / 写出 JSON 供 Dashboard 消费
    out = []
    for s in scored:
        out.append({
            "tender_id":    s.tender_id,
            "features":     s.features,
            "default":      matcher.score(s),
            "adjusted":     matcher.score(s, custom_weights=adjusted),
            "rec_weights":  matcher.models[
                "it" if s.domain == "it" else "construction"
            ].recommended_weights(),
        })
    out_path = DATA_DIR / "scores_output.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"\n[Complete/完成] Results written to / 结果已写入 {out_path}")