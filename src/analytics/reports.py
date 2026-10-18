"""
Analytics and reporting module for OLX phone data.
"""

import json
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
from collections import defaultdict
import statistics

from ..storage import (
    Database, RawListing, EnrichedListing, PhoneSpec, PriceStats,
    FraudAnalysis, City, Condition, CollectionRun
)
from ..utils.logging import get_logger

logger = get_logger(__name__)


@dataclass
class MarketOverview:
    """High-level market overview."""
    total_listings: int
    total_enriched: int
    total_phone_specs: int
    cities_covered: List[str]
    brands_covered: List[str]
    date_range: Dict[str, str]
    avg_price: float
    median_price: float
    price_range: Dict[str, int]


@dataclass
class BrandAnalysis:
    """Analysis for a specific brand."""
    brand: str
    models: int
    listings: int
    avg_price: float
    median_price: float
    price_trend: str
    popular_models: List[Dict[str, Any]]


@dataclass
class CityAnalysis:
    """Analysis for a specific city."""
    city: str
    listings: int
    avg_price: float
    median_price: float
    top_brands: List[Dict[str, Any]]
    price_vs_national_avg: float


class AnalyticsEngine:
    """Generate analytics and reports from collected data."""

    def __init__(self, db: Database):
        self.db = db

    async def generate_market_overview(self, days_back: int = 30) -> MarketOverview:
        """Generate high-level market overview."""
        listings = await self.db.get_raw_listings(days_back=days_back, limit=10000)
        enriched = await self.db.get_enriched_listings(days_back=days_back, limit=10000)
        specs = await self.db.get_all_phone_specs()

        if not listings:
            return MarketOverview(
                total_listings=0,
                total_enriched=0,
                total_phone_specs=0,
                cities_covered=[],
                brands_covered=[],
                date_range={},
                avg_price=0,
                median_price=0,
                price_range={"min": 0, "max": 0},
            )

        prices = [l.price for l in listings if l.price > 0]
        cities = list(set(l.city.value for l in listings))

        # Extract brands from enriched listings
        brands = set()
        for e in enriched:
            if e.phone_spec:
                brands.add(e.phone_spec.brand)

        date_min = min(l.listing_date for l in listings if l.listing_date)
        date_max = max(l.listing_date for l in listings if l.listing_date)

        return MarketOverview(
            total_listings=len(listings),
            total_enriched=len(enriched),
            total_phone_specs=len(specs),
            cities_covered=sorted(cities),
            brands_covered=sorted(brands),
            date_range={
                "start": date_min.isoformat() if date_min else "",
                "end": date_max.isoformat() if date_max else "",
            },
            avg_price=statistics.mean(prices) if prices else 0,
            median_price=statistics.median(prices) if prices else 0,
            price_range={
                "min": min(prices) if prices else 0,
                "max": max(prices) if prices else 0,
            },
        )

    async def analyze_by_brand(self, days_back: int = 90) -> List[BrandAnalysis]:
        """Analyze market by brand."""
        enriched = await self.db.get_enriched_listings(days_back=days_back, limit=10000)

        brand_data = defaultdict(lambda: {
            "models": set(),
            "listings": [],
            "prices": [],
        })

        for e in enriched:
            if not e.phone_spec:
                continue
            brand = e.phone_spec.brand
            brand_data[brand]["models"].add(e.phone_spec.model)
            brand_data[brand]["listings"].append(e)
            if e.raw_listing.price > 0:
                brand_data[brand]["prices"].append(e.raw_listing.price)

        results = []
        for brand, data in brand_data.items():
            if not data["prices"]:
                continue

            prices = data["prices"]

            # Find popular models
            model_counts = defaultdict(int)
            for e in data["listings"]:
                if e.phone_spec:
                    model_counts[e.phone_spec.model] += 1

            popular = sorted(
                [{"model": m, "count": c} for m, c in model_counts.items()],
                key=lambda x: x["count"],
                reverse=True
            )[:5]

            # Price trend
            trend = self._calculate_price_trend(data["listings"])

            results.append(BrandAnalysis(
                brand=brand,
                models=len(data["models"]),
                listings=len(data["listings"]),
                avg_price=statistics.mean(prices),
                median_price=statistics.median(prices),
                price_trend=trend,
                popular_models=popular,
            ))

        return sorted(results, key=lambda x: x.listings, reverse=True)

    async def analyze_by_city(self, days_back: int = 90) -> List[CityAnalysis]:
        """Analyze market by city."""
        listings = await self.db.get_raw_listings(days_back=days_back, limit=10000)
        enriched = await self.db.get_enriched_listings(days_back=days_back, limit=10000)

        # National average
        all_prices = [l.price for l in listings if l.price > 0]
        national_avg = statistics.mean(all_prices) if all_prices else 0

        city_data = defaultdict(lambda: {
            "listings": [],
            "prices": [],
            "brands": defaultdict(int),
        })

        for l in listings:
            city_data[l.city.value]["listings"].append(l)
            if l.price > 0:
                city_data[l.city.value]["prices"].append(l.price)

        for e in enriched:
            if e.phone_spec:
                city_data[e.raw_listing.city.value]["brands"][e.phone_spec.brand] += 1

        results = []
        for city, data in city_data.items():
            if not data["prices"]:
                continue

            prices = data["prices"]
            top_brands = sorted(
                [{"brand": b, "count": c} for b, c in data["brands"].items()],
                key=lambda x: x["count"],
                reverse=True
            )[:5]

            city_avg = statistics.mean(prices)
            price_vs_national = ((city_avg - national_avg) / national_avg * 100) if national_avg > 0 else 0

            results.append(CityAnalysis(
                city=city,
                listings=len(data["listings"]),
                avg_price=city_avg,
                median_price=statistics.median(prices),
                top_brands=top_brands,
                price_vs_national_avg=round(price_vs_national, 1),
            ))

        return sorted(results, key=lambda x: x.listings, reverse=True)

    async def analyze_price_segments(
        self,
        brand: Optional[str] = None,
        city: Optional[City] = None,
        days_back: int = 90,
    ) -> Dict[str, Any]:
        """Analyze price segments (budget, mid-range, premium)."""
        listings = await self.db.get_raw_listings(
            city=city, days_back=days_back, limit=10000
        )

        if brand:
            enriched = await self.db.get_enriched_listings(days_back=days_back, limit=10000)
            brand_listings = set(e.raw_listing.listing_id for e in enriched
                               if e.phone_spec and e.phone_spec.brand.lower() == brand.lower())
            listings = [l for l in listings if l.listing_id in brand_listings]

        prices = [l.price for l in listings if l.price > 0]
        if not prices:
            return {}

        # Define segments
        p33 = statistics.quantiles(prices, n=3)[0] if len(prices) >= 3 else prices[0]
        p66 = statistics.quantiles(prices, n=3)[1] if len(prices) >= 3 else prices[-1]

        segments = {
            "budget": {"max_price": p33, "listings": []},
            "mid_range": {"min_price": p33, "max_price": p66, "listings": []},
            "premium": {"min_price": p66, "listings": []},
        }

        for l in listings:
            if l.price <= p33:
                segments["budget"]["listings"].append(l)
            elif l.price <= p66:
                segments["mid_range"]["listings"].append(l)
            else:
                segments["premium"]["listings"].append(l)

        result = {}
        for seg_name, seg_data in segments.items():
            seg_prices = [l.price for l in seg_data["listings"]]
            if seg_prices:
                result[seg_name] = {
                    "count": len(seg_prices),
                    "avg_price": round(statistics.mean(seg_prices)),
                    "median_price": round(statistics.median(seg_prices)),
                    "price_range": {
                        "min": min(seg_prices),
                        "max": max(seg_prices),
                    },
                    "percentage": round(len(seg_prices) / len(prices) * 100, 1),
                }
            else:
                result[seg_name] = {"count": 0}

        return result

    async def find_deals(
        self,
        max_price_vs_market: float = 0.8,
        min_confidence: float = 0.6,
        city: Optional[City] = None,
        days_back: int = 7,
    ) -> List[Dict[str, Any]]:
        """Find potentially good deals (underpriced listings)."""
        enriched = await self.db.get_enriched_listings(
            city=city, days_back=days_back, limit=5000
        )

        deals = []
        for e in enriched:
            if e.match_confidence < min_confidence:
                continue
            if not e.phone_spec:
                continue
            if e.price_vs_msrp_pct is None:
                continue

            if e.price_vs_msrp_pct < max_price_vs_market * 100:
                deals.append({
                    "listing_id": e.raw_listing.listing_id,
                    "title": e.raw_listing.title,
                    "price": e.raw_listing.price,
                    "city": e.raw_listing.city.value,
                    "brand": e.phone_spec.brand,
                    "model": e.phone_spec.model,
                    "variant": e.phone_spec.variant,
                    "condition": e.raw_listing.condition.value,
                    "price_vs_msrp_pct": e.price_vs_msrp_pct,
                    "depreciation_pct": e.depreciation_pct,
                    "age_years": e.age_years,
                    "match_confidence": e.match_confidence,
                    "url": e.raw_listing.url,
                    "listing_date": e.raw_listing.listing_date.isoformat() if e.raw_listing.listing_date else None,
                })

        deals.sort(key=lambda x: x["price_vs_msrp_pct"])
        return deals[:50]

    async def detect_anomalies(self, days_back: int = 30) -> List[Dict[str, Any]]:
        """Detect anomalous listings (potential fraud or data issues)."""
        enriched = await self.db.get_enriched_listings(days_back=days_back, limit=10000)
        fraud_analyses = await self.db.get_fraud_analyses(days_back=days_back, limit=10000)

        anomalies = []

        # High fraud risk
        high_risk = [f for f in fraud_analyses if f.risk_level.value in ("high", "critical")]
        for f in high_risk:
            listing = next((e for e in enriched if e.raw_listing.listing_id == f.listing_id), None)
            if listing:
                anomalies.append({
                    "type": "fraud_risk",
                    "severity": f.risk_level.value,
                    "listing_id": f.listing_id,
                    "title": listing.raw_listing.title,
                    "price": listing.raw_listing.price,
                    "flags": [flag.value for flag in f.flags],
                    "risk_score": f.risk_score,
                    "evidence": f.evidence,
                })

        # Price outliers (using IQR method)
        prices = [e.raw_listing.price for e in enriched if e.raw_listing.price > 0]
        if len(prices) >= 10:
            q1 = statistics.quantiles(prices, n=4)[0]
            q3 = statistics.quantiles(prices, n=4)[2]
            iqr = q3 - q1
            lower_bound = q1 - 1.5 * iqr
            upper_bound = q3 + 1.5 * iqr

            for e in enriched:
                price = e.raw_listing.price
                if price < lower_bound or price > upper_bound:
                    anomalies.append({
                        "type": "price_outlier",
                        "severity": "medium" if price < lower_bound else "high",
                        "listing_id": e.raw_listing.listing_id,
                        "title": e.raw_listing.title,
                        "price": price,
                        "bound": "lower" if price < lower_bound else "upper",
                        "threshold": round(lower_bound if price < lower_bound else upper_bound),
                    })

        # Spec mismatches
        for e in enriched:
            if e.match_confidence < 0.4 and e.phone_spec:
                anomalies.append({
                    "type": "spec_mismatch",
                    "severity": "medium",
                    "listing_id": e.raw_listing.listing_id,
                    "title": e.raw_listing.title,
                    "match_confidence": e.match_confidence,
                    "matched_spec": f"{e.phone_spec.brand} {e.phone_spec.model}",
                })

        return anomalies

    def _calculate_price_trend(self, listings: List[EnrichedListing]) -> str:
        """Calculate price trend from listings."""
        if len(listings) < 5:
            return "insufficient_data"

        # Group by month
        monthly = defaultdict(list)
        for e in listings:
            if e.raw_listing.listing_date and e.raw_listing.price > 0:
                month = e.raw_listing.listing_date.strftime("%Y-%m")
                monthly[month].append(e.raw_listing.price)

        if len(monthly) < 2:
            return "insufficient_data"

        medians = []
        for month in sorted(monthly.keys()):
            prices = monthly[month]
            if len(prices) >= 3:
                medians.append(statistics.median(prices))

        if len(medians) < 2:
            return "insufficient_data"

        first = medians[0]
        last = medians[-1]
        change = ((last - first) / first) * 100

        if change > 5:
            return "increasing"
        elif change < -5:
            return "decreasing"
        return "stable"

    async def export_to_json(self, filepath: str, days_back: int = 30) -> None:
        """Export analytics to JSON file."""
        overview = await self.generate_market_overview(days_back)
        brands = await self.analyze_by_brand(days_back)
        cities = await self.analyze_by_city(days_back)
        segments = await self.analyze_price_segments(days_back=days_back)
        deals = await self.find_deals(days_back=days_back)
        anomalies = await self.detect_anomalies(days_back)

        data = {
            "generated_at": datetime.utcnow().isoformat(),
            "period_days": days_back,
            "market_overview": asdict(overview),
            "brand_analysis": [asdict(b) for b in brands],
            "city_analysis": [asdict(c) for c in cities],
            "price_segments": segments,
            "top_deals": deals,
            "anomalies": anomalies,
        }

        with open(filepath, "w") as f:
            json.dump(data, f, indent=2, default=str)

        logger.info("Analytics exported", filepath=filepath)


async def generate_full_report(db: Database, output_dir: str, days_back: int = 30) -> Dict[str, Any]:
    """Generate complete analytics report."""
    import os
    os.makedirs(output_dir, exist_ok=True)

    engine = AnalyticsEngine(db)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    filepath = os.path.join(output_dir, f"market_report_{timestamp}.json")

    await engine.export_to_json(filepath, days_back)

    overview = await engine.generate_market_overview(days_back)

    return {
        "report_path": filepath,
        "summary": {
            "total_listings": overview.total_listings,
            "total_enriched": overview.total_enriched,
            "brands": len(overview.brands_covered),
            "cities": len(overview.cities_covered),
        },
    }