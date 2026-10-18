# OLX Phone Data Pipeline

A comprehensive tool for scraping, enriching, and analyzing phone listings from OLX India.

## Features

- **Scraping**: Automated collection of phone listings from OLX across major Indian cities
- **Enrichment**: Match listings to phone specifications (GSMArena) and calculate metrics
- **Fraud Detection**: Rule-based detection of suspicious listings
- **Pricing Analysis**: Fair market value calculations and price trends
- **Analytics**: Market reports, deal finding, and anomaly detection

## Quick Start

```bash
# Install dependencies
pip install -e ".[dev]"

# Install Playwright browsers
playwright install chromium

# Set up environment
cp .env.example .env
# Edit .env with your database URL

# Run database migrations
alembic upgrade head

# Scrape listings
olx-data scrape --cities mumbai delhi --max-pages 5

# Enrich with phone specs
olx-data enrich --limit 1000

# Detect fraud
olx-data fraud --limit 1000

# Calculate fair prices
olx-data price

# Generate report
olx-data report --output reports --days 30

# Find deals
olx-data deals --city mumbai --days 7
```

## Commands

| Command | Description |
|---------|-------------|
| `scrape` | Scrape listings from OLX |
| `enrich` | Match listings to phone specifications |
| `fraud` | Run fraud detection |
| `price` | Calculate fair market prices |
| `report` | Generate analytics report |
| `deals` | Find potentially good deals |
| `anomalies` | Detect anomalous listings |
| `stats` | Show database statistics |
| `export` | Export data to CSV/JSON |

## Configuration

Create a `.env` file:

```env
DATABASE_URL=postgresql+asyncpg://user:pass@localhost/olx_data
LOG_LEVEL=INFO
HEADLESS=true
```

## Project Structure

```
src/
├── cli.py              # Main CLI entry point
├── storage/            # Database models and operations
├── scraper/            # OLX scraping logic
├── enrichment/         # Phone spec matching
├── fraud/              # Fraud detection
├── pricing/            # Price analysis
├── analytics/          # Reports and insights
└── utils/              # Logging and helpers
```

## Database Schema

- **raw_listings**: Raw scraped data from OLX
- **phone_specs**: Phone specifications from GSMArena
- **enriched_listings**: Listings matched to specs with metrics
- **fraud_analyses**: Fraud detection results
- **price_stats**: Calculated price statistics
- **collection_runs**: Scraping run metadata

## License

MIT