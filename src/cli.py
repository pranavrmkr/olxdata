"""
Main CLI entry point for OLX phone data pipeline.
"""

import asyncio
import argparse
import sys
from datetime import datetime
from pathlib import Path
from typing import Optional, List

from .storage import Database, init_database, City, Condition
from .scraper import run_scraping_pipeline, OLXScraper
from .enrichment import EnrichmentEngine
from .fraud import run_fraud_detection
from .pricing import run_pricing_analysis
from .analytics import generate_full_report, AnalyticsEngine
from .utils.logging import setup_logging, get_logger

logger = get_logger(__name__)


async def cmd_scrape(args):
    """Scrape listings from OLX."""
    logger.info("Starting scrape", cities=args.cities, max_pages=args.max_pages)

    db = await init_database()
    try:
        config = {
            "scraper": {
                "max_pages_per_city": args.max_pages,
                "max_listings_per_model": args.max_listings,
                "headless": not args.no_headless,
                "delay_min": 3,
                "delay_max": 8,
                "timeout": 30,
            }
        }
        cities = [City(c) for c in args.cities]
        await run_scraping_pipeline(
            db=db,
            cities=cities,
            config=config,
        )
    finally:
        await db.close()

    logger.info("Scraping complete")


async def cmd_enrich(args):
    """Enrich listings with phone specifications."""
    logger.info("Starting enrichment", city=args.city, limit=args.limit)

    db = await init_database()
    try:
        engine = EnrichmentEngine(db)
        results = await engine.enrich_all_listings(
            city=City(args.city) if args.city else None,
            limit=args.limit,
            min_confidence=args.min_confidence,
        )
        logger.info("Enrichment complete", enriched_count=len(results))
    finally:
        await db.close()


async def cmd_fraud(args):
    """Run fraud detection on enriched listings."""
    logger.info("Starting fraud detection", city=args.city, limit=args.limit)

    db = await init_database()
    try:
        results = await run_fraud_detection(
            db=db,
            city=City(args.city) if args.city else None,
            limit=args.limit,
        )
        high_risk = sum(1 for r in results if r.risk_level.value in ("high", "critical"))
        logger.info("Fraud detection complete", total=len(results), high_risk=high_risk)
    finally:
        await db.close()


async def cmd_price(args):
    """Calculate fair market prices."""
    logger.info("Starting pricing analysis")

    db = await init_database()
    try:
        specs = await db.get_all_phone_specs()
        spec_ids = [s.id for s in specs]

        results = await run_pricing_analysis(
            db=db,
            phone_spec_ids=spec_ids,
        )
        logger.info("Pricing analysis complete", stats_count=len(results))
    finally:
        await db.close()


async def cmd_report(args):
    """Generate analytics report."""
    logger.info("Generating report", output_dir=args.output, days=args.days)

    db = await init_database()
    try:
        result = await generate_full_report(db, args.output, args.days)
        logger.info("Report generated", path=result["report_path"], summary=result["summary"])
        print(f"Report saved to: {result['report_path']}")
    finally:
        await db.close()


async def cmd_deals(args):
    """Find good deals."""
    logger.info("Finding deals", city=args.city, max_price_pct=args.max_price_pct)

    db = await init_database()
    try:
        engine = AnalyticsEngine(db)
        deals = await engine.find_deals(
            max_price_vs_market=args.max_price_pct,
            min_confidence=args.min_confidence,
            city=City(args.city) if args.city else None,
            days_back=args.days,
        )

        print(f"Found {len(deals)} potential deals:")
        for i, deal in enumerate(deals[:20], 1):
            print(f"{i}. {deal['brand']} {deal['model']} {deal['variant'] or ''} - "
                  f"₹{deal['price']:,} ({deal['price_vs_msrp_pct']:.1f}% of MSRP) - "
                  f"{deal['city']} - {deal['condition']}")
    finally:
        await db.close()


async def cmd_anomalies(args):
    """Detect anomalous listings."""
    logger.info("Detecting anomalies", days=args.days)

    db = await init_database()
    try:
        engine = AnalyticsEngine(db)
        anomalies = await engine.detect_anomalies(days_back=args.days)

        print(f"Found {len(anomalies)} anomalies:")
        by_type = {}
        for a in anomalies:
            by_type.setdefault(a["type"], []).append(a)

        for atype, items in by_type.items():
            print(f"\n{atype} ({len(items)}):")
            for item in items[:5]:
                print(f"  - {item['listing_id']}: {item['title'][:60]} - ₹{item['price']:,}")
    finally:
        await db.close()


async def cmd_stats(args):
    """Show database statistics."""
    db = await init_database()
    try:
        stats = await db.get_statistics()
        print("\n=== Database Statistics ===")
        for key, value in stats.items():
            print(f"  {key}: {value}")
    finally:
        await db.close()


