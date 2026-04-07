# Safco Dental Product Scraper

## What This Does

This project scrapes product data from [Safco Dental Supply](https://www.safcodental.com) and outputs it as clean, structured JSON and CSV files. Given a list of category URLs (e.g., "Gloves", "Sutures & Surgical Products"), it automatically discovers every product in those categories and extracts details like name, brand, SKU, price, availability, description, images, and specifications.

In the proof of concept run, it extracted **316 products across 2 categories** in a single automated pass.

## How It Works

The scraper is built as a pipeline of four specialized agents, each handling one job:

1. **Navigator** -- Starts from category pages, follows links, and builds a list of every product URL to visit. Think of it as the "map builder."
2. **Classifier** -- Looks at each URL and determines what kind of page it is (category listing vs. product detail) using simple pattern matching.
3. **Extractor** -- Visits each product page and pulls out structured data. It primarily reads JSON-LD -- machine-readable product info that Safco Dental already embeds in every page -- so extraction is fast, reliable, and requires no AI.
4. **Validator** -- Checks the extracted data for quality (missing fields, bad prices, duplicate entries) and deduplicates the results.

An **Orchestrator** coordinates all four agents, managing the flow from discovery through to final output. The entire pipeline is async, rate-limited, and resumable -- if it gets interrupted, it picks up where it left off.

**No API keys or AI models are needed to run this.** The core pipeline is pure Python using HTTP requests and HTML/JSON parsing. An optional LLM fallback exists for edge cases but is never triggered in normal operation.

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

**Pipeline flow:**

1. **Discovery** -- The Navigator Agent crawls seed category URLs, discovers subcategories and product links by parsing HTML anchors and JSON-LD `ItemList` data, and builds a deduplicated URL queue. Visited URLs are tracked to prevent cycles.

2. **Classification** -- The Classifier Agent determines each page's type (`category_listing`, `product_detail`, `subcategory_listing`) using URL pattern matching. For ambiguous pages, it falls back to an LLM classification call.

3. **Extraction** -- The Extractor Agent pulls product data from each page using a 3-tier strategy: JSON-LD structured data first, BeautifulSoup HTML parsing second, and Claude LLM as a last resort.

4. **Validation & Deduplication** -- The Validator Agent checks required fields, price format, and URL validity. Deduplication runs with a priority chain: SKU > URL > name+brand composite key.

5. **Storage** -- Output is saved as JSON and CSV files, with per-category splits. A SQLite checkpoint database tracks crawl progress for resumability.

## Why This Approach

- **JSON-LD first**: Safco Dental embeds rich `schema.org` structured data (`Product`, `ItemList`, `Offer` types) in every page. Parsing this is more reliable than scraping arbitrary HTML selectors, and it yields clean, typed data with minimal post-processing.

- **Agent separation**: Each agent has a single responsibility. The Navigator knows nothing about extraction; the Extractor knows nothing about URL discovery. This makes the system testable in isolation and straightforward to extend (e.g., swap the Extractor strategy without touching navigation).

- **Python + httpx + asyncio**: A lightweight async HTTP stack. Safco Dental serves fully rendered HTML with embedded JSON-LD, so there is no need for a heavyweight headless browser like Playwright or Selenium. `httpx` provides async HTTP/2 support, connection pooling, and redirect handling out of the box.

- **LLM used selectively**: Claude is only invoked as a fallback -- for classifying ambiguous pages that do not match URL patterns, and for extracting data from irregular pages where JSON-LD and HTML parsing both fail. This keeps costs low and latency predictable while retaining a safety net for edge cases.

- **Pydantic models**: Every data structure (`Product`, `CrawlState`, `ClassificationResult`, `ExtractionResult`, `QualityReport`) is a Pydantic `BaseModel`. This provides runtime type validation, serialization, and clear documentation of the data contracts between agents.

## Agent Responsibilities

### NavigatorAgent
Discovers categories and subcategories from seed URLs. Recursively follows `/catalog/` links that are deeper than the current page depth. Extracts product URLs from both HTML `<a>` tags (matching `/product/` paths) and JSON-LD `ItemList` elements. Maintains a `visited_urls` set to prevent infinite loops on circular link structures. Produces a deduplicated queue of product URLs and a tree of `Category` objects.

### ClassifierAgent
Determines page type using regex-based URL pattern matching:
- `/product/<slug>` -- `product_detail` (confidence 0.95)
- `/catalog/<slug>` -- `category_listing` (confidence 0.9)
- `/catalog/<parent>/<child>` -- `subcategory_listing` (confidence 0.9)

For URLs that match none of these patterns, an async LLM fallback sends the first 2,000 characters of HTML to Claude for classification (confidence 0.7). The LLM is optional; without an API key, unmatched pages are marked `unknown`.

### ExtractorAgent
Extracts product data using a 3-tier strategy:

1. **JSON-LD (primary)** -- Parses `<script type="application/ld+json">` tags for `Product` and `ItemList` schema.org types. Extracts name, brand, SKU, price, availability, description, images, specifications, and category hierarchy directly from the structured data.
2. **BeautifulSoup HTML (fallback)** -- If no JSON-LD is found, falls back to CSS class-based parsing: product cards on listing pages, `<h1>` / price / SKU / description elements on detail pages.
3. **Claude LLM (last resort)** -- For pages where both methods fail, sends truncated HTML to Claude with a structured extraction prompt. Parses the JSON response into `Product` objects.

Each extraction also calculates field completeness percentages for quality tracking.

### ValidatorAgent
Validates extracted products against business rules:
- **Required fields**: `name` must be non-empty, `url` must be a valid URL
- **Price format**: If present, must be parseable as a numeric value (after stripping `$` and `,`)
- **SKU format**: If present, must not be an empty string
- **Image URLs**: Must start with `http://`, `https://`, or `//`

Deduplication uses a priority chain: first by normalized SKU, then by normalized URL, then by lowercase `name|brand` composite key. Generates a `QualityReport` with total/valid counts and per-field completeness percentages.

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

Edit `config.yaml` to adjust rate limits, target categories, output directory, or LLM settings:

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

**No API key is needed to run this scraper.** The primary extraction pipeline is entirely non-LLM: JSON-LD structured data parsing handles the vast majority of pages, with BeautifulSoup HTML parsing as the second tier. These two methods cover effectively 100% of Safco Dental's catalog since every page embeds rich `schema.org` structured data. The LLM fallback (Claude) exists only as a last-resort safety net for hypothetical edge cases where both JSON-LD and HTML parsing fail -- in practice, this path is never triggered during normal operation. The scraper is fully functional, fast, and free to run without any API key.

If you still want to enable the LLM fallback for maximum coverage on irregular or future pages:

```bash
export ANTHROPIC_API_KEY="sk-ant-..."
```

### Run

```bash
# Full run with default config
uv run python main.py

# Resume an interrupted crawl from checkpoint
uv run python main.py --resume

# Scrape specific categories only
uv run python main.py --categories https://www.safcodental.com/catalog/gloves

# Custom output directory
uv run python main.py --output-dir ./my-output

# Custom config file
uv run python main.py --config my-config.yaml
```

### Run Tests

```bash
uv run pytest tests/ -v
```

## Sample Output Schema

The `Product` model defines the following fields:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | `string` | Yes | Product name |
| `brand` | `string` | No | Brand or manufacturer |
| `sku` | `string` | No | SKU / item number |
| `category_hierarchy` | `list[str]` | No | Category path, e.g. `["Gloves", "Nitrile"]` |
| `url` | `string` | Yes | Canonical product page URL |
| `price` | `string` | No | Price with currency symbol, e.g. `"$8.99"` |
| `unit_pack_size` | `string` | No | Pack size or unit information |
| `availability` | `string` | No | Stock status (e.g. `"In Stock"`, `"Out of Stock"`) |
| `description` | `string` | No | Product description text |
| `specifications` | `dict[str, str]` | No | Key-value specification pairs |
| `image_urls` | `list[str]` | No | Product image URLs |
| `alternative_products` | `list[str]` | No | URLs of related / alternative products |

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
  "image_urls": [
    "https://www.safcodental.com/media/catalog/product/p/f/pflxa.jpg?width=265&height=265&canvas=265,265&optimize=medium&fit=bounds"
  ],
  "alternative_products": []
}
```

Output files are written to the `output/` directory:
- `products.json` -- All products as a JSON array
- `products.csv` -- Flattened CSV with all products
- `<category-name>.json` -- Per-category JSON files
- `checkpoint.db` -- SQLite crawl state for resume support
- `crawl_log.txt` -- Detailed log of the crawl run

**POC results**: 316 products extracted across 2 categories (Sutures & Surgical Products, Gloves).

## Limitations

- **POC scope**: Only 2 categories are scraped by default, not the full Safco Dental catalog. The system is designed to handle more -- just add URLs to `config.yaml`.
- **No JavaScript rendering**: Relies on server-rendered HTML and embedded JSON-LD. This is sufficient for Safco Dental, which serves complete pages without client-side rendering, but would not work for SPAs.
- **LLM features require API key**: The JSON-LD and HTML extraction tiers work without an API key, but the LLM fallback for classification and extraction on irregular pages requires an Anthropic API key.
- **Rate limiting is single-machine**: The `RateLimiter` uses an in-process `asyncio.Semaphore` and timestamp tracking. There is no distributed coordination across multiple worker processes or machines.
- **No proxy rotation**: All requests originate from a single IP. On large-scale runs, this could trigger rate limiting or IP blocks from the target site.

## Failure Handling

- **Retry with exponential backoff**: Transient HTTP errors (429, 500, 502, 503, 504) trigger automatic retries with configurable backoff (`backoff_factor: 2.0`, `max_retries: 3`). The `retry_async` decorator handles this transparently.

- **Checkpoint and resume**: A SQLite database (`checkpoint.db`) tracks every URL's crawl status (`pending`, `in_progress`, `completed`, `failed`). If the process is interrupted (Ctrl+C, crash, network failure), running with `--resume` picks up from where it left off without re-crawling completed URLs.

- **Error isolation**: Individual URL failures are logged and the URL is marked as `failed` in the checkpoint DB, but the pipeline continues processing remaining URLs. One bad page does not take down the entire crawl.

- **Rate limiting**: A configurable delay between requests (`delay_seconds: 2.0`) and concurrency cap (`max_concurrent: 3`) prevent overwhelming the target server. The `RateLimiter` uses an async semaphore with timestamp-based minimum intervals.

- **Validation gates**: The Validator Agent catches extraction errors (missing names, malformed prices, invalid URLs) before they propagate to the final output. A quality report summarizes data integrity across the full result set.

## Idempotency

Running the scraper multiple times produces the same final result without creating duplicates or corrupting state. This is achieved through several reinforcing mechanisms:

- **Checkpoint-based skip logic**: The SQLite checkpoint database records every URL's status (`pending`, `in_progress`, `completed`, `failed`). On a fresh run, URLs are registered before processing. On a resumed run (`--resume`), already-completed URLs are skipped entirely -- no redundant HTTP requests, no duplicate extraction work. This means running `python main.py` followed by `python main.py --resume` does not re-process anything.

- **Deduplication at output**: Even if the same product appears on multiple pages (e.g., listed in two categories), the Validator Agent deduplicates using a priority chain: SKU match first, then normalized URL, then a composite `name|brand` key. The same product discovered twice converges to a single output record.

- **Deterministic extraction**: The JSON-LD and HTML parsing strategies are stateless and deterministic -- given the same HTML input, they produce the same `Product` output. There is no randomness or order-dependence in the extraction logic.

- **Atomic checkpoint updates**: URL status transitions (`pending` -> `in_progress` -> `completed`/`failed`) are written to SQLite as individual upserts. If the process crashes mid-crawl, partially processed URLs remain marked as `in_progress` and will be retried on resume rather than silently skipped or double-counted.

The net effect: you can run the scraper as many times as you want -- against the same config, it converges to the same output. This is important for production scheduling (e.g., a daily cron job) where you need confidence that reruns do not inflate product counts or leave inconsistent state.

## Deployment Path

This POC runs locally with `uv run python main.py`. To move toward production, the deployment would follow these stages:

### Stage 1: Containerization

Package the scraper as a Docker container for consistent, reproducible runs across environments:

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN pip install uv && uv sync --frozen
COPY src/ src/
COPY main.py config.yaml ./
CMD ["uv", "run", "python", "main.py"]
```

