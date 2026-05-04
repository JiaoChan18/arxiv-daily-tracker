# arXiv Daily Tracker — Product Specification

## Overview

A personal research tool that automatically scrapes, analyzes, and reports daily arXiv papers in the `quant-ph` category. Designed for individual use by a quantum physics researcher, and published as an open-source project for the broader research community.

**Core principle**: 专注于论文价值的深度提炼，不提供通识性科普。Output is aimed at domain researchers, not general audiences.

---

## Target Users

- **Primary**: Individual researcher (quantum physics, based in Copenhagen)
- **Secondary**: Open-source community — other researchers who want to adapt the tool for their own arXiv categories and workflows

---

## Core Requirements

### Scraping

- **Source**: arXiv (https://arxiv.org), category `quant-ph`
- **Scope**: Each day's new submissions (not cross-lists by default)
- **Configuration**: Category should be dynamically configurable via a config file so other users can adapt it
- **Trigger modes**:
  - Scheduled: every day at **08:00 Copenhagen time** (CEST UTC+2 in summer, CET UTC+1 in winter)
  - Manual: run on demand via CLI command

### Analysis & Summarization (Phased)

| Phase | Feature | Priority |
|-------|---------|----------|
| Phase 1 | Structured abstract analysis: Core Value distillation + highlighted EN/ZH abstracts (专注于论文价值的深度提炼，不提供通识性科普) | High |
| Phase 2 | Relevance scoring / recommendation ranking against user's research focus | Medium |
| Phase 3 | User-defined research focus configuration in `config.yaml` | Low |

### Output

- **Markdown file**: one `.md` file per day, saved locally in an organized directory structure
- **PDF**: generated from the Markdown file
- **Email**: PDF attached and sent automatically to the configured recipient via SMTP

Per-paper Markdown structure:
1. Chinese title (heading)
2. English original title, authors, arXiv link
3. **🌟 Core Value** — 1-2 sentence blockquote distilling the research contribution
4. **Abstract (Original)** — full English abstract with `**bold**` on methods/metrics/conclusions
5. **中文摘要** — accurate Chinese translation with matching `**bold**` emphasis

---

## Technical Decisions

### Language & Runtime

- **Python 3.10+**
- Chosen because: user is proficient in Python; widely used in research tooling

### LLM API

- **Zhipu AI API** (`open.bigmodel.cn`)
- Model: `glm-4-flash` (free tier available, strong Chinese output)
- SDK: fully compatible with the OpenAI Python SDK (`openai` package with custom `base_url`)
- Used for: title translation + structured abstract analysis (Phase 1); relevance scoring (Phase 2)
- API key stored in local environment variable `ZHIPU_API_KEY` (never committed to git)

### arXiv Data Source

- Use the **arXiv API** (`export.arxiv.org/api/query`) or parse the daily listing page
- Prefer the official API for reliability and rate-limit compliance
- Fetch papers submitted on the previous calendar day (arXiv updates at UTC 00:00)

### Scheduling

- **Tool**: Python `schedule` library or a system cron job
- **Run time**: 08:00 Copenhagen local time daily
- arXiv daily update completes at UTC 00:00; Copenhagen 08:00 CEST = UTC 06:00, ensuring all papers are available

### Markdown & PDF Generation

- Markdown written with standard formatting (headings, tables, bullet points)
- PDF generated from Markdown using **`weasyprint`** or **`pandoc`** (to be decided during implementation based on system availability)

### Email Delivery

- **Protocol**: SMTP (supports Gmail, Outlook, Yahoo, and custom SMTP servers)
- **Sender**: configured via `SMTP_USERNAME` environment variable
- **Recipient**: configured via `SMTP_RECIPIENTS` environment variable or `config.yaml`
- **Attachment**: the generated PDF / Markdown for that day

---

## Directory Structure

```
arxiv-daily-tracker/
├── main.py                  # Entry point (manual run)
├── scheduler.py             # Scheduled daily run
├── config.yaml              # User-configurable settings (category, language, etc.)
├── .env.example             # Template for API keys and email credentials
├── requirements.txt
├── SPEC.md
│
├── fetcher/
│   └── arxiv_fetcher.py     # Scrape arXiv API; defines Paper dataclass
│
├── processor/
│   └── translator.py        # Zhipu AI: title translation + structured abstract analysis
│
├── renderer/
│   ├── markdown_writer.py   # Generate daily .md file
│   └── pdf_exporter.py      # Convert .md to .pdf
│
├── notifier/
│   └── email_sender.py      # Send PDF via Gmail SMTP
│
└── output/
    └── YYYY-MM-DD/
        ├── quant-ph-YYYY-MM-DD.md
        └── quant-ph-YYYY-MM-DD.pdf
```

---

## Configuration (`config.yaml`)

```yaml
arxiv:
  categories:
    - quant-ph
  max_results: null          # Fetch all papers submitted that day (no limit)

llm:
  provider: zhipu
  model: glm-4-flash
  translation_language: zh   # Target language for translation

schedule:
  time: "08:00"              # Local time to run daily
  timezone: "Europe/Copenhagen"

output:
  directory: ./output
  formats:
    - markdown
    - pdf

email:
  enabled: true
  recipients:
    - recipient@example.com
```

---

## Phase Breakdown

### Phase 1 — MVP (Structured Analysis)

- [x] Fetch daily `quant-ph` papers from arXiv API
- [x] Translate title to Chinese via Zhipu AI API
- [x] Analyze abstract via Zhipu AI: output Core Value (1-2 sentence distillation) + highlighted EN abstract + highlighted ZH abstract in a single structured LLM call
- [x] Generate structured Markdown file (Core Value blockquote + bilingual highlighted abstracts)
- [x] Convert Markdown to PDF
- [x] Send PDF via Gmail SMTP
- [x] Support manual CLI trigger
- [x] Support scheduled daily run

### Phase 2 — Relevance Scoring

- [ ] Allow user to define research focus keywords/description in `config.yaml`
- [ ] Score each paper's relevance to user's research using Zhipu AI
- [ ] Sort daily output by relevance score (descending)
- [ ] Highlight top-N recommended papers

### Phase 3 — Advanced Configuration (Future)

- [ ] Multiple arXiv categories per run
- [ ] Per-user research profile for personalized ranking
- [ ] Digest mode: send only top-N papers instead of full listing

---

## Constraints & Notes

- Zhipu AI API (`open.bigmodel.cn`) is accessible from outside China (Copenhagen)
- Gmail SMTP requires an **App Password** (not the account password); 2FA must be enabled on the Gmail account
- arXiv API rate limit: max 1 request per 3 seconds; implement polite delays
- API keys and credentials must never be committed to the repository; use `.env` + `.gitignore`
- The tool should degrade gracefully: if analysis fails for a paper, log the error and include the original English abstract in the output
- LaTeX formulas (`$...$` and `$$...$$`) must survive the LLM analysis unchanged — the prompt explicitly forbids modifying any character inside formula delimiters
