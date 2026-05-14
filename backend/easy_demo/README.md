# Tender GTM Pipeline Demo / 投标 GTM 流水线 Demo

## 1. Project Overview / 项目简介

This project is a demo pipeline for matching **one company profile** with multiple public tender opportunities.

本项目是一个用于 **单个公司匹配多个招标项目** 的 GTM demo。系统会根据公司能力、招标描述、预算、地区、资质和工期等信息，判断每个 tender 是否值得投标。

The current version supports:

- Semantic similarity scoring
- Rule-based business scoring
- Construction / IT dual-domain Logistic Regression
- Manual sales weight adjustment
- Explainable recommendation output
- JSON output for dashboard or frontend usage

当前版本支持：

- 语义相似度打分
- 业务规则打分
- Construction / IT 双领域逻辑回归模型
- Sales 人工调权模拟
- 可解释推荐结果
- 输出 JSON 文件供 dashboard 或前端使用

---

## 2. Project Structure / 项目结构

```text
tender_gtm_demo/
├── tender_pipeline.py
├── requirements.txt
├── README.md
└── data/
    ├── tenders.json
    └── company_profile.json
```

After running the pipeline, the following file will be generated:

运行程序后会生成：

```text
data/scores_output.json
```

---

## 3. Input Files / 输入文件

### 3.1 `data/company_profile.json`

This file describes the target company.

该文件描述目标公司的能力画像。

Example fields:

```json
{
  "company_name": "某科技工程有限公司",
  "overall_description": "...",
  "capability_profiles": {
    "construction": "...",
    "it": "...",
    "hybrid": "..."
  },
  "qualifications": [],
  "regions": [],
  "budget_range_wan": {
    "min": 80,
    "max": 600
  },
  "typical_delivery": {
    "construction": "...",
    "it": "..."
  }
}
```

### 3.2 `data/tenders.json`

This file contains multiple tender opportunities.

该文件包含多个招标项目。

Example fields:

```json
[
  {
    "tender_id": "T-001",
    "domain": "construction",
    "project_name": "...",
    "project_description": "...",
    "budget_cny_wan": 320,
    "region": "上海",
    "deadline_days": 42,
    "qualification_requirements": [],
    "result": 1
  }
]
```

---

## 4. Pipeline Logic / 流水线逻辑

The pipeline contains the following steps:

系统主要流程如下：

```text
1. Load tenders.json and company_profile.json
2. Compute semantic similarity between tender description and company capability profile
3. Compute rule-based scores:
   - budget_match
   - region_match
   - qual_match
   - days_norm
4. Merge all scores into a feature vector
5. Train construction and IT Logistic Regression models
6. Score each tender
7. Output recommendation labels and explainable top factors
8. Simulate manual sales weight adjustment
9. Write results to data/scores_output.json
```

中文解释：

```text
1. 加载 tenders.json 和 company_profile.json
2. 计算 tender 描述和公司能力之间的语义相似度
3. 计算规则分数：
   - 预算匹配
   - 地区匹配
   - 资质匹配
   - 工期/截止时间分数
4. 合并成机器学习特征向量
5. 分别训练 construction 和 IT 逻辑回归模型
6. 对每个 tender 打分
7. 输出推荐标签和可解释因素
8. 模拟 Sales 人工调权
9. 写出 data/scores_output.json
```

---

## 5. Scoring Features / 打分特征

The model uses the following features:

模型使用以下特征：

| Feature | Meaning | 中文含义 |
|---|---|---|
| `semantic_score` | Semantic similarity between tender and company capability | 招标描述与公司能力的语义相似度 |
| `budget_match` | Whether the tender budget fits the company budget range | 预算是否匹配公司项目规模 |
| `region_match` | Whether the tender location matches company regions | 地区是否匹配公司覆盖范围 |
| `qual_match` | Whether company qualifications match tender requirements | 公司资质是否满足招标要求 |
| `days_norm` | Normalized deadline or delivery time score | 工期/截止时间归一化分数 |

---

## 6. Recommendation Labels / 推荐标签

The final probability is converted into a business recommendation:

最终分数会转换成业务推荐标签：