Environment variables (`ANTHROPIC_API_KEY`) are injected at runtime via `docker run -e` or a secrets manager -- never baked into the image.

### Stage 2: Scheduled Execution

For recurring crawls (e.g., daily price updates), deploy the container on a scheduler:

- **Simple**: A cron job or systemd timer on a single server running `docker run` on a schedule.
- **Cloud-native**: AWS ECS Scheduled Tasks, Google Cloud Run Jobs, or Azure Container Instances with a timer trigger. These provide automatic retries, logging integration, and no idle compute costs.
- **Orchestrated**: Airflow or Prefect DAG that runs the container as a task, with built-in monitoring, alerting, and dependency management.

### Stage 3: Secrets Management

Move API keys out of environment variables and into a managed secrets store:

- **AWS**: Secrets Manager or SSM Parameter Store, injected into ECS task definitions.
- **GCP**: Secret Manager, mounted as environment variables in Cloud Run.
- **Self-hosted**: HashiCorp Vault with application-level secret fetching.

The `config.yaml` field `api_key_env_var: ANTHROPIC_API_KEY` already abstracts the key name from the value, so the application code does not change -- only the infrastructure that provides the environment variable.

### Stage 4: Output Pipeline

Replace local file output with a persistent data store:

- Write extracted products to PostgreSQL or MongoDB instead of JSON/CSV files.
- Push results to an S3 bucket or GCS for downstream consumers.
- Emit events to a message queue (SQS, Pub/Sub) for real-time processing by other systems.

