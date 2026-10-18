"""
Utils package for OLX scraper.
"""

from .logging import setup_logging, get_logger
from .helpers import (
    extract_price, extract_listing_id, normalize_text,
    parse_ram_storage, detect_condition, random_delay, sleep_random,
    build_olx_search_url, extract_query_params, is_valid_phone_listing,
    calculate_age_years, calculate_depreciation, calculate_price_vs_msrp,
    slugify
)

__all__ = [
    "setup_logging", "get_logger",
    "extract_price", "extract_listing_id", "normalize_text",
    "parse_ram_storage", "detect_condition", "random_delay", "sleep_random",
    "build_olx_search_url", "extract_query_params", "is_valid_phone_listing",
    "calculate_age_years", "calculate_depreciation", "calculate_price_vs_msrp",
    "slugify",
]