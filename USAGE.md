# Usage

## Run for today

```bash
python main.py
```

No flags needed. `main.py` calls `get_arxiv_latest_date()` (main.py:49), which uses ET time and arXiv's 20:00 ET announce schedule to auto-pick the latest available batch:

| System time (ET)              | Target date resolved to |
|-------------------------------|-------------------------|
| Weekday before 20:00 ET       | Previous business day   |
| Weekday 20:00 ET or later     | Today                   |
| Saturday                      | Previous Friday         |
| Sunday                        | Previous Friday         |

If the resolved batch is empty (weekend/holiday), the fetcher auto-falls-back up to 7 days until it finds papers (main.py:166,188).

## CLI parameters

| Flag              | Type   | Default   | Purpose                                                          |
|-------------------|--------|-----------|------------------------------------------------------------------|
| `--date YYYY-MM-DD` | str    | *(auto)*  | Run for a specific historical date. Bypasses auto-detection. Uses arXiv Search API instead of RSS. |
| `--no-email`      | flag   | off       | Dry run: fetch + translate + render, but skip SMTP send.         |
| `--verbose`       | flag   | off       | DEBUG-level logging (shows RSS entry parsing, API URLs, etc.).   |

## Common recipes

```bash
# Normal daily run (fetch + translate + PDF + email)
python main.py

# Dry run — produce the report locally, don't email anyone
python main.py --no-email

# Debug a specific historical date
python main.py --date 2026-04-09 --verbose

# Scheduled mode: runs main() daily at the time set in config.yaml
python scheduler.py
```

## Output

Report files land in:

```
output/YYYY-MM-DD/
  quant-ph-YYYY-MM-DD.md
  quant-ph-YYYY-MM-DD.pdf
```

Where `YYYY-MM-DD` is the resolved `target_date`, **not** the wall-clock date you ran the script on. Running with `--date 2025-04-13` will produce `output/2025-04-13/` even if today is 2026.

## Prerequisites

- `.env` with `ZHIPU_API_KEY` and Gmail App Password (see `.env.example`)
- `config.yaml` present in project root (categories, SMTP host/port, recipients)
- `pandoc` + `xelatex` installed on `$PATH` for PDF generation; falls back to sending the `.md` if PDF export fails
