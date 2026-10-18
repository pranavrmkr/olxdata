"""
OLX scraper orchestration - coordinates browser, parsing, and storage.
"""

import asyncio
import random
from datetime import datetime
from typing import List, Optional, Dict, Any, Callable
from dataclasses import dataclass, field

from .browser import RateLimitedBrowser
from .parser import OLXListingParser, OLXSearchURLBuilder
from ..storage import Database, RawListing, City, CollectionRun
from ..utils.logging import get_logger
from ..utils.helpers import sleep_random, parse_ram_storage

logger = get_logger(__name__)


@dataclass
class ScrapingStats:
    """Statistics for a scraping session."""
    city: City
    pages_scraped: int = 0
    listings_found: int = 0
    listings_saved: int = 0
    duplicates: int = 0
    errors: int = 0
    error_details: List[str] = field(default_factory=list)
    start_time: datetime = field(default_factory=datetime.utcnow)
    end_time: Optional[datetime] = None


class OLXScraper:
    """Main OLX scraper for collecting phone listings."""

    def __init__(
        self,
        db: Database,
        max_pages_per_city: int = 10,
        max_listings_per_model: int = 3,
        min_delay: float = 3.0,
        max_delay: float = 8.0,
        headless: bool = True,
        timeout: int = 30000,
        progress_callback: Optional[Callable[[str, int, int], None]] = None,
    ):
        self.db = db
        self.max_pages_per_city = max_pages_per_city
        self.max_listings_per_model = max_listings_per_model
        self.progress_callback = progress_callback

        self.browser = RateLimitedBrowser(
            headless=headless,
            timeout=timeout,
            min_delay=min_delay,
            max_delay=max_delay,
        )

        # Track model counts per city for deduplication
        self._model_counts: Dict[str, Dict[str, int]] = {}

    async def scrape_city(self, city: City) -> ScrapingStats:
        """Scrape all phone listings for a city."""
        stats = ScrapingStats(city=city)
        logger.info("Starting scrape for city", city=city.value)

        # Initialize model tracking for this city
        city_key = city.value
        self._model_counts[city_key] = {}

        try:
            await self.browser.start()

            # Build search URLs
            search_urls = OLXSearchURLBuilder.get_all_search_urls(city, self.max_pages_per_city)
            logger.info("Generated search URLs", city=city.value, count=len(search_urls))

            page = await self.browser.new_page()

            for i, url in enumerate(search_urls):
                if stats.pages_scraped >= self.max_pages_per_city * 5:
                    break

                try:
                    if self.progress_callback:
                        self.progress_callback(city.value, i + 1, len(search_urls))

                    logger.debug("Scraping search page", url=url)
                    await self.browser.navigate_with_delay(page, url)

                    # Check for CAPTCHA or blocking
                    if await self._is_blocked(page):
                        logger.warning("Detected blocking/CAPTCHA", url=url)
                        stats.errors += 1
                        stats.error_details.append(f"Blocked on page: {url}")
                        await sleep_random(30, 60)
                        continue

                    # Get page content
                    html = await page.content()

                    # Parse listings
                    listings = OLXListingParser(city).parse_search_results(html, url)
                    stats.listings_found += len(listings)

                    if not listings:
                        logger.debug("No listings found on page", url=url)
                        continue

                    # Visit each listing detail page
                    for listing_data in listings:
                        if await self._should_skip_listing(city_key, listing_data):
                            stats.duplicates += 1
                            continue

                        try:
                            detail_listing = await self._scrape_listing_detail(page, listing_data)
                            if detail_listing:
                                saved = await self.db.save_raw_listing(detail_listing)
                                if saved:
                                    stats.listings_saved += 1
                                    self._track_model(city_key, detail_listing)
                                else:
                                    stats.duplicates += 1
                        except Exception as e:
                            logger.warning("Failed to scrape listing detail", error=str(e))
                            stats.errors += 1
                            stats.error_details.append(f"Detail scrape error: {str(e)}")

                    stats.pages_scraped += 1

                except Exception as e:
                    logger.error("Error scraping page", url=url, error=str(e))
                    stats.errors += 1
                    stats.error_details.append(f"Page error: {str(e)}")
                    continue

            await self.browser.close_page(page)

        except Exception as e:
            logger.error("Fatal error scraping city", city=city.value, error=str(e))
            stats.errors += 1
            stats.error_details.append(f"Fatal error: {str(e)}")
        finally:
            await self.browser.close()
            stats.end_time = datetime.utcnow()

        logger.info("Completed scrape for city", city=city.value, stats=stats.__dict__)
        return stats

    async def _scrape_listing_detail(self, page, listing_data: Dict[str, Any]) -> Optional[RawListing]:
        """Scrape a single listing detail page."""
        url = listing_data["url"]

        try:
            await self.browser.navigate_with_delay(page, url)

            # Check for blocking
            if await self._is_blocked(page):
                logger.warning("Blocked on detail page", url=url)
                return None

            html = await page.content()
            parser = OLXListingParser(listing_data.get("city", City.DELHI))
            return parser.parse_listing_detail(html, url)

        except Exception as e:
            logger.warning("Error scraping detail page", url=url, error=str(e))
            return None

    async def _is_blocked(self, page) -> bool:
        """Check if page shows CAPTCHA or blocking."""
        try:
            content = await page.content()
            blocking_indicators = [
                "captcha",
                "blocked",
                "access denied",
                "too many requests",
                "rate limit",
                "please verify",
                "robot check",
                "unusual traffic",
            ]
            content_lower = content.lower()
            return any(indicator in content_lower for indicator in blocking_indicators)
        except Exception:
            return False

    def _get_model_key(self, listing: RawListing) -> str:
        """Generate a model key for deduplication."""
        title_lower = listing.title.lower()

        brands = [
            "samsung", "apple", "iphone", "xiaomi", "redmi", "poco",
            "oneplus", "realme", "vivo", "oppo", "motorola", "nokia",
            "asus", "rog", "google", "pixel", "nothing", "techno",
            "infinix", "itel", "lava", "micromax", "karbonn",
        ]

        brand = "unknown"
        for b in brands:
            if b in title_lower:
                brand = b
                break

        ram_storage = parse_ram_storage(listing.title + " " + listing.description)
        ram = ram_storage.get("ram_gb")
        storage = ram_storage.get("storage_gb")

        parts = [brand]
        if ram:
            parts.append(f"{ram}gb")
        if storage:
            parts.append(f"{storage}gb")

        model_keywords = []
        for word in title_lower.split():
            if len(word) > 2 and word not in ["the", "and", "for", "with", "gb", "ram", "rom"]:
                model_keywords.append(word)

        if model_keywords:
            parts.append("_".join(model_keywords[:3]))

        return "_".join(parts).replace(" ", "_").replace("/", "_")

    def _should_skip_listing(self, city_key: str, listing_data: Dict[str, Any]) -> bool:
        """Check if we should skip this listing based on model limits."""
        temp_listing = RawListing(
            listing_id=listing_data["listing_id"],
            url=listing_data["url"],
            city=City(city_key),
            title=listing_data["title"],
            price=listing_data["price"] or 0,
            description="",
        )
        model_key = self._get_model_key(temp_listing)

        current_count = self._model_counts[city_key].get(model_key, 0)
        return current_count >= self.max_listings_per_model

    def _track_model(self, city_key: str, listing: RawListing) -> None:
        """Track model count for deduplication."""
        model_key = self._get_model_key(listing)
        self._model_counts[city_key][model_key] = self._model_counts[city_key].get(model_key, 0) + 1

    async def scrape_all_cities(self, cities: List[City]) -> Dict[City, ScrapingStats]:
        """Scrape multiple cities sequentially."""
        results = {}

        for city in cities:
            logger.info("Starting city scrape", city=city.value)
            stats = await self.scrape_city(city)
            results[city] = stats

            # Delay between cities
            await sleep_random(10, 20)

        return results


