#!/usr/bin/env python
"""
OLX Phone Data Pipeline - Full Pipeline Runner
This script runs the complete pipeline: scrape -> enrich -> fraud -> price -> report
"""

import asyncio
import argparse
import sys
import os
from datetime import datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'src'))

from src.cli import (
    cmd_scrape, cmd_enrich, cmd_fraud, cmd_price, cmd_report,
    cmd_deals, cmd_anomalies, cmd_stats, cmd_export
)
from src.storage import init_database, City
from src.utils.logging import setup_logging, get_logger

logger = get_logger(__name__)


class PipelineArgs:
    """Mock args object for running pipeline steps."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)


async def run_full_pipeline(
    cities: list = None,
    max_pages: int = 5,
    max_listings: int = 100,
    enrich_limit: int = 500,
    fraud_limit: int = 500,
    report_days: int = 30,
    deals_city: str = None,
    deals_days: int = 7,
    no_headless: bool = False,
    min_confidence: float = 0.5,
    log_level: str = "INFO",
    skip_scrape: bool = False,
    skip_enrich: bool = False,
    skip_fraud: bool = False,
    skip_price: bool = False,
    skip_report: bool = False,
):
    """Run the complete OLX data pipeline."""

    setup_logging(level=log_level)
    logger.info("Starting full OLX pipeline",
                cities=cities, max_pages=max_pages,
                enrich_limit=enrich_limit, fraud_limit=fraud_limit)

    start_time = datetime.utcnow()

    # Default cities if not specified
    if cities is None:
        cities = ["mumbai", "delhi", "bengaluru"]

    city_enums = [City(c) for c in cities]

    try:
        # Step 1: Scrape
        if not skip_scrape:
            logger.info("=" * 50)
            logger.info("STEP 1: SCRAPING LISTINGS FROM OLX")
            logger.info("=" * 50)

            scrape_args = PipelineArgs(
                cities=cities,
                max_pages=max_pages,
                max_listings=max_listings,
                no_headless=no_headless,
                log_level=log_level,
            )
            await cmd_scrape(scrape_args)
            logger.info("Scraping completed successfully")
        else:
            logger.info("Skipping scrape step")

        # Step 2: Enrich
        if not skip_enrich:
            logger.info("=" * 50)
            logger.info("STEP 2: ENRICHING WITH PHONE SPECIFICATIONS")
            logger.info("=" * 50)

            enrich_args = PipelineArgs(
                city=None,  # Enrich all cities
                limit=enrich_limit,
                min_confidence=min_confidence,
                log_level=log_level,
            )
            await cmd_enrich(enrich_args)
            logger.info("Enrichment completed successfully")
        else:
            logger.info("Skipping enrichment step")

        # Step 3: Fraud Detection
        if not skip_fraud:
            logger.info("=" * 50)
            logger.info("STEP 3: FRAUD DETECTION")
            logger.info("=" * 50)

            fraud_args = PipelineArgs(
                city=None,
                limit=fraud_limit,
                log_level=log_level,
            )
            await cmd_fraud(fraud_args)
            logger.info("Fraud detection completed successfully")
        else:
            logger.info("Skipping fraud detection step")

        # Step 4: Pricing Analysis
        if not skip_price:
            logger.info("=" * 50)
            logger.info("STEP 4: PRICING ANALYSIS")
            logger.info("=" * 50)

            price_args = PipelineArgs(log_level=log_level)
            await cmd_price(price_args)
            logger.info("Pricing analysis completed successfully")
        else:
            logger.info("Skipping pricing step")

        # Step 5: Generate Report
        if not skip_report:
            logger.info("=" * 50)
            logger.info("STEP 5: GENERATING ANALYTICS REPORT")
            logger.info("=" * 50)

            report_args = PipelineArgs(
                output="reports",
                days=report_days,
                log_level=log_level,
            )
            await cmd_report(report_args)
            logger.info("Report generation completed successfully")
        else:
            logger.info("Skipping report step")

        # Step 6: Show Stats
        logger.info("=" * 50)
        logger.info("STEP 6: DATABASE STATISTICS")
        logger.info("=" * 50)

        stats_args = PipelineArgs(log_level=log_level)
        await cmd_stats(stats_args)

        # Step 7: Find Deals
        logger.info("=" * 50)
        logger.info("STEP 7: FINDING GOOD DEALS")
        logger.info("=" * 50)

        deals_args = PipelineArgs(
            city=deals_city,
            max_price_pct=0.8,
            min_confidence=0.6,
            days=deals_days,
            log_level=log_level,
        )
        await cmd_deals(deals_args)

        # Step 8: Detect Anomalies
        logger.info("=" * 50)
        logger.info("STEP 8: DETECTING ANOMALIES")
        logger.info("=" * 50)

        anomalies_args = PipelineArgs(
            days=report_days,
            log_level=log_level,
        )
        await cmd_anomalies(anomalies_args)

        # Step 9: Export to CSV (automatic)
        logger.info("=" * 50)
        logger.info("STEP 9: EXPORTING DATA TO CSV")
        logger.info("=" * 50)

        export_dir = Path("exports")
        export_dir.mkdir(parents=True, exist_ok=True)

        # Export enriched listings to CSV
        export_args = PipelineArgs(
            type="enriched",
            format="csv",
            output=str(export_dir / "enriched_listings.csv"),
            limit=10000,
            log_level=log_level,
        )
        await cmd_export(export_args)

        # Export raw listings to CSV
        export_args = PipelineArgs(
            type="listings",
            format="csv",
            output=str(export_dir / "raw_listings.csv"),
            limit=10000,
            log_level=log_level,
        )
        await cmd_export(export_args)

        # Export fraud analyses to CSV
        export_args = PipelineArgs(
            type="fraud",
            format="csv",
            output=str(export_dir / "fraud_analyses.csv"),
            limit=10000,
            log_level=log_level,
        )
        await cmd_export(export_args)

        # Export phone specs to CSV
        export_args = PipelineArgs(
            type="specs",
            format="csv",
            output=str(export_dir / "phone_specs.csv"),
            limit=10000,
            log_level=log_level,
        )
        await cmd_export(export_args)

        elapsed = datetime.utcnow() - start_time
        logger.info("=" * 50)
        logger.info(f"PIPELINE COMPLETED SUCCESSFULLY in {elapsed}")
        logger.info("=" * 50)

        # Print summary of where data is saved
        print("\n" + "=" * 60)
        print("PIPELINE COMPLETE - DATA LOCATIONS:")
        print("=" * 60)
        print(f"Database:          data/olx_data.db (SQLite)")
        print(f"Reports:           reports/ (HTML/JSON reports)")
        print(f"Logs:              logs/olx_data.log")
        print(f"Exports (CSV):     exports/")
        print(f"  - enriched_listings.csv  - Enriched phone listings with specs & pricing")
        print(f"  - raw_listings.csv       - Raw scraped data from OLX")
        print(f"  - fraud_analyses.csv     - Fraud detection results")
        print(f"  - phone_specs.csv        - Phone specifications from GSMArena")
        print(f"Raw data cache:    data/raw/")
        print(f"Enriched data:     data/enriched/")
        print("=" * 60)
        print("\nOpen CSV files in Excel:")
        print("  exports/enriched_listings.csv  <- Best for analysis")
        print("  exports/fraud_analyses.csv     <- Check for fraud")
        print("  exports/raw_listings.csv       <- All raw data")
        print("=" * 60)
        print("\nKey Commands for Further Analysis:")
        print("  python run_pipeline.py --skip-scrape --skip-enrich --skip-fraud --skip-price")
        print("  olx-data stats                           # Database statistics")
        print("  olx-data deals --city mumbai --days 7   # Find deals in Mumbai")
        print("  olx-data report --output reports --days 30  # Regenerate report")
        print("=" * 60)

    except KeyboardInterrupt:
        logger.info("Pipeline interrupted by user")
        return 130
    except Exception as e:
        logger.exception("Pipeline failed", error=str(e))
        return 1

    return 0


def main():
    parser = argparse.ArgumentParser(
        description="Run the complete OLX Phone Data Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Run full pipeline with defaults
  python run_pipeline.py

  # Run with specific cities and more pages
  python run_pipeline.py --cities mumbai delhi --max-pages 10 --max-listings 500

  # Skip scraping (use existing data) and run enrichment onwards
  python run_pipeline.py --skip-scrape --enrich-limit 2000

  # Quick test run (1 page per city, headless off to see browser)
  python run_pipeline.py --max-pages 1 --max-listings 5 --no-headless

  # Only generate report from existing data
  python run_pipeline.py --skip-scrape --skip-enrich --skip-fraud --skip-price
        """
    )

    # Scraping options
    parser.add_argument("--cities", nargs="+",
                        choices=[c.value for c in City],
                        default=["mumbai", "delhi", "bengaluru"],
                        help="Cities to scrape (default: mumbai delhi bengaluru)")
    parser.add_argument("--max-pages", type=int, default=5,
                        help="Max pages per city per query (default: 5)")
    parser.add_argument("--max-listings", type=int, default=100,
                        help="Max listings per city (default: 100)")
    parser.add_argument("--no-headless", action="store_true",
                        help="Run browser in visible mode (for debugging)")

    # Enrichment options
    parser.add_argument("--enrich-limit", type=int, default=500,
                        help="Max listings to enrich (default: 500)")
    parser.add_argument("--min-confidence", type=float, default=0.5,
                        help="Minimum match confidence for enrichment (default: 0.5)")

    # Fraud options
    parser.add_argument("--fraud-limit", type=int, default=500,
                        help="Max listings for fraud detection (default: 500)")

    # Report options
    parser.add_argument("--report-days", type=int, default=30,
                        help="Days of data for report (default: 30)")

    # Deals options
    parser.add_argument("--deals-city", choices=[c.value for c in City],
                        help="City for deals search (default: all)")
    parser.add_argument("--deals-days", type=int, default=7,
                        help="Days of data for deals (default: 7)")

    # Skip options
    parser.add_argument("--skip-scrape", action="store_true",
                        help="Skip scraping step")
    parser.add_argument("--skip-enrich", action="store_true",
                        help="Skip enrichment step")
    parser.add_argument("--skip-fraud", action="store_true",
                        help="Skip fraud detection step")
    parser.add_argument("--skip-price", action="store_true",
                        help="Skip pricing analysis step")
    parser.add_argument("--skip-report", action="store_true",
                        help="Skip report generation step")

    # Global options
    parser.add_argument("--log-level", default="INFO",
                        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
                        help="Log level (default: INFO)")

    args = parser.parse_args()

    return asyncio.run(run_full_pipeline(
        cities=args.cities,
        max_pages=args.max_pages,
        max_listings=args.max_listings,
        enrich_limit=args.enrich_limit,
        fraud_limit=args.fraud_limit,
        report_days=args.report_days,
        deals_city=args.deals_city,
        deals_days=args.deals_days,
        no_headless=args.no_headless,
        min_confidence=args.min_confidence,
        log_level=args.log_level,
        skip_scrape=args.skip_scrape,
        skip_enrich=args.skip_enrich,
        skip_fraud=args.skip_fraud,
        skip_price=args.skip_price,
        skip_report=args.skip_report,
    ))


if __name__ == "__main__":
    sys.exit(main())