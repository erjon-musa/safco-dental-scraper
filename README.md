# Safco Dental Product Scraper

## What This Does

This project scrapes product data from [Safco Dental Supply](https://www.safcodental.com) and outputs it as clean, structured JSON and CSV files. Given a list of category URLs (e.g., "Gloves", "Sutures & Surgical Products"), it automatically discovers every product in those categories and extracts details like name, brand, SKU, price, availability, description, images, and specifications.

In the proof of concept run, it extracted **316 products across 2 categories** in a single automated pass.

## How It Works

The scraper is built as a pipeline of four specialized agents, each handling one job:

1. **Navigator** -- Starts from category pages, follows links, and builds a list of every product URL to visit. Recursively discovers subcategories by following `/catalog/` links and extracts product URLs from both HTML anchors and JSON-LD `ItemList` data. Tracks visited URLs to prevent cycles.

2. **Classifier** -- Determines page type using regex URL pattern matching (`/product/<slug>` = product detail, `/catalog/<slug>` = category listing). An optional LLM fallback exists for ambiguous pages but is never needed in practice.

3. **Extractor** -- Pulls product data using a 3-tier strategy: JSON-LD structured data first (Safco embeds rich `schema.org` data on every page), BeautifulSoup HTML parsing second, and an optional LLM fallback as a last resort. JSON-LD handles effectively 100% of pages. Each extraction calculates field completeness percentages for quality tracking.

4. **Validator** -- Validates products against business rules (required fields, price format, valid URLs) and deduplicates using a priority chain: SKU > URL > name+brand composite key. Generates a `QualityReport` with completeness metrics.

An **Orchestrator** coordinates all four agents, managing the flow from discovery through to final output. The entire pipeline is async, rate-limited, and resumable.

**No API keys or AI models are needed to run this.** The core pipeline is pure Python using HTTP requests and HTML/JSON parsing. The LLM fallback exists only as a safety net for hypothetical edge cases -- in practice, it is never triggered during normal operation.

## Architecture Overview

```
                          +------------------+
                          |   Orchestrator   |
                          | (Pipeline Coord) |
                          +--------+---------+
                                   |
              +--------------------+--------------------+
              |                    |                     |
     Phase 1  |           Phase 2 & 3          Phase 4  |
              v                    v                     v
    +---------+--------+  +-------+--------+   +--------+---------+
    | Navigator Agent  |  | Classifier     |   | Validator Agent  |
    | - Discover cats  |  | - URL patterns |   | - Field checks   |
    | - Build URL queue|  | - LLM fallback |   | - Deduplication  |
    | - Track visited  |  +-------+--------+   | - Quality report |
    +---------+--------+          |             +--------+---------+
              |                   v                      |
              |           +-------+--------+             |
              |           | Extractor Agent|             |
              |           | - JSON-LD      |             |
              |           | - BS4 HTML     |             |
              |           | - LLM fallback |             |
              |           +----------------+             |
              |                                          |
              +------------------+-----------------------+
                                 |
                                 v
                       +---------+---------+
                       |     Storage       |
                       | JSON / CSV / SQLite|
                       +-------------------+
```

## Agent Responsibilities

**NavigatorAgent** -- Discovers categories and subcategories from seed URLs. Recursively follows `/catalog/` links, extracts product URLs from HTML anchors and JSON-LD `ItemList` elements, and maintains a `visited_urls` set to prevent infinite loops. Produces a deduplicated queue of product URLs and a tree of `Category` objects.

**ClassifierAgent** -- Determines page type using regex URL pattern matching:
- `/product/<slug>` -- `product_detail` (confidence 0.95)
- `/catalog/<slug>` -- `category_listing` (confidence 0.9)
- `/catalog/<parent>/<child>` -- `subcategory_listing` (confidence 0.9)

For unmatched URLs, an optional async LLM fallback sends truncated HTML to Claude for classification. The LLM is optional; without an API key, unmatched pages are marked `unknown`.

**ExtractorAgent** -- Extracts product data using a 3-tier strategy:
1. **JSON-LD (primary)** -- Parses `<script type="application/ld+json">` tags for `Product` and `ItemList` schema.org types.
2. **BeautifulSoup HTML (fallback)** -- CSS class-based parsing when JSON-LD is absent.
3. **Claude LLM (last resort)** -- For pages where both methods fail. Never triggered in practice.

**ValidatorAgent** -- Validates products against business rules (non-empty name, valid URL, parseable price, valid image URLs). Deduplicates using a priority chain: normalized SKU, then normalized URL, then lowercase `name|brand` composite key. Generates a `QualityReport` with total/valid counts and per-field completeness.

## Project Structure

```
.
├── main.py                  # CLI entry point
├── config.yaml              # Scraping configuration
├── pyproject.toml           # Project metadata and dependencies
├── src/
│   ├── orchestrator.py      # Pipeline coordinator
│   ├── models.py            # Pydantic data models
│   ├── storage.py           # JSON/CSV/SQLite persistence
│   ├── rate_limiter.py      # Async rate limiter
│   ├── retry.py             # Exponential backoff retry decorator
│   ├── utils.py             # Config loading, logging setup, URL normalization
│   └── agents/
│       ├── navigator.py     # URL discovery and category tree building
│       ├── classifier.py    # Page type classification
│       ├── extractor.py     # Product data extraction (3-tier)
│       └── validator.py     # Validation and deduplication
├── tests/
│   ├── test_models.py       # Model validation tests
│   ├── test_extractor.py    # Extraction logic tests
│   ├── test_validator.py    # Validation and dedup tests
│   └── test_storage.py      # Storage persistence tests
└── output/                  # Generated output
    ├── products.json
    ├── products.csv
    ├── checkpoint.db
    └── crawl_log.txt
```

## Why This Approach

- **JSON-LD first**: Safco Dental embeds rich `schema.org` structured data on every page. Parsing this is more reliable than scraping arbitrary HTML selectors and yields clean, typed data with minimal post-processing.
- **Agent separation**: Each agent has a single responsibility, making the system testable in isolation and straightforward to extend.
- **Python + httpx + asyncio**: Safco serves fully rendered HTML with embedded JSON-LD, so there is no need for a heavyweight headless browser like Playwright or Selenium.
- **Pydantic models**: Every data structure (`Product`, `ClassificationResult`, `ExtractionResult`, `QualityReport`) is a Pydantic `BaseModel`, providing runtime type validation and clear data contracts between agents.

## Setup & Execution

### Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager

### Install

```bash
git clone <repo>
cd safco-dental-scraper
uv sync
```

### Configure (optional)

Edit `config.yaml` to adjust targets, rate limits, or output directory:

```yaml
targets:
  categories:
    - https://www.safcodental.com/catalog/sutures-surgical-products
    - https://www.safcodental.com/catalog/gloves
  base_url: https://www.safcodental.com

rate_limiting:
  delay_seconds: 2.0
  max_concurrent: 3

retry:
  max_retries: 3
  backoff_factor: 2.0
  retry_on_status: [429, 500, 502, 503, 504]
```

### Run

```bash
uv run python main.py                # Full run
uv run python main.py --resume       # Resume interrupted crawl
uv run python main.py --categories https://www.safcodental.com/catalog/gloves
uv run python main.py --output-dir ./my-output
uv run python main.py --config my-config.yaml
```

### Run Tests

```bash
uv run pytest tests/ -v
```

## Sample Output Schema

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | `string` | Yes | Product name |
| `brand` | `string` | No | Brand or manufacturer |
| `sku` | `string` | No | SKU / item number |
| `category_hierarchy` | `list[str]` | No | Category path, e.g. `["Gloves", "Nitrile"]` |
| `url` | `string` | Yes | Canonical product page URL |
| `price` | `string` | No | Price with currency symbol, e.g. `"$8.99"` |
| `unit_pack_size` | `string` | No | Pack size or unit information |
| `availability` | `string` | No | Stock status (e.g. `"In Stock"`) |
| `description` | `string` | No | Product description text |
| `specifications` | `dict[str, str]` | No | Key-value specification pairs |
| `image_urls` | `list[str]` | No | Product image URLs |
| `alternative_products` | `list[str]` | No | URLs of related products |

### Sample product (from actual output)

```json
{
  "name": "Myco Medical Technocut\u00ae Disposable Scalpels",
  "brand": "Safco Dental",
  "sku": "PFLXA",
  "category_hierarchy": [],
  "url": "https://www.safcodental.com/product/myco-medical-technocut-reg-disposable-scalpels",
  "price": "$8.99",
  "unit_pack_size": null,
  "availability": "In Stock",
  "description": "Non-slip, clear shield improves safety and enables easy blade size identification...",
  "specifications": {},
  "image_urls": ["https://www.safcodental.com/media/catalog/product/p/f/pflxa.jpg"],
  "alternative_products": []
}
```

## Production-Minded Design

### Reliability

- **Rate limiting**: Configurable delay between requests (`delay_seconds`) and concurrency cap (`max_concurrent`) using an async semaphore with timestamp-based minimum intervals.
- **Retry with exponential backoff**: Transient HTTP errors (429, 500, 502, 503, 504) trigger automatic retries with configurable backoff. The `retry_async` decorator handles this transparently.
- **Error isolation**: Individual URL failures are logged and marked as `failed` in the checkpoint database. One bad page does not take down the entire crawl.
- **Checkpoint and resume**: A SQLite database tracks every URL's status (`pending`, `in_progress`, `completed`, `failed`). Running with `--resume` picks up from where it left off without re-crawling completed URLs.

### Idempotency

Running the scraper multiple times produces the same result. Checkpoint-based skip logic prevents reprocessing, deduplication at output prevents duplicates, extraction is deterministic (same HTML = same output), and atomic checkpoint updates ensure crash-safe state transitions. This makes it safe for production scheduling (e.g., a daily cron job).

### Config-Driven Execution

All behavior is controlled through `config.yaml` -- target URLs, rate limits, retry policy, output directory, and LLM settings. No code changes are needed to adjust scraping parameters.

### Secrets Management

API keys are referenced by environment variable name in `config.yaml` (`api_key_env_var: ANTHROPIC_API_KEY`), never stored in code. For production, this extends naturally to secrets managers (AWS Secrets Manager, GCP Secret Manager, HashiCorp Vault) -- only the infrastructure changes, not the application code.

### Deployment Path

- **Containerization**: Package as a Docker container with env vars injected at runtime.
- **Scheduled execution**: Run on a cron job, AWS ECS Scheduled Tasks, Google Cloud Run Jobs, or an Airflow DAG.
- **Output pipeline**: Swap `storage.py` from local JSON/CSV to PostgreSQL, S3, or a message queue -- one file change, no agent logic affected.
- **Scaling**: Replace the in-process URL loop with a distributed task queue (Celery + Redis), add proxy rotation, and deploy on Kubernetes for horizontal scaling.

### Monitoring

The `ValidatorAgent` already generates field completeness reports. For production, extend with dashboards (Grafana), anomaly detection on extraction success rates, schema drift detection, and per-extraction-method tracking to catch site changes early.

## Limitations

- **Proof of concept scope**: 2 categories scraped by default. Add more URLs to `config.yaml` to expand.
- **No JavaScript rendering**: Relies on server-rendered HTML and JSON-LD. Sufficient for Safco Dental but would not work for SPAs.
- **Single-machine rate limiting**: No distributed coordination across multiple workers.
- **Single IP**: No proxy rotation. Large-scale runs could trigger IP blocks.
