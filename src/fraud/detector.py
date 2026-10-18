"""
Fraud detection engine for OLX phone listings.
"""

import re
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, field

from ..storage import (
    RawListing, EnrichedListing, FraudAnalysis, FraudFlag, RiskLevel
)

# Define flag types as constants
class FlagType:
    PRICE_TOO_LOW = "price_too_low"
    PRICE_TOO_HIGH = "price_too_high"
    PRICE_ROUND_NUMBER = "price_round_number"
    DESCRIPTION_TOO_SHORT = "description_too_short"
    DESCRIPTION_GENERIC = "description_generic"
    DESCRIPTION_MISMATCH = "description_mismatch"
    IMAGES_STOCK_PHOTOS = "images_stock_photos"
    IMAGES_TOO_FEW = "images_too_few"
    IMAGES_MISMATCH = "images_mismatch"
    SELLER_NO_RATING = "seller_no_rating"
    SELLER_NEW_ACCOUNT = "seller_new_account"
    SELLER_MULTIPLE_LISTINGS = "seller_multiple_listings"
    CONTACT_WHATSAPP_ONLY = "contact_whatsapp_only"
    CONTACT_ADVANCE_PAYMENT = "contact_advance_payment"
    CONTACT_URGENT_SALE = "contact_urgent_sale"
    SPECS_MISMATCH = "specs_mismatch"
    LOCATION_MISMATCH = "location_mismatch"
    LISTING_TOO_GOOD_TO_BE_TRUE = "listing_too_good_to_be_true"
    URGENCY_LANGUAGE = "urgency_language"
from ..utils.logging import get_logger
from ..utils.helpers import parse_ram_storage, calculate_price_vs_msrp, calculate_depreciation

logger = get_logger(__name__)


@dataclass
class FraudRule:
    """A single fraud detection rule."""
    flag: FraudFlag
    weight: float
    condition: callable
    description: str


