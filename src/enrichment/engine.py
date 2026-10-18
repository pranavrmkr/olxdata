"""
Enrichment engine - matches listings to phone specs and calculates metrics.
"""

import re
from datetime import datetime
from typing import Optional, List, Dict, Any, Tuple
from difflib import SequenceMatcher
from dataclasses import dataclass

from ..storage import Database, RawListing, PhoneSpec, EnrichedListing, City, Condition
from ..utils.logging import get_logger
from ..utils.helpers import (
    parse_ram_storage, calculate_age_years, calculate_depreciation,
    calculate_price_vs_msrp, slugify
)
from .sources.gsmarena import search_and_get_specs as gsmarena_search

logger = get_logger(__name__)


@dataclass
class MatchResult:
    """Result of phone spec matching."""
    phone_spec: PhoneSpec
    confidence: float
    method: str
    matched_fields: Dict[str, Any]


class PhoneSpecMatcher:
    """Match OLX listings to phone specifications."""

    def __init__(self, db: Database):
        self.db = db
        self._brand_aliases = self._load_brand_aliases()

    def _load_brand_aliases(self) -> Dict[str, List[str]]:
        return {
            "samsung": ["samsung", "sammy"],
            "apple": ["apple", "iphone", "ios"],
            "xiaomi": ["xiaomi", "mi", "redmi", "poco"],
            "oneplus": ["oneplus", "1+", "one plus"],
            "realme": ["realme", "real me"],
            "vivo": ["vivo"],
            "oppo": ["oppo"],
            "motorola": ["motorola", "moto", "lenovo"],
            "nokia": ["nokia", "hmd"],
            "asus": ["asus", "rog", "republic of gamers"],
            "google": ["google", "pixel", "nexus"],
            "nothing": ["nothing"],
            "techno": ["techno", "tecno"],
            "infinix": ["infinix"],
            "itel": ["itel"],
            "lava": ["lava"],
            "micromax": ["micromax"],
            "karbonn": ["karbonn"],
        }

    def normalize_brand(self, brand: str) -> str:
        brand_lower = brand.lower().strip()
        for canonical, aliases in self._brand_aliases.items():
            if brand_lower in aliases:
                return canonical
        return brand_lower

    def extract_brand_model(self, title: str, description: str = "") -> Tuple[Optional[str], Optional[str], Optional[str]]:
        text = f"{title} {description}".lower()

        brand = None
        for canonical, aliases in self._brand_aliases.items():
            for alias in aliases:
                if alias in text:
                    brand = canonical
                    break
            if brand:
                break

        if not brand:
            return None, None, None

        remaining = text
        for alias in self._brand_aliases.get(brand, []):
            remaining = remaining.replace(alias, " ")

        model = None
        variant = None

        model_patterns = [
            rf'{re.escape(brand)}\s+([a-z0-9\s\-\+]+?)(?:\s+\d+/\d+|\s+\d+gb|\s*$)',
            rf'{re.escape(brand)}\s+([a-z][a-z0-9\s\-\+]*?)(?:\s+\d+/\d+|\s+\d+gb|\s*$)',
        ]

        for pattern in model_patterns:
            match = re.search(pattern, text)
            if match:
                candidate = match.group(1).strip()
                stop_words = {"new", "used", "old", "good", "condition", "price", "negotiable", "selling", "sale"}
                words = [w for w in candidate.split() if w not in stop_words]
                if words:
                    model = " ".join(words[:5])
                    break

        variant_keywords = ["ultra", "pro", "max", "plus", "lite", "mini", "fe", "ne", "5g", "4g", "dual sim", "single sim"]
        for kw in variant_keywords:
            if kw in remaining and kw not in (model or ""):
                variant = kw
                break

        return brand, model, variant

    async def find_or_fetch_spec(
        self,
        brand: str,
        model: str,
        variant: Optional[str] = None,
        ram_gb: Optional[int] = None,
        storage_gb: Optional[int] = None,
    ) -> Optional[PhoneSpec]:
        brand = self.normalize_brand(brand)

        existing = await self.db.find_phone_spec(brand, model, variant, ram_gb, storage_gb)
        if existing:
            logger.info("Found spec in database", brand=brand, model=model)
            return existing

        logger.info("Fetching spec from GSMArena", brand=brand, model=model)
        spec_data = await gsmarena_search(brand, model, variant, ram_gb, storage_gb)

        if spec_data:
            return self._create_phone_spec(spec_data, brand, model, variant, ram_gb, storage_gb)

        return None

    def _create_phone_spec(
        self,
        data: Dict[str, Any],
        brand: str,
        model: str,
        variant: Optional[str] = None,
        ram_gb: Optional[int] = None,
        storage_gb: Optional[int] = None,
    ) -> PhoneSpec:
        import uuid

        ram = data.get("ram_gb") or ram_gb
        storage = data.get("storage_gb") or storage_gb

        return PhoneSpec(
            id=str(uuid.uuid4()),
            brand=brand.title(),
            model=model.title(),
            variant=variant,
            ram_gb=ram or 0,
            storage_gb=storage or 0,
            virtual_ram_gb=data.get("virtual_ram_gb"),
            expandable_storage=data.get("expandable_storage", False),
            launch_year=data.get("launch_year") or datetime.now().year,
            launch_date=data.get("launch_date"),
            original_msrp_inr=data.get("original_msrp_inr"),
            original_msrp_usd=data.get("original_msrp_usd"),
            display_size_inches=data.get("display_size_inches"),
            display_type=data.get("display_type"),
            processor=data.get("processor"),
            battery_mah=data.get("battery_mah"),
            rear_camera_mp=data.get("rear_camera_mp"),
            front_camera_mp=data.get("front_camera_mp"),
            os_at_launch=data.get("os_at_launch"),
            weight_grams=data.get("weight_grams"),
            dimensions_mm=data.get("dimensions_mm"),
            colors=data.get("colors", []),
            network_technologies=data.get("network_technologies", []),
            source_urls=[data.get("source_url")] if data.get("source_url") else [],
            source_retrieved_at=datetime.utcnow(),
            confidence=0.8,
            notes=f"Auto-fetched from GSMArena for {brand} {model}",
        )

    def calculate_match_score(
        self,
        listing: RawListing,
        spec: PhoneSpec,
    ) -> Tuple[float, Dict[str, Any]]:
        score = 0.0
        matched = {}
        max_score = 0.0

        listing_text = f"{listing.title} {listing.description}".lower()
        spec_text = f"{spec.brand} {spec.model} {spec.variant or ''}".lower()

        max_score += 30
        if self.normalize_brand(spec.brand) in listing_text:
            score += 30
            matched["brand"] = True

        max_score += 30
        model_words = spec.model.lower().split()
        model_matches = sum(1 for w in model_words if len(w) > 2 and w in listing_text)
        if model_words:
            model_ratio = model_matches / len(model_words)
            score += 30 * model_ratio
            matched["model_ratio"] = model_ratio

        max_score += 10
        if spec.variant and spec.variant.lower() in listing_text:
            score += 10
            matched["variant"] = True

        max_score += 15
        listing_ram = parse_ram_storage(listing_text).get("ram_gb")
        if listing_ram and spec.ram_gb and listing_ram == spec.ram_gb:
            score += 15
            matched["ram"] = True
        elif listing_ram and spec.ram_gb:
            diff = abs(listing_ram - spec.ram_gb)
            if diff <= 2:
                score += 10
                matched["ram_close"] = True

        max_score += 15
        listing_storage = parse_ram_storage(listing_text).get("storage_gb")
        if listing_storage and spec.storage_gb and listing_storage == spec.storage_gb:
            score += 15
            matched["storage"] = True
        elif listing_storage and spec.storage_gb:
            diff = abs(listing_storage - spec.storage_gb)
            if diff <= 32:
                score += 10
                matched["storage_close"] = True

        confidence = score / max_score if max_score > 0 else 0.0

        return confidence, matched


