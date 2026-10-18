"""
Common utilities for OLX scraper.
"""

import re
import random
import asyncio
from datetime import datetime
from typing import Optional, List, Dict, Any
from urllib.parse import urlparse, parse_qs


def extract_price(text: str) -> Optional[int]:
    """Extract price in INR from text."""
    if not text:
        return None

    # Remove currency symbols and commas
    cleaned = re.sub(r'[₹,\s]', '', text)

    # Find numbers (handle lakhs/crores)
    patterns = [
        r'(\d+(?:\.\d+)?)\s*[Ll]akh',
        r'(\d+(?:\.\d+)?)\s*[Cc]rore',
        r'(\d{1,3}(?:,\d{3})*(?:\.\d{2})?)',
        r'(\d+)',
    ]

    for pattern in patterns:
        match = re.search(pattern, cleaned, re.IGNORECASE)
        if match:
            try:
                val = float(match.group(1))
                if 'lakh' in pattern.lower():
                    return int(val * 100000)
                elif 'crore' in pattern.lower():
                    return int(val * 10000000)
                return int(val)
            except ValueError:
                continue
    return None


def extract_listing_id(url: str) -> Optional[str]:
    """Extract OLX listing ID from URL."""
    # OLX URLs typically have pattern: /item/...-iid-<id> or similar
    patterns = [
        r'-iid-(\d+)',
        r'/item/.*?(\d{8,})',
        r'[?&]id=(\d+)',
        r'/(\d{10,})',
    ]

    for pattern in patterns:
        match = re.search(pattern, url)
        if match:
            return match.group(1)
    return None


def normalize_text(text: str) -> str:
    """Normalize text for comparison."""
    if not text:
        return ""
    # Remove extra whitespace, normalize unicode
    text = re.sub(r'\s+', ' ', text.strip())
    return text.lower()


def parse_ram_storage(text: str) -> Dict[str, Optional[int]]:
    """Parse RAM and storage from text like '8GB RAM 128GB Storage' or '8/128'."""
    result = {"ram_gb": None, "storage_gb": None}

    if not text:
        return result

    text = text.lower()

    # Pattern: 8/128, 8GB/128GB, 8GB RAM 128GB Storage
    patterns = [
        r'(\d+)\s*[Gg][Bb]?\s*/\s*(\d+)\s*[Gg][Bb]?',  # 8/128 or 8GB/128GB
        r'(\d+)\s*[Gg][Bb]\s*[Rr][Aa][Mm].*?(\d+)\s*[Gg][Bb]',  # 8GB RAM 128GB
        r'[Rr][Aa][Mm]\s*[:\-]?\s*(\d+)\s*[Gg][Bb]',  # RAM: 8GB
        r'[Ss][Tt][Oo][Rr][Aa][Gg][Ee]\s*[:\-]?\s*(\d+)\s*[Gg][Bb]',  # Storage: 128GB
    ]

    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            groups = match.groups()
            if len(groups) >= 2:
                result["ram_gb"] = int(groups[0])
                result["storage_gb"] = int(groups[1])
            elif len(groups) == 1:
                if 'ram' in pattern.lower():
                    result["ram_gb"] = int(groups[0])
                elif 'storage' in pattern.lower():
                    result["storage_gb"] = int(groups[0])
            break

    # If not found, try standalone patterns
    if result["ram_gb"] is None:
        ram_match = re.search(r'(\d+)\s*[Gg][Bb]\s*[Rr][Aa][Mm]', text)
        if ram_match:
            result["ram_gb"] = int(ram_match.group(1))

    if result["storage_gb"] is None:
        storage_match = re.search(r'(\d+)\s*[Gg][Bb]\s*(?:[Ss][Tt][Oo][Rr][Aa][Gg][Ee]|[Rr][Oo][Mm])', text)
        if storage_match:
            result["storage_gb"] = int(storage_match.group(1))

    return result


def detect_condition(text: str) -> str:
    """Detect phone condition from text."""
    if not text:
        return "unknown"

    text = text.lower()

    conditions = {
        "new": ["brand new", "new ", "sealed", "unopened", "bnib"],
        "like_new": ["like new", "mint", "as new", "barely used", "excellent"],
        "good": ["good condition", "good ", "well maintained", "very good"],
        "fair": ["fair", "average", "okay", "decent", "usable", "working"],
        "poor": ["poor", "damaged", "broken", "cracked", "faulty", "issues", "repair"],
    }

    for condition, keywords in conditions.items():
        for kw in keywords:
            if kw in text:
                return condition

    return "unknown"


def random_delay(min_sec: float, max_sec: float) -> float:
    """Generate a random delay between min and max seconds."""
    return random.uniform(min_sec, max_sec)


async def sleep_random(min_sec: float, max_sec: float) -> None:
    """Sleep for a random duration."""
    delay = random_delay(min_sec, max_sec)
    await asyncio.sleep(delay)


def build_olx_search_url(city_code: str, query: str = "mobile phones", page: int = 1) -> str:
    """Build OLX search URL for a city."""
    base = f"https://www.olx.in/{city_code}/q-{query.replace(' ', '-')}"
    if page > 1:
        base += f"?page={page}"
    return base


def extract_query_params(url: str) -> Dict[str, Any]:
    """Extract query parameters from URL."""
    parsed = urlparse(url)
    return {k: v[0] if len(v) == 1 else v for k, v in parse_qs(parsed.query).items()}


def is_valid_phone_listing(title: str, description: str, price: int) -> bool:
    """Basic validation for phone listings."""
    if not title or len(title) < 5:
        return False

    if price < 500 or price > 300000:  # Reasonable phone price range
        return False

    # Must mention phone-related terms
    phone_keywords = [
        "mobile", "phone", "smartphone", "android", "iphone",
        "galaxy", "pixel", "oneplus", "xiaomi", "redmi", "poco",
        "realme", "oppo", "vivo", "motorola", "nokia", "asus",
        "rog", "gaming", "5g", "4g"
    ]

    text = f"{title} {description}".lower()
    has_phone_keyword = any(kw in text for kw in phone_keywords)

    # Exclude non-phone items
    exclude_keywords = [
        "cover", "case", "tempered", "glass", "screen guard",
        "charger", "cable", "earphone", "headphone", "watch",
        "band", "tablet", "laptop", "power bank", "battery",
        "repair", "spare", "part", "motherboard", "display",
        "camera", "lens", "back cover", "flip cover"
    ]

    has_exclude = any(kw in text for kw in exclude_keywords)

    return has_phone_keyword and not has_exclude


def calculate_age_years(launch_year: int, reference_date: Optional[datetime] = None) -> float:
    """Calculate age in years from launch year."""
    if reference_date is None:
        reference_date = datetime.utcnow()
    return reference_date.year - launch_year + (reference_date.timetuple().tm_yday / 365.25)


def calculate_depreciation(current_price: int, original_msrp: int) -> Optional[float]:
    """Calculate depreciation percentage."""
    if original_msrp <= 0:
        return None
    return round(((original_msrp - current_price) / original_msrp) * 100, 2)


def calculate_price_vs_msrp(current_price: int, original_msrp: int) -> Optional[float]:
    """Calculate current price as percentage of MSRP."""
    if original_msrp <= 0:
        return None
    return round((current_price / original_msrp) * 100, 2)


def slugify(text: str) -> str:
    """Create a URL-friendly slug."""
    text = text.lower().strip()
    text = re.sub(r'[^\w\s-]', '', text)
    text = re.sub(r'[\s_-]+', '-', text)
    text = re.sub(r'^-+|-+$', '', text)
    return text