| Probability | Label |
|---|---|
| `>= 0.70` | Strongly Recommend / 强烈建议投标 |
| `>= 0.50` | Recommend / 建议投标 |
| `>= 0.35` | Consider / 可考虑 |
| `< 0.35` | Not Recommended / 不建议投标 |

---

## 7. Installation / 安装依赖

Create and activate a virtual environment if needed:

可以先创建并激活虚拟环境：

```bash
python3 -m venv venv
source venv/bin/activate
```

Install dependencies:

安装依赖：

```bash
pip install -r requirements.txt
```

If `requirements.txt` does not exist, install manually:

如果还没有 `requirements.txt`，可以手动安装：

```bash
pip install numpy scikit-learn sentence-transformers
```

If you do not want to download MiniLM, set this in `tender_pipeline.py`:

如果不想下载 MiniLM 模型，可以在 `tender_pipeline.py` 里设置：

```python
USE_MINILM = False
```

Then the system will use TF-IDF cosine similarity instead.

这样系统会使用 TF-IDF cosine similarity 作为离线替代方案。

---

## 8. Run / 运行方式

From the project folder, run:

在项目文件夹下运行：

```bash
python3 tender_pipeline.py
```

Expected output:

预期输出包括：

```text
[Load/加载]
[Semantic/语义]
[Feature Scoring / 特征打分]
[LR Training / LR 训练]
[Default Scoring / 默认评分]
[Complete/完成] Results written to data/scores_output.json
```

---

## 9. Output / 输出结果

The pipeline writes the final results to:

程序会输出结果到：

```text
data/scores_output.json
```

Each result contains:

每条结果包含：

```json
{
  "tender_id": "T-001",
  "features": {
    "semantic_score": 0.82,
    "budget_match": 1.0,
    "region_match": 1.0,
    "qual_match": 1.0,
    "days_norm": 0.7
  },
  "default": {
    "score": 88.5,
    "recommend": "Strongly Recommend / 强烈建议投标",
    "top_factors": []
  },
  "adjusted": {},
  "rec_weights": {}
}
```

---

## 10. Current Capability / 当前代码能实现什么

The current demo can:

当前 demo 可以实现：

- Load one company profile and multiple tender records
- Score each tender-company match
- Combine semantic similarity and business rules
- Train simple Logistic Regression models
- Produce recommendation scores
- Explain important scoring factors
- Simulate manual sales weight adjustment
- Export results to JSON

中文总结：

```text
当前代码已经能实现：
一个公司扫描多个 tender，
并结合语义匹配、预算、地区、资质和工期，
输出每个 tender 的投标推荐分数和推荐理由。
```

---

## 11. Limitations / 当前限制

This is a demo version, so it still has several limitations:

这是一个 demo 版本，因此还有一些限制：

1. The current version supports one company only.
2. The dataset is small and mainly used for demonstration.
3. Logistic Regression coefficients are not reliable with very few samples.
4. Qualification matching is still based on simple text overlap.
5. Region matching is based on simple string matching.
6. Budget handling is simplified and mainly supports `budget_cny_wan`.
7. Semantic score gives a number but does not yet explain detailed item-to-item matches.
8. There is no frontend dashboard yet.

中文：

```text
当前版本主要适合学校 project demo，
还不能直接作为真实生产系统使用。
```

---

## 12. Future Improvements / 后续优化方向

Possible next steps:

后续可以优化：

- Support multiple companies with `companies.json`
- Rank tenders for each company
- Add real historical tender-company pair data
- Add requirement-item and capability-item level matching
- Improve qualification taxonomy
- Normalize currencies such as EUR, DKK and CNY
- Add evaluation metrics such as accuracy, recall, AUC and top-k hit rate
- Build a frontend dashboard
- Add more explainable AI output

中文总结：

```text
下一步可以把系统升级成：
多个公司 → 每个公司扫描所有 tender → 给每家公司推荐最值得投的项目。
```

---

## 13. Notes / 备注

This project is designed as a school project demo for GTM tender recommendation and machine learning-based opportunity matching.

本项目是一个学校项目 demo，用于展示如何用机器学习和语义匹配方法做 GTM 投标机会推荐。