The `storage.py` module is the single integration point -- swapping `save_json`/`save_csv` for a database writer requires changes in one file without touching any agent logic.

## Scaling to Full-Site Crawling

This POC demonstrates the architecture on 2 categories. To scale to the full Safco Dental catalog (or similar sites), the following changes would be appropriate:

- **Distributed task queue**: Replace the in-process URL loop with Celery or RQ workers consuming from a shared task queue. Each worker runs the same agent pipeline but pulls URLs independently.

- **Message broker for URL management**: Use Redis or RabbitMQ to manage the URL frontier, with deduplication at the queue level to prevent redundant crawls across workers.

- **Proxy rotation pool**: Distribute requests across a pool of rotating proxies to avoid IP-based rate limiting and reduce the risk of blocks.

- **Persistent database storage**: Replace JSON/CSV output with PostgreSQL (for relational queries and joins) or MongoDB (for flexible document storage). This enables incremental writes, concurrent access, and richer querying.

- **Container orchestration**: Package the scraper as a Docker container and deploy on Kubernetes for horizontal scaling. Auto-scale workers based on queue depth.

- **Incremental crawling with change detection**: Store content hashes per URL and only re-extract products when the page content has changed. This reduces unnecessary work on recurring crawls.

- **Priority queuing**: Assign priority scores to categories based on business importance (e.g., high-revenue product lines first) so the most valuable data is extracted earliest.

## Monitoring Data Quality

The system already generates field completeness reports via the `ValidatorAgent.quality_report()` method. For production use, this would be extended with:

- **Field completeness dashboards**: Track completeness percentages per field over time. The existing `QualityReport` model provides `total_products`, `valid_products`, `duplicates_removed`, and per-field completeness -- pipe these to a time-series database (InfluxDB, Prometheus) and visualize in Grafana.

- **Anomaly detection**: Alert when the extraction success rate drops below a threshold (e.g., less than 80% of pages yielding products). A sudden drop could indicate site structure changes or IP blocking.

- **Schema drift detection**: Compare the current extraction output schema against a stored baseline. If new fields appear or existing fields consistently return null, flag for review -- the site may have restructured its JSON-LD or HTML.

- **Automated regression tests**: Maintain a suite of snapshot tests against known product pages. Run these on a schedule to detect when the extraction logic needs updating due to site changes.

- **Per-extraction-method tracking**: Monitor the ratio of JSON-LD vs. HTML vs. LLM extractions. A shift away from JSON-LD (the most reliable method) toward fallbacks signals potential issues with the primary extraction path.