class EnrichmentEngine:
    """Main enrichment pipeline."""

    def __init__(self, db: Database):
        self.db = db
        self.matcher = PhoneSpecMatcher(db)

    async def enrich_listing(self, raw_listing: RawListing) -> EnrichedListing:
        brand, model, variant = self.matcher.extract_brand_model(
            raw_listing.title, raw_listing.description
        )

        phone_spec = None
        match_confidence = 0.0
        match_method = "none"
        matched_fields = {}

        if brand and model:
            ram_storage = parse_ram_storage(raw_listing.title + " " + raw_listing.description)
            ram_gb = ram_storage.get("ram_gb")
            storage_gb = ram_storage.get("storage_gb")

            phone_spec = await self.matcher.find_or_fetch_spec(
                brand, model, variant, ram_gb, storage_gb
            )

            if phone_spec:
                await self.db.save_phone_spec(phone_spec)

                match_confidence, matched_fields = self.matcher.calculate_match_score(
                    raw_listing, phone_spec
                )
                match_method = "spec_match"
            else:
                match_method = "no_spec_found"
        else:
            match_method = "no_brand_model"

        age_years = None
        price_vs_msrp_pct = None
        depreciation_pct = None

        if phone_spec and phone_spec.launch_year:
            age_years = calculate_age_years(phone_spec.launch_year)

            if phone_spec.original_msrp_inr and raw_listing.price > 0:
                price_vs_msrp_pct = calculate_price_vs_msrp(raw_listing.price, phone_spec.original_msrp_inr)
                depreciation_pct = calculate_depreciation(raw_listing.price, phone_spec.original_msrp_inr)

        enriched = EnrichedListing(
            raw_listing=raw_listing,
            phone_spec=phone_spec,
            match_confidence=match_confidence,
            match_method=match_method,
            age_years=age_years,
            price_vs_msrp_pct=price_vs_msrp_pct,
            depreciation_pct=depreciation_pct,
        )

        await self.db.save_enriched_listing(enriched)

        return enriched

    async def enrich_all_listings(
        self,
        city: Optional[City] = None,
        limit: int = 1000,
        min_confidence: float = 0.5,
    ) -> List[EnrichedListing]:
        raw_listings = await self.db.get_raw_listings(city=city, limit=limit)
        enriched_listings = []

        for raw in raw_listings:
            try:
                enriched = await self.enrich_listing(raw)
                if enriched.match_confidence >= min_confidence or enriched.phone_spec:
                    enriched_listings.append(enriched)
            except Exception as e:
                logger.warning("Failed to enrich listing", listing_id=raw.listing_id, error=str(e))

        return enriched_listings