async def cmd_export(args):
    """Export data to CSV/JSON."""
    logger.info("Exporting data", format=args.format, output=args.output)

    db = await init_database()
    try:
        if args.type == "listings":
            listings = await db.get_raw_listings(
                city=City(args.city) if args.city else None,
                limit=args.limit,
            )
            data = [l.to_dict() for l in listings]
        elif args.type == "enriched":
            listings = await db.get_enriched_listings(
                city=City(args.city) if args.city else None,
                limit=args.limit,
            )
            data = [l.to_dict() for l in listings]
        elif args.type == "specs":
            specs = await db.get_all_phone_specs()
            data = [s.to_dict() for s in specs]
        elif args.type == "fraud":
            analyses = await db.get_fraud_analyses(limit=args.limit)
            data = [a.to_dict() for a in analyses]
        else:
            print(f"Unknown export type: {args.type}")
            return

        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        if args.format == "json":
            import json
            with open(output_path, "w") as f:
                json.dump(data, f, indent=2, default=str)
        elif args.format == "csv":
            import csv
            if data:
                with open(output_path, "w", newline="", encoding="utf-8") as f:
                    writer = csv.DictWriter(f, fieldnames=data[0].keys())
                    writer.writeheader()
                    writer.writerows(data)
        else:
            print(f"Unknown format: {args.format}")
            return

        logger.info("Export complete", records=len(data), path=args.output)
        print(f"Exported {len(data)} records to {args.output}")

    finally:
        await db.close()


def create_parser():
    """Create argument parser."""
    parser = argparse.ArgumentParser(
        description="OLX Phone Data Pipeline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Scrape command
    scrape = subparsers.add_parser("scrape", help="Scrape listings from OLX")
    scrape.add_argument("--cities", nargs="+", choices=[c.value for c in City],
                        default=[c.value for c in City], help="Cities to scrape")
    scrape.add_argument("--max-pages", type=int, default=10, help="Max pages per city")
    scrape.add_argument("--max-listings", type=int, default=500, help="Max listings per city")
    scrape.add_argument("--no-headless", action="store_true", help="Run browser in visible mode")

    # Enrich command
    enrich = subparsers.add_parser("enrich", help="Enrich listings with phone specs")
    enrich.add_argument("--city", choices=[c.value for c in City], help="Filter by city")
    enrich.add_argument("--limit", type=int, default=1000, help="Max listings to enrich")
    enrich.add_argument("--min-confidence", type=float, default=0.5, help="Min match confidence")

    # Fraud command
    fraud = subparsers.add_parser("fraud", help="Run fraud detection")
    fraud.add_argument("--city", choices=[c.value for c in City], help="Filter by city")
    fraud.add_argument("--limit", type=int, default=1000, help="Max listings to analyze")

    # Price command
    price = subparsers.add_parser("price", help="Calculate fair market prices")

    # Report command
    report = subparsers.add_parser("report", help="Generate analytics report")
    report.add_argument("--output", default="reports", help="Output directory")
    report.add_argument("--days", type=int, default=30, help="Days of data to include")

    # Deals command
    deals = subparsers.add_parser("deals", help="Find good deals")
    deals.add_argument("--city", choices=[c.value for c in City], help="Filter by city")
    deals.add_argument("--max-price-pct", type=float, default=0.8, help="Max price vs market (0-1)")
    deals.add_argument("--min-confidence", type=float, default=0.6, help="Min match confidence")
    deals.add_argument("--days", type=int, default=7, help="Days of data to check")

    # Anomalies command
    anomalies = subparsers.add_parser("anomalies", help="Detect anomalous listings")
    anomalies.add_argument("--days", type=int, default=30, help="Days of data to check")

    # Stats command
    subparsers.add_parser("stats", help="Show database statistics")

    # Export command
    export = subparsers.add_parser("export", help="Export data")
    export.add_argument("--type", choices=["listings", "enriched", "specs", "fraud"],
                        default="listings", help="Data type to export")
    export.add_argument("--format", choices=["json", "csv"], default="json", help="Output format")
    export.add_argument("--output", required=True, help="Output file path")
    export.add_argument("--city", choices=[c.value for c in City], help="Filter by city")
    export.add_argument("--limit", type=int, default=10000, help="Max records to export")

    # Global options
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    parser.add_argument("--log-file", help="Log file path")

    return parser


async def main():
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args()

    # Setup logging
    setup_logging(level=args.log_level, log_file=args.log_file)

    if not args.command:
        parser.print_help()
        return 1

    # Route to command handler
    handlers = {
        "scrape": cmd_scrape,
        "enrich": cmd_enrich,
        "fraud": cmd_fraud,
        "price": cmd_price,
        "report": cmd_report,
        "deals": cmd_deals,
        "anomalies": cmd_anomalies,
        "stats": cmd_stats,
        "export": cmd_export,
    }

    handler = handlers.get(args.command)
    if not handler:
        print(f"Unknown command: {args.command}")
        return 1

    try:
        await handler(args)
        return 0
    except KeyboardInterrupt:
        logger.info("Interrupted by user")
        return 130
    except Exception as e:
        logger.exception("Command failed", error=str(e))
        return 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))