class FraudDetector:
    """Detects potentially fraudulent listings."""

    def __init__(self):
        self.rules = self._build_rules()

    def _build_rules(self) -> List[FraudRule]:
        """Build the fraud detection rules."""
        return [
            # Price-based rules
            FraudRule(
                flag=FlagType.PRICE_TOO_LOW,
                weight=0.9,
                condition=lambda ctx: self._check_price_too_low(ctx),
                description="Price significantly below market value"
            ),
            FraudRule(
                flag=FlagType.PRICE_TOO_HIGH,
                weight=0.5,
                condition=lambda ctx: self._check_price_too_high(ctx),
                description="Price significantly above market value"
            ),
            FraudRule(
                flag=FlagType.PRICE_ROUND_NUMBER,
                weight=0.2,
                condition=lambda ctx: self._check_round_price(ctx),
                description="Price is a round number (e.g., 10000, 15000)"
            ),

            # Description-based rules
            FraudRule(
                flag=FlagType.DESCRIPTION_TOO_SHORT,
                weight=0.4,
                condition=lambda ctx: self._check_short_description(ctx),
                description="Description is very short or missing"
            ),
            FraudRule(
                flag=FlagType.DESCRIPTION_GENERIC,
                weight=0.3,
                condition=lambda ctx: self._check_generic_description(ctx),
                description="Description contains generic/template text"
            ),
            FraudRule(
                flag=FlagType.DESCRIPTION_MISMATCH,
                weight=0.6,
                condition=lambda ctx: self._check_description_mismatch(ctx),
                description="Description doesn't match title/specs"
            ),

            # Image-based rules
            FraudRule(
                flag=FlagType.IMAGES_STOCK_PHOTOS,
                weight=0.7,
                condition=lambda ctx: self._check_stock_images(ctx),
                description="Images appear to be stock/official photos"
            ),
            FraudRule(
                flag=FlagType.IMAGES_TOO_FEW,
                weight=0.3,
                condition=lambda ctx: self._check_few_images(ctx),
                description="Very few or no images"
            ),
            FraudRule(
                flag=FlagType.IMAGES_MISMATCH,
                weight=0.5,
                condition=lambda ctx: self._check_image_mismatch(ctx),
                description="Images don't match described phone"
            ),

            # Seller-based rules
            FraudRule(
                flag=FlagType.SELLER_NEW_ACCOUNT,
                weight=0.4,
                condition=lambda ctx: self._check_new_seller(ctx),
                description="Seller account appears new"
            ),
            FraudRule(
                flag=FlagType.SELLER_MULTIPLE_LISTINGS,
                weight=0.3,
                condition=lambda ctx: self._check_multiple_listings(ctx),
                description="Seller has many similar listings"
            ),
            FraudRule(
                flag=FlagType.SELLER_NO_RATING,
                weight=0.4,
                condition=lambda ctx: self._check_low_rating(ctx),
                description="Seller has low rating"
            ),

            # Contact-based rules
            FraudRule(
                flag=FlagType.CONTACT_WHATSAPP_ONLY,
                weight=0.6,
                condition=lambda ctx: self._check_contact_in_description(ctx),
                description="Phone/email in description (bypass platform)"
            ),
            FraudRule(
                flag=FlagType.CONTACT_ADVANCE_PAYMENT,
                weight=0.8,
                condition=lambda ctx: self._check_external_contact(ctx),
                description="Asks to contact outside platform"
            ),

            # Spec mismatch rules
            FraudRule(
                flag=FlagType.SPECS_MISMATCH,
                weight=0.7,
                condition=lambda ctx: self._check_spec_mismatch(ctx),
                description="Listed specs don't match known phone specs"
            ),
            FraudRule(
                flag=FlagType.LISTING_TOO_GOOD_TO_BE_TRUE,
                weight=0.9,
                condition=lambda ctx: self._check_impossible_specs(ctx),
                description="Impossible specification combination"
            ),

            # Location/urgency rules
            FraudRule(
                flag=FlagType.LOCATION_MISMATCH,
                weight=0.4,
                condition=lambda ctx: self._check_location_mismatch(ctx),
                description="Location inconsistent with listing"
            ),
            FraudRule(
                flag=FlagType.URGENCY_LANGUAGE,
                weight=0.3,
                condition=lambda ctx: self._check_urgency(ctx),
                description="Uses urgency pressure tactics"
            ),
        ]

    def analyze(self, enriched: EnrichedListing) -> FraudAnalysis:
        """Run all fraud checks on an enriched listing."""
        flags = []
        evidence = {}

        # Build context for rules
        ctx = self._build_context(enriched)

        for rule in self.rules:
            try:
                if rule.condition(ctx):
                    # Create FraudFlag object from flag type string
                    flag_obj = FraudFlag(
                        flag_type=rule.flag,
                        severity=self._flag_to_severity(rule.flag),
                        description=rule.description,
                        evidence={},
                        confidence=1.0
                    )
                    flags.append(flag_obj)
                    evidence[rule.flag] = rule.description
            except Exception as e:
                logger.warning("Rule evaluation failed", flag=rule.flag, error=str(e))

        # Calculate risk score
        risk_score = self._calculate_risk_score(flags)
        risk_level = self._score_to_level(risk_score)

        # Check if manual review needed
        requires_review = risk_level in (RiskLevel.HIGH, RiskLevel.CRITICAL)

        return FraudAnalysis(
            listing_id=enriched.raw_listing.listing_id,
            flags=flags,
            risk_score=risk_score,
            risk_level=risk_level,
            evidence=evidence,
            requires_manual_review=requires_review,
            analyzed_at=datetime.utcnow(),
        )

    def _build_context(self, enriched: EnrichedListing) -> Dict[str, Any]:
        """Build context dict for rule evaluation."""
        raw = enriched.raw_listing
        spec = enriched.phone_spec

        # Parse listing details
        ram_storage = parse_ram_storage(raw.title + " " + raw.description)

        return {
            "raw": raw,
            "enriched": enriched,
            "spec": spec,
            "title": raw.title.lower(),
            "description": raw.description.lower(),
            "price": raw.price,
            "ram_gb": ram_storage.get("ram_gb"),
            "storage_gb": ram_storage.get("storage_gb"),
            "condition": raw.condition.value,
            "seller_name": raw.seller_name,
            "seller_type": raw.seller_type,
            "seller_rating": raw.seller_rating,
            "images": raw.images,
            "listing_date": raw.listing_date,
            "price_vs_msrp": enriched.price_vs_msrp_pct,
            "depreciation": enriched.depreciation_pct,
            "age_years": enriched.age_years,
            "match_confidence": enriched.match_confidence,
        }

    def _calculate_risk_score(self, flags: List[FraudFlag]) -> float:
        """Calculate overall risk score from flags."""
        if not flags:
            return 0.0

        # Get rule weights for triggered flags
        flag_weights = {}
        for rule in self.rules:
            flag_weights[rule.flag] = rule.weight

        # Sum weights with diminishing returns
        total_weight = sum(flag_weights.get(flag, 0.5) for flag in flags)
        # Normalize to 0-1 with diminishing returns
        score = min(1.0, total_weight * 0.85)

        return round(score, 3)

    def _score_to_level(self, score: float) -> RiskLevel:
        """Convert risk score to risk level."""
        if score >= 0.7:
            return RiskLevel.HIGH
        elif score >= 0.4:
            return RiskLevel.MEDIUM
        elif score > 0.0:
            return RiskLevel.LOW
        return RiskLevel.LOW

    def _flag_to_severity(self, flag_type: str) -> RiskLevel:
        """Map flag type to severity level."""
        high_severity = {
            FlagType.PRICE_TOO_LOW,
            FlagType.DESCRIPTION_MISMATCH,
            FlagType.IMAGES_STOCK_PHOTOS,
            FlagType.SELLER_MULTIPLE_LISTINGS,
            FlagType.CONTACT_ADVANCE_PAYMENT,
            FlagType.SPECS_MISMATCH,
            FlagType.LOCATION_MISMATCH,
            FlagType.LISTING_TOO_GOOD_TO_BE_TRUE,
        }
        medium_severity = {
            FlagType.PRICE_TOO_HIGH,
            FlagType.PRICE_ROUND_NUMBER,
            FlagType.DESCRIPTION_GENERIC,
            FlagType.IMAGES_TOO_FEW,
            FlagType.IMAGES_MISMATCH,
            FlagType.SELLER_NEW_ACCOUNT,
            FlagType.SELLER_NO_RATING,
            FlagType.CONTACT_WHATSAPP_ONLY,
            FlagType.URGENCY_LANGUAGE,
        }

        if flag_type in high_severity:
            return RiskLevel.HIGH
        elif flag_type in medium_severity:
            return RiskLevel.MEDIUM
        return RiskLevel.LOW

    # Rule implementations
    def _check_price_too_low(self, ctx: Dict) -> bool:
        """Check if price is suspiciously low."""
        price = ctx["price"]
        price_vs_msrp = ctx.get("price_vs_msrp")
        depreciation = ctx.get("depreciation")

        # If we have MSRP comparison
        if price_vs_msrp is not None and price_vs_msrp < 30:
            return True

        # If we have depreciation
        if depreciation is not None and depreciation > 85:
            return True

        # Absolute thresholds for phones
        if price < 2000:  # Less than 2000 INR for any smartphone
            return True

        return False

    def _check_price_too_high(self, ctx: Dict) -> bool:
        """Check if price is suspiciously high."""
        price = ctx["price"]
        price_vs_msrp = ctx.get("price_vs_msrp")

        if price_vs_msrp is not None and price_vs_msrp > 120:
            return True

        # Absolute threshold
        if price > 200000:  # More than 2L for used phone
            return True

        return False

    def _check_round_price(self, ctx: Dict) -> bool:
        """Check if price is a round number."""
        price = ctx["price"]
        return price % 1000 == 0 and price >= 5000

    def _check_short_description(self, ctx: Dict) -> bool:
        """Check if description is too short."""
        desc = ctx["description"]
        return len(desc.strip()) < 50

    def _check_generic_description(self, ctx: Dict) -> bool:
        """Check for generic/template descriptions."""
        desc = ctx["description"]
        generic_phrases = [
            "brand new", "best price", "urgent sale", "moving abroad",
            "gift received", "unwanted gift", "bought by mistake",
            "perfect condition", "no scratch", "like new",
            "contact me", "call me", "whatsapp me",
            "genuine buyer", "serious buyer", "no time waster",
        ]
        desc_lower = desc.lower()
        matches = sum(1 for phrase in generic_phrases if phrase in desc_lower)
        return matches >= 3

    def _check_description_mismatch(self, ctx: Dict) -> bool:
        """Check if description contradicts title/specs."""
        title = ctx["title"]
        desc = ctx["description"]
        spec = ctx["spec"]

        if not spec:
            return False

        # Check if title mentions different brand/model
        title_brands = ["samsung", "apple", "xiaomi", "oneplus", "realme", "vivo", "oppo", "motorola", "nokia"]
        desc_brands = ["samsung", "apple", "xiaomi", "oneplus", "realme", "vivo", "oppo", "motorola", "nokia"]

        title_brand = next((b for b in title_brands if b in title), None)
        desc_brand = next((b for b in desc_brands if b in desc), None)

        if title_brand and desc_brand and title_brand != desc_brand:
            return True

        # Check RAM/storage mismatch
        if spec.ram_gb and ctx["ram_gb"] and spec.ram_gb != ctx["ram_gb"]:
            diff = abs(spec.ram_gb - ctx["ram_gb"])
            if diff > 4:  # Significant difference
                return True

        return False

    def _check_stock_images(self, ctx: Dict) -> bool:
        """Check if images appear to be stock photos."""
        images = ctx["images"]
        if not images:
            return False

        stock_indicators = [
            "gsmarena", "official", "press", "render", "wallpaper",
            "cdn", "static", "assets", "marketing", "promo",
        ]

        stock_count = 0
        for img in images:
            img_lower = img.lower()
            if any(indicator in img_lower for indicator in stock_indicators):
                stock_count += 1

        # If more than half images look like stock photos
        return stock_count > len(images) / 2

    def _check_few_images(self, ctx: Dict) -> bool:
        """Check if listing has very few images."""
        images = ctx["images"]
        return len(images) <= 1

    def _check_image_mismatch(self, ctx: Dict) -> bool:
        """Check if images don't match described phone."""
        # This would require image analysis - placeholder
        return False

    def _check_new_seller(self, ctx: Dict) -> bool:
        """Check if seller account appears new."""
        # We don't have account age directly, but can infer
        # Placeholder - would need seller profile data
        return False

    def _check_multiple_listings(self, ctx: Dict) -> bool:
        """Check if seller has multiple similar listings."""
        # Would need cross-listing analysis - placeholder
        return False

    def _check_low_rating(self, ctx: Dict) -> bool:
        """Check if seller has low rating."""
        rating = ctx["seller_rating"]
        return rating is not None and rating < 3.0

    def _check_contact_in_description(self, ctx: Dict) -> bool:
        """Check for contact info in description."""
        desc = ctx["description"]
        patterns = [
            r'\b\d{10}\b',  # 10-digit phone
            r'\b\d{5}\s?\d{5}\b',  # 5+5 phone format
            r'[\w\.-]+@[\w\.-]+\.\w+',  # email
            r'whatsapp', r'telegram', r'signal',
        ]
        return any(re.search(p, desc, re.IGNORECASE) for p in patterns)

    def _check_external_contact(self, ctx: Dict) -> bool:
        """Check for requests to contact outside platform."""
        desc = ctx["description"]
        external_phrases = [
            "contact outside", "direct contact", "call directly",
            "whatsapp me", "telegram me", "message me on",
            "my number", "call on", "contact on",
            "not on olx", "outside olx", "bypass olx",
        ]
        return any(phrase in desc for phrase in external_phrases)

    def _check_spec_mismatch(self, ctx: Dict) -> bool:
        """Check if listed specs don't match known phone specs."""
        spec = ctx["spec"]
        if not spec:
            return False

        ram_gb = ctx["ram_gb"]
        storage_gb = ctx["storage_gb"]

        # Check if listing claims specs that don't exist for this model
        # This is complex - simplified check
        if ram_gb and spec.ram_gb:
            # Check if claimed RAM is impossible for this model
            known_rams = [spec.ram_gb]
            if spec.virtual_ram_gb:
                known_rams.append(spec.ram_gb + spec.virtual_ram_gb)

            if ram_gb not in known_rams and ram_gb > max(known_rams) * 1.5:
                return True

        return False

    def _check_impossible_specs(self, ctx: Dict) -> bool:
        """Check for impossible spec combinations."""
        ram_gb = ctx["ram_gb"]
        storage_gb = ctx["storage_gb"]

        # Impossible combinations
        if ram_gb and storage_gb:
            # More RAM than storage (very unlikely)
            if ram_gb > storage_gb:
                return True

            # Extremely high RAM for phone
            if ram_gb > 24:
                return True

            # Extremely high storage for phone
            if storage_gb > 2048:
                return True

        return False

    def _check_location_mismatch(self, ctx: Dict) -> bool:
        """Check for location inconsistencies."""
        # Would need more data - placeholder
        return False

    def _check_urgency(self, ctx: Dict) -> bool:
        """Check for urgency pressure tactics."""
        text = ctx["title"] + " " + ctx["description"]
        urgency_phrases = [
            "urgent", "immediate", "today only", "last chance",
            "selling fast", "hurry", "limited time", "need money",
            "emergency", "desperate", "quick sale", "asap",
        ]
        return any(phrase in text for phrase in urgency_phrases)


async def run_fraud_detection(
    db,
    city=None,
    limit: int = 1000,
) -> List[FraudAnalysis]:
    """Run fraud detection on enriched listings."""
    from ..enrichment import EnrichmentEngine

    engine = EnrichmentEngine(db)
    detector = FraudDetector()

    enriched_listings = await engine.enrich_all_listings(city=city, limit=limit)
    analyses = []

    for enriched in enriched_listings:
        analysis = detector.analyze(enriched)
        await db.save_fraud_analysis(analysis)
        analyses.append(analysis)

    return analyses