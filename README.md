# 💸 Personal Expense Analyzer

An LLM-powered web app that turns a bank or mobile-wallet statement (CSV / Excel / text PDF) into an interactive
budgeting dashboard and a downloadable multi-page PDF report. Built with **Streamlit**, **pandas** and
**Google Gemini** (free tier). Currency defaults to **BDT (৳)**.

> ⚖️ This app gives general budgeting guidance only. It is **not** financial, tax or investment advice.

## Features

| Area | What you get |
|---|---|
| **Upload & mapping** | CSV, XLSX or text-based PDF. Title rows above the header are skipped. Pick the date, description and amount columns. Amounts can be one signed column, separate debit/credit columns, or amount + Dr/Cr column. Day-first dates, Bengali digits (০-৯), `৳ 1,200`, `(500)` and `1,000 Dr` are understood. |
| **Privacy** | Card, account and phone numbers, emails and long reference IDs are **masked** before anything leaves your computer. You can preview exactly what will be sent. |
| **AI categorisation** | **One** batched Gemini request with the unique masked descriptions (max 400) plus money direction (in/out). Structured output via a Pydantic schema. Offline keyword rules are used until you run it. |
| **AI insights** | **One** Gemini request with **aggregated totals only**: spending patterns, recurring payments/subscriptions, unusual transactions, saving tips, suggested budgets per category and a 0-100 budget-health score. |
| **Dashboard** | KPI cards (income, expenses, net savings, savings rate), category donut, monthly trend, top merchants, recurring payments list, flagged unusual transactions. Filters by month and category. |
| **Transactions** | Editable table (`st.data_editor`): fix a category or merchant and every chart recomputes. Option to apply a fix to all rows from the same merchant. |
| **Budget planner** | Set a monthly budget per category (defaults from the AI suggestions) and see used %, amount left/over and progress bars, plus a budget-vs-spend chart. |
| **Exports** | Multi-page PDF report (ReportLab, charts drawn in ReportLab), categorised CSV (masked descriptions by default) and a JSON of the whole analysis. |
| **Demo mode** | A synthetic 3-month BDT statement with clearly fake names, plus pre-generated categories and insights. No API key needed. |

## Quick start

```bash
cd expense-analyzer
python3 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # then paste your key into .env (optional, you can also paste it in the sidebar)
streamlit run app.py --server.port 8512
```

Open http://localhost:8512 and turn on **Demo mode** in the sidebar to explore without a key.
Run the app from inside the `expense-analyzer` folder so the custom theme in `.streamlit/config.toml` is used.

### Deploy on Streamlit Community Cloud

1. On https://share.streamlit.io click **Create app** and pick this repository, branch `main`.
2. Main file path: `streamlit_app.py` (it simply runs `app.py`).
3. Optional: under **Advanced settings → Secrets** add `GEMINI_API_KEY = "your-key"`; otherwise users paste
   their own key in the sidebar, or use Demo mode.

### Get a free Gemini API key

1. Go to **https://aistudio.google.com** and sign in with a Google account.
2. Click **Get API key → Create API key** (no credit card needed for the free tier).
3. Paste it into the sidebar, or put `GEMINI_API_KEY=...` in `.env`.
4. Pick a **Flash-Lite** model in the sidebar; it has the highest free-tier limits.

Free-tier notes:
- A full analysis uses **2 requests** (Categorise + Generate insights), each started by a button. The app never retries automatically.
- If you see "free-tier limit reached" (HTTP 429), wait a minute (per-minute limit) or try again after the daily
  reset (midnight Pacific time, about 2 PM in Bangladesh), or switch to another Flash-Lite model.
- On the free tier, Google may use your inputs to improve its products. That is why the app masks personal
  identifiers and sends only descriptions or totals, never your file.

## How it works

```
Statement file ─► pandas parser + column mapping ─► masking ─► unique masked descriptions ─► Gemini #1 (categories)
                                    │                                                               │
                                    ▼                                                               ▼
                         local analytics (pandas): KPIs, categories, months, merchants, recurring, unusual
                                    │                                       │
                                    ▼                                       ▼
                       Streamlit dashboard / editor / budget       aggregated totals ─► Gemini #2 (insights)
                                    │
                                    ▼
                        PDF (ReportLab) · CSV · JSON
```

| File | Role |
|---|---|
| `app.py` | Streamlit UI: upload and mapping, steps, filters, the five views, downloads. |
| `core/parser.py` | Reads CSV/XLSX/PDF, guesses the column mapping, cleans amounts and dates. Caps at 2,000 rows. |
| `core/privacy.py` | `mask_text()` (cards, accounts, phones, emails, reference IDs) and the dedup key. |
| `core/analytics.py` | All numbers: KPIs, category totals, monthly trend, top merchants, recurring and unusual detection, budget status, the insights payload. Offline keyword rules. |
| `core/schema.py` | Pydantic models for Gemini structured output (`CategorizationResult`, `InsightsResult`). |
| `core/common.py` | Prompts, payload builders, disclaimer, `AnalyzerError`. |
| `core/gemini_llm.py` | `google-genai` calls: model list (Flash-Lite first), one request per action, friendly 429 / invalid-key / model-not-found messages. |
| `core/report.py` | Multi-page PDF with ReportLab drawings (donut, bars, progress bars). |
| `core/theme.py` | Colours and currencies shared by the app and the PDF. |
| `samples/make_sample.py` | Generates the synthetic statement and the demo analysis JSON. |
| `tests/test_core.py` | Offline tests (pytest). |

## Tests

```bash
.venv/bin/python -m pytest -q tests
```

24 offline tests cover: masking (cards, phones, accounts, refs, emails), parsing the sample CSV and an XLSX with
Bengali digits, KPIs and recurring/unusual detection, that no raw identifier reaches the insights payload or the
Gemini request, the PDF build, and **mocked Gemini calls** (a fake HTTP transport): one batched request, structured
parsing, and friendly errors for 429 / 400 / 403 / 404 with no retries.

Not covered by the tests: a real call to the Gemini API (it needs your key). The demo categories and insights are
pre-generated sample data, not live model output.

## Limitations

- Scanned (image) PDFs are not supported; text PDFs are best-effort. CSV/Excel work best.
- Only the first 2,000 rows and 400 unique descriptions are analysed.
- Recurring and unusual detection use simple rules; the AI only comments on those candidates.
- AI text can contain mistakes; all numbers are computed locally by pandas.
