"""
Pricing engine - calculates fair market values and price statistics.
"""

import statistics
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from collections import defaultdict

from ..storage import (
    Database, EnrichedListing, PhoneSpec, PriceStats, City, Condition
)
from ..utils.logging import get_logger
from ..utils.helpers import calculate_price_vs_msrp, calculate_depreciation

logger = get_logger(__name__)


@dataclass
class PricePoint:
    """A single price observation."""
    price: int
    condition: Condition
    city: City
    listing_date: datetime
    ram_gb: Optional[int]
    storage_gb: Optional[int]
    source_listing_id: str


class PricingEngine:
    """Calculate fair market prices and statistics."""

    def __init__(self, db: Database):
        self.db = db

    async def calculate_price_stats(
        self,
        phone_spec_id: str,
        city: Optional[City] = None,
        condition: Optional[Condition] = None,
        ram_gb: Optional[int] = None,
        storage_gb: Optional[int] = None,
        days_back: int = 90,
        min_samples: int = 3,
    ) -> Optional[PriceStats]:
        """Calculate price statistics for a phone model."""
        # Get enriched listings matching criteria
        listings = await self.db.get_enriched_listings(
            phone_spec_id=phone_spec_id,
            city=city,
            condition=condition,
            ram_gb=ram_gb,
            storage_gb=storage_gb,
            days_back=days_back,
        )

        if len(listings) < min_samples:
            logger.debug("Insufficient samples for price stats",
                        phone_spec_id=phone_spec_id, count=len(listings))
            return None

        # Extract price points
        price_points = self._extract_price_points(listings)

        # Group by condition for condition-specific stats
        by_condition = defaultdict(list)
        for pp in price_points:
            by_condition[pp.condition].append(pp.price)

        # Calculate overall stats
        all_prices = [pp.price for pp in price_points]
        stats = self._calculate_statistics(all_prices)

        # Calculate condition-specific stats
        condition_stats = {}
        for cond, prices in by_condition.items():
            if len(prices) >= min_samples:
                condition_stats[cond.value] = self._calculate_statistics(prices)

        # Calculate depreciation curve if we have age data
        depreciation_curve = self._calculate_depreciation_curve(listings)

        # Determine confidence based on sample size and variance
        confidence = self._calculate_confidence(len(all_prices), stats["cv"])

        price_stats = PriceStats(
            phone_spec_id=phone_spec_id,
            city=city,
            condition=condition,
            ram_gb=ram_gb,
            storage_gb=storage_gb,
            sample_size=len(all_prices),
            min_price=stats["min"],
            max_price=stats["max"],
            mean_price=stats["mean"],
            median_price=stats["median"],
            std_dev=stats["std"],
            percentile_25=stats["p25"],
            percentile_75=stats["p75"],
            condition_breakdown=condition_stats,
            depreciation_curve=depreciation_curve,
            confidence=confidence,
            calculated_at=datetime.utcnow(),
        )

        await self.db.save_price_stats(price_stats)
        return price_stats

    def _extract_price_points(self, listings: List[EnrichedListing]) -> List[PricePoint]:
        """Extract price points from enriched listings."""
        points = []
        for enriched in listings:
            raw = enriched.raw_listing
            spec = enriched.phone_spec

            ram = spec.ram_gb if spec else None
            storage = spec.storage_gb if spec else None

            points.append(PricePoint(
                price=raw.price,
                condition=raw.condition,
                city=raw.city,
                listing_date=raw.listing_date or datetime.utcnow(),
                ram_gb=ram,
                storage_gb=storage,
                source_listing_id=raw.listing_id,
            ))
        return points

    def _calculate_statistics(self, prices: List[int]) -> Dict[str, Any]:
        """Calculate comprehensive price statistics."""
        if not prices:
            return {}

        sorted_prices = sorted(prices)
        n = len(sorted_prices)

        mean = statistics.mean(prices)
        median = statistics.median(prices)

        try:
            std = statistics.stdev(prices) if n > 1 else 0
        except statistics.StatisticsError:
            std = 0

        cv = (std / mean * 100) if mean > 0 else 0

        # Percentiles
        p25_idx = int(n * 0.25)
        p75_idx = int(n * 0.75)

        return {
            "min": min(prices),
            "max": max(prices),
            "mean": round(mean),
            "median": round(median),
            "std": round(std),
            "cv": round(cv, 2),
            "p25": sorted_prices[p25_idx],
            "p75": sorted_prices[p75_idx],
        }

    def _calculate_depreciation_curve(self, listings: List[EnrichedListing]) -> List[Dict[str, Any]]:
        """Calculate depreciation curve from listings with age data."""
        age_price_pairs = []

        for enriched in listings:
            if enriched.age_years is not None and enriched.raw_listing.price > 0:
                age_price_pairs.append({
                    "age_years": enriched.age_years,
                    "price": enriched.raw_listing.price,
                    "condition": enriched.raw_listing.condition.value,
                })

        if len(age_price_pairs) < 3:
            return []

        # Group by age buckets
        age_buckets = defaultdict(list)
        for pair in age_price_pairs:
            bucket = round(pair["age_years"] * 2) / 2  # 0.5 year buckets
            age_buckets[bucket].append(pair["price"])

        curve = []
        for age, prices in sorted(age_buckets.items()):
            if len(prices) >= 2:
                curve.append({
                    "age_years": age,
                    "median_price": statistics.median(prices),
                    "mean_price": statistics.mean(prices),
                    "sample_size": len(prices),
                })

        return curve

    def _calculate_confidence(self, sample_size: int, cv: float) -> float:
        """Calculate confidence score for price stats."""
        # Base confidence from sample size
        size_confidence = min(1.0, sample_size / 30)  # Full confidence at 30+ samples

        # Reduce confidence for high variance
        variance_penalty = min(0.5, cv / 100)  # 50% max penalty at CV=100

        confidence = size_confidence * (1 - variance_penalty)
        return round(max(0.1, confidence), 2)

    async def calculate_fair_price(
        self,
        phone_spec_id: str,
        condition: Condition,
        city: Optional[City] = None,
        ram_gb: Optional[int] = None,
        storage_gb: Optional[int] = None,
    ) -> Optional[Dict[str, Any]]:
        """Calculate fair price range for a specific phone configuration."""
        stats = await self.calculate_price_stats(
            phone_spec_id=phone_spec_id,
            city=city,
            condition=condition,
            ram_gb=ram_gb,
            storage_gb=storage_gb,
        )

        if not stats:
            return None

        # Use condition-specific stats if available
        if condition and condition.value in stats.condition_breakdown:
            cond_stats = stats.condition_breakdown[condition.value]
            median = cond_stats["median"]
            p25 = cond_stats["p25"]
            p75 = cond_stats["p75"]
        else:
            median = stats.median_price
            p25 = stats.percentile_25
            p75 = stats.percentile_75

        return {
            "fair_price": median,
            "price_range": (p25, p75),
            "min_price": stats.min_price,
            "max_price": stats.max_price,
            "confidence": stats.confidence,
            "sample_size": stats.sample_size,
        }

    async def analyze_price_trends(
        self,
        phone_spec_id: str,
        city: Optional[City] = None,
        months: int = 6,
    ) -> Dict[str, Any]:
        """Analyze price trends over time."""
        listings = await self.db.get_enriched_listings(
            phone_spec_id=phone_spec_id,
            city=city,
            days_back=months * 30,
        )

        if len(listings) < 10:
            return {"trend": "insufficient_data"}

        # Group by month
        monthly = defaultdict(list)
        for enriched in listings:
            if enriched.raw_listing.listing_date:
                month_key = enriched.raw_listing.listing_date.strftime("%Y-%m")
                monthly[month_key].append(enriched.raw_listing.price)

        # Calculate monthly medians
        trend_data = []
        for month, prices in sorted(monthly.items()):
            if len(prices) >= 3:
                trend_data.append({
                    "month": month,
                    "median_price": statistics.median(prices),
                    "mean_price": statistics.mean(prices),
                    "count": len(prices),
                })

        if len(trend_data) < 2:
            return {"trend": "insufficient_data"}

        # Calculate trend direction
        first_median = trend_data[0]["median_price"]
        last_median = trend_data[-1]["median_price"]
        change_pct = ((last_median - first_median) / first_median) * 100

        if change_pct > 5:
            trend = "increasing"
        elif change_pct < -5:
            trend = "decreasing"
        else:
            trend = "stable"

        return {
            "trend": trend,
            "change_pct": round(change_pct, 1),
            "monthly_data": trend_data,
        }

    async def compare_cities(
        self,
        phone_spec_id: str,
        condition: Condition,
        ram_gb: Optional[int] = None,
        storage_gb: Optional[int] = None,
    ) -> Dict[City, Dict[str, Any]]:
        """Compare prices across cities."""
        from ..storage import City

        results = {}
        for city in City:
            fair_price = await self.calculate_fair_price(
                phone_spec_id=phone_spec_id,
                condition=condition,
                city=city,
                ram_gb=ram_gb,
                storage_gb=storage_gb,
            )
            if fair_price:
                results[city] = fair_price

        return results


async def run_pricing_analysis(
    db: Database,
    phone_spec_ids: List[str],
    cities: Optional[List[City]] = None,
) -> List[PriceStats]:
    """Run pricing analysis for multiple phone models."""
    engine = PricingEngine(db)
    results = []

    for spec_id in phone_spec_ids:
        for city in (cities or [None]):
            for condition in Condition:
                stats = await engine.calculate_price_stats(
                    phone_spec_id=spec_id,
                    city=city,
                    condition=condition,
                )
                if stats:
                    results.append(stats)

    return results