"""
Storage package for OLX scraper.
"""

from .models import (
    RawListing, PhoneSpec, EnrichedListing, FraudAnalysis,
    FraudFlag, CollectionRun, DataQualityReport,
    PriceStats,
    City, Condition, RiskLevel, ListingSource
)
from .database import Database

__all__ = [
    "RawListing", "PhoneSpec", "EnrichedListing", "FraudAnalysis",
    "FraudFlag", "CollectionRun", "DataQualityReport",
    "PriceStats",
    "City", "Condition", "RiskLevel", "ListingSource",
    "Database",
    "init_database",
]


async def init_database(db_path: str = "data/olx_data.db") -> Database:
    """Initialize database and return Database instance."""
    db = Database(db_path)
    await db.initialize()
    return db