async def run_scraping_pipeline(
    db: Database,
    cities: List[City],
    config: Dict[str, Any],
    progress_callback: Optional[Callable[[str, int, int], None]] = None,
) -> CollectionRun:
    """Run the complete scraping pipeline for all cities."""
    run = CollectionRun(
        cities_scraped=cities,
        config_snapshot=config,
    )

    await db.save_collection_run(run)

    scraper = OLXScraper(
        db=db,
        max_pages_per_city=config.get("scraper", {}).get("max_pages_per_city", 10),
        max_listings_per_model=config.get("scraper", {}).get("max_listings_per_model", 3),
        min_delay=config.get("scraper", {}).get("delay_min", 3),
        max_delay=config.get("scraper", {}).get("delay_max", 8),
        headless=config.get("scraper", {}).get("headless", True),
        timeout=config.get("scraper", {}).get("timeout", 30) * 1000,
        progress_callback=progress_callback,
    )

    try:
        stats_by_city = await scraper.scrape_all_cities(cities)

        # Aggregate stats
        total_found = sum(s.listings_found for s in stats_by_city.values())
        total_saved = sum(s.listings_saved for s in stats_by_city.values())
        total_dupes = sum(s.duplicates for s in stats_by_city.values())
        total_errors = sum(s.errors for s in stats_by_city.values())
        all_errors = []
        for s in stats_by_city.values():
            all_errors.extend(s.error_details)

        run.completed_at = datetime.utcnow()
        run.status = "completed"
        run.total_listings_found = total_found
        run.total_listings_saved = total_saved
        run.total_duplicates = total_dupes
        run.total_errors = total_errors
        run.error_details = all_errors

    except Exception as e:
        logger.error("Pipeline failed", error=str(e))
        run.completed_at = datetime.utcnow()
        run.status = "failed"
        run.total_errors += 1
        run.error_details.append(f"Pipeline error: {str(e)}")

    await db.save_collection_run(run)
    return run