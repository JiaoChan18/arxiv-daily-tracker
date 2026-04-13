# CLAUDE.md — arXiv Daily Tracker

This file provides guidance for Claude Code when working on this project.

---

## Project Overview

**arXiv Daily Tracker** is a Python CLI tool that:
1. Fetches all new papers submitted each day to the `quant-ph` category on arXiv
2. Analyzes each paper with Zhipu AI: translates the title to Chinese, then produces a structured output containing a Core Value distillation, a highlighted English abstract, and a highlighted Chinese translation — **专注于论文价值的深度提炼，不提供通识性科普**
3. Generates a structured Markdown report and converts it to PDF
4. Emails the PDF to the researcher automatically each morning

The tool runs on a daily schedule (08:00 Copenhagen time) and can also be triggered manually.

---

## Tech Stack

| Layer | Choice | Reason |
|-------|--------|--------|
| Language | Python 3.10+ | User is proficient in Python |
| arXiv data | arXiv API (`export.arxiv.org/api/query`) | Official, rate-limit compliant |
| LLM | Zhipu AI API (`glm-4-flash`) | Free tier available, OpenAI-SDK-compatible, strong Chinese output |
| PDF generation | `weasyprint` or `pandoc` | Decided at implementation time |
| Scheduling | `schedule` library or system cron | Simple, cross-platform |
| Email | Gmail SMTP + App Password | User has Gmail account |
| Config | `config.yaml` | Human-readable, easy for open-source users to adapt |
| Secrets | `.env` file loaded via `python-dotenv` | Never committed to git |

---

## Project Structure

```
arxiv-daily-tracker/
├── main.py                  # CLI entry point (manual run)
├── scheduler.py             # Daily scheduled runner
├── config.yaml              # User-configurable settings
├── .env.example             # Credentials template (commit this, not .env)
├── requirements.txt
├── SPEC.md                  # Full product specification
├── CLAUDE.md                # This file
│
├── fetcher/
│   └── arxiv_fetcher.py     # Fetch papers from arXiv API; defines Paper dataclass
│
├── processor/
│   └── translator.py        # Zhipu AI: title translation + structured abstract analysis
│
├── renderer/
│   ├── markdown_writer.py   # Write daily .md report
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

## Code Standards

### General

- All code must be **Python 3.10+** compatible
- Use **type hints** on all function signatures
- Keep functions small and single-purpose; avoid functions longer than ~50 lines
- Do not hardcode credentials, email addresses, or category names — read from `config.yaml` or `.env`

### Comments

- Every module must have a **docstring** at the top explaining what it does
- Every public function must have a **docstring** describing its purpose, parameters, and return value
- Add inline comments for non-obvious logic (e.g., pagination math, rate-limit delays, date offset calculations)
- Comment on *why*, not *what* — the code shows what; the comment explains the reasoning

Example:
```python
# arXiv updates at UTC 00:00; we fetch the previous day's submissions
# to ensure the daily listing is complete before we run at 06:00 UTC
target_date = datetime.utcnow().date() - timedelta(days=1)
```

### Output Contract (per paper)

Each paper processed by `translate_paper()` in `processor/translator.py` populates these fields on the `Paper` dataclass:

| Field | Type | Description |
|-------|------|-------------|
| `title_zh` | `str` | Chinese translation of the English title |
| `core_value` | `str` | 1–2 sentence direct statement of research contribution; never prefixed with "本文" boilerplate |
| `abstract_en_highlighted` | `str` | Original abstract with `**bold**` on research methods, key metrics, and conclusions; LaTeX formulas untouched |
| `abstract_zh` | `str` | Chinese translation with matching `**bold**` emphasis; LaTeX formulas preserved |

The LLM prompt uses section delimiters (`===CORE_VALUE===`, `===ABSTRACT_EN===`, `===ABSTRACT_ZH===`). If any delimiter is missing from the response, `_parse_analysis_output()` degrades gracefully to the original English abstract rather than crashing. `core_value` falls back to an empty string, and `markdown_writer.py` conditionally skips the blockquote block when it is empty.

### Error Handling

- **Never let the entire pipeline crash** because one paper fails. Wrap per-paper processing in try/except, log the error, and continue with the next paper.
- Use Python's `logging` module (not `print`) for all runtime messages. Default level: `INFO`; verbose mode: `DEBUG`.
- If the Zhipu AI API call fails for a paper, fall back to the original English title/abstract and log a warning.
- If PDF generation fails, still send the Markdown file as the email attachment and log the error.
- If email sending fails, log the error and exit with a non-zero status code so cron/scheduler can detect failure.
- All network requests (arXiv API, Zhipu AI API, SMTP) must have explicit **timeouts**.

Example pattern:
```python
for paper in papers:
    try:
        translate_paper(paper, client, model, max_retries)
    except Exception as e:
        logger.warning(f"Analysis failed for {paper.arxiv_id}: {e}. Using original text.")
```

### Security

- `ZHIPU_API_KEY` must be set as a local environment variable — never hardcode or commit it
- Use Gmail **App Password**, not the account password
- Do not log API keys or email credentials at any log level

### Dependencies

- Pin all dependencies in `requirements.txt` with exact versions (e.g., `requests==2.31.0`)
- Add a brief comment next to each dependency explaining its role

---

## Running the Tool

### Setup

```bash
# 1. Install dependencies
pip install -r requirements.txt

# 2. Copy and fill in credentials
cp .env.example .env
# Edit .env with your Zhipu AI API key and Gmail App Password

# 3. Review config
cat config.yaml
```

### Manual Run

```bash
# Fetch, analyze, generate PDF, and send email for today's papers
python main.py

# Fetch a specific date
python main.py --date 2025-04-11

# Dry run: fetch and analyze, but skip email sending
python main.py --no-email

# Verbose logging
python main.py --verbose
```

### Scheduled Run

```bash
# Start the scheduler (runs daily at 08:00 Copenhagen time)
python scheduler.py
```

### Running Tests

```bash
# Run all tests
pytest

# Run with coverage report
pytest --cov=. --cov-report=term-missing

# Run a specific module's tests
pytest tests/test_fetcher.py
pytest tests/test_translator.py
```

---

## Development Phases

| Phase | Status | Description |
|-------|--------|-------------|
| Phase 1 | Complete | Fetch + structured analysis (Core Value + highlighted EN/ZH abstracts) + Markdown + PDF + email |
| Phase 2 | Planned | Relevance scoring and recommendation ranking against user's research focus |
| Phase 3 | Future | User-defined research focus keywords in `config.yaml`; sort output by relevance score |

When implementing Phase 2 or 3, extend existing modules rather than rewriting them. The `processor/` directory is designed for this.

---

## Key Constraints

- **arXiv API rate limit**: wait at least 3 seconds between paginated requests
- **Zhipu AI API**: implement retry with exponential backoff (max 3 retries) for transient failures
- **All papers**: fetch the complete daily listing — `max_results` in `config.yaml` is `null` (no cap)
- **Graceful degradation**: partial failures must not block the rest of the pipeline
