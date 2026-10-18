"""
Phone specification sources for enrichment.
"""

from .gsmarena import GSMArenaScraper, search_and_get_specs as gsmarena_search

__all__ = [
    "GSMArenaScraper",
    "gsmarena_search",
]