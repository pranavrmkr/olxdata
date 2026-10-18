"""
SQLite database operations for OLX scraper.
Handles persistence of listings, specs, fraud analysis, and collection runs.
"""

import sqlite3
import json
import aiosqlite
from pathlib import Path
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any, AsyncIterator
from contextlib import asynccontextmanager
import uuid

from .models import (
    RawListing, PhoneSpec, EnrichedListing, FraudAnalysis,
    FraudFlag, CollectionRun, DataQualityReport, City, Condition, RiskLevel, ListingSource
)


SCHEMA = """
-- Raw listings table
CREATE TABLE IF NOT EXISTS raw_listings (
    id TEXT PRIMARY KEY,
    listing_id TEXT UNIQUE NOT NULL,
    url TEXT NOT NULL,
    city TEXT NOT NULL,
    title TEXT NOT NULL,
    price INTEGER NOT NULL,
    description TEXT,
    condition TEXT,
    seller_name TEXT,
    seller_type TEXT,
    seller_rating REAL,
    listing_date TEXT,
    images TEXT,  -- JSON array
    collected_at TEXT NOT NULL,
    source TEXT NOT NULL,
    raw_html TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Phone specifications table
CREATE TABLE IF NOT EXISTS phone_specs (
    id TEXT PRIMARY KEY,
    brand TEXT NOT NULL,
    model TEXT NOT NULL,
    variant TEXT,
    ram_gb INTEGER NOT NULL,
    storage_gb INTEGER NOT NULL,
    virtual_ram_gb INTEGER,
    expandable_storage INTEGER DEFAULT 0,
    launch_year INTEGER NOT NULL,
    launch_date TEXT,
    original_msrp_inr INTEGER,
    original_msrp_usd INTEGER,
    display_size_inches REAL,
    display_type TEXT,
    processor TEXT,
    battery_mah INTEGER,
    rear_camera_mp TEXT,
    front_camera_mp TEXT,
    os_at_launch TEXT,
    weight_grams INTEGER,
    dimensions_mm TEXT,
    colors TEXT,  -- JSON array
    network_technologies TEXT,  -- JSON array
    source_urls TEXT,  -- JSON array
    source_retrieved_at TEXT NOT NULL,
    confidence REAL DEFAULT 1.0,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(brand, model, variant, ram_gb, storage_gb)
);

-- Enriched listings table (links raw listings to phone specs)
CREATE TABLE IF NOT EXISTS enriched_listings (
    id TEXT PRIMARY KEY,
    raw_listing_id TEXT NOT NULL,
    phone_spec_id TEXT,
    match_confidence REAL DEFAULT 0.0,
    match_method TEXT,
    age_years REAL,
    price_vs_msrp_pct REAL,
    depreciation_pct REAL,
    enriched_at TEXT NOT NULL,
    FOREIGN KEY (raw_listing_id) REFERENCES raw_listings(id),
    FOREIGN KEY (phone_spec_id) REFERENCES phone_specs(id)
);

-- Fraud analysis table
CREATE TABLE IF NOT EXISTS fraud_analysis (
    id TEXT PRIMARY KEY,
    listing_id TEXT NOT NULL,
    risk_level TEXT NOT NULL,
    risk_score REAL NOT NULL,
    flags TEXT NOT NULL,  -- JSON array of FraudFlag objects
    analyzed_at TEXT NOT NULL,
    analyzer_version TEXT NOT NULL,
    FOREIGN KEY (listing_id) REFERENCES raw_listings(id)
);

-- Collection runs metadata
CREATE TABLE IF NOT EXISTS collection_runs (
    id TEXT PRIMARY KEY,
    started_at TEXT NOT NULL,
    completed_at TEXT,
    status TEXT NOT NULL,
    cities_scraped TEXT,  -- JSON array
    total_listings_found INTEGER DEFAULT 0,
    total_listings_saved INTEGER DEFAULT 0,
    total_duplicates INTEGER DEFAULT 0,
    total_errors INTEGER DEFAULT 0,
    error_details TEXT,  -- JSON array
    config_snapshot TEXT,  -- JSON object
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Spec cache for enrichment (separate from phone_specs for raw cache)
CREATE TABLE IF NOT EXISTS spec_cache (
    id TEXT PRIMARY KEY,
    query_key TEXT UNIQUE NOT NULL,  -- e.g., "samsung galaxy s23 ultra 8/128"
    brand TEXT,
    model TEXT,
    variant TEXT,
    response_data TEXT NOT NULL,  -- JSON response from source
    source TEXT NOT NULL,
    retrieved_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_raw_listings_city ON raw_listings(city);
CREATE INDEX IF NOT EXISTS idx_raw_listings_listing_id ON raw_listings(listing_id);
CREATE INDEX IF NOT EXISTS idx_raw_listings_collected_at ON raw_listings(collected_at);
CREATE INDEX IF NOT EXISTS idx_phone_specs_brand_model ON phone_specs(brand, model);
CREATE INDEX IF NOT EXISTS idx_enriched_raw_listing ON enriched_listings(raw_listing_id);
CREATE INDEX IF NOT EXISTS idx_fraud_listing ON fraud_analysis(listing_id);
CREATE INDEX IF NOT EXISTS idx_spec_cache_query ON spec_cache(query_key);
CREATE INDEX IF NOT EXISTS idx_spec_cache_expires ON spec_cache(expires_at);
"""


class Database:
    """Async SQLite database manager."""

    def __init__(self, db_path: str = "data/olx_data.db", wal_mode: bool = True):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.wal_mode = wal_mode
        self._pool: Optional[aiosqlite.Connection] = None

    async def initialize(self) -> None:
        """Initialize database schema."""
        async with aiosqlite.connect(self.db_path) as db:
            if self.wal_mode:
                await db.execute("PRAGMA journal_mode=WAL;")
            await db.execute("PRAGMA foreign_keys=ON;")
            await db.executescript(SCHEMA)
            await db.commit()
        self._pool = await aiosqlite.connect(self.db_path)
        if self.wal_mode:
            await self._pool.execute("PRAGMA journal_mode=WAL;")
        await self._pool.execute("PRAGMA foreign_keys=ON;")

    async def close(self) -> None:
        """Close database connections."""
        if self._pool:
            await self._pool.close()
            self._pool = None

    @asynccontextmanager
    async def transaction(self) -> AsyncIterator[aiosqlite.Connection]:
        """Context manager for database transactions."""
        if not self._pool:
            await self.initialize()
        async with self._pool.execute("BEGIN") as cursor:
            try:
                yield self._pool
                await self._pool.commit()
            except Exception:
                await self._pool.rollback()
                raise

    # Raw Listings Operations
    async def save_raw_listing(self, listing: RawListing) -> bool:
        """Save a raw listing. Returns True if new, False if duplicate."""
        async with self.transaction() as db:
            try:
                await db.execute(
                    """INSERT INTO raw_listings
                    (id, listing_id, url, city, title, price, description, condition,
                     seller_name, seller_type, seller_rating, listing_date, images,
                     collected_at, source, raw_html)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        listing.id,
                        listing.listing_id,
                        str(listing.url),
                        listing.city.value,
                        listing.title,
                        listing.price,
                        listing.description,
                        listing.condition.value,
                        listing.seller_name,
                        listing.seller_type,
                        listing.seller_rating,
                        listing.listing_date.isoformat() if listing.listing_date else None,
                        json.dumps(listing.images),
                        listing.collected_at.isoformat(),
                        listing.source.value,
                        listing.raw_html,
                    )
                )
                return True
            except sqlite3.IntegrityError:
                # Duplicate listing_id
                return False

    async def get_raw_listing(self, listing_id: str) -> Optional[RawListing]:
        """Get a raw listing by OLX listing_id."""
        async with self._pool.execute(
            "SELECT * FROM raw_listings WHERE listing_id = ?", (listing_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return self._row_to_raw_listing(row)
            return None

    async def get_raw_listings(
        self,
        city: Optional[City] = None,
        limit: int = 1000,
        offset: int = 0,
        days_back: Optional[int] = None
    ) -> List[RawListing]:
        """Get raw listings with optional city filter."""
        query = "SELECT * FROM raw_listings"
        params = []
        conditions = []
        if city:
            conditions.append("city = ?")
            params.append(city.value)
        if days_back:
            from datetime import datetime, timedelta
            cutoff = (datetime.utcnow() - timedelta(days=days_back)).isoformat()
            conditions.append("collected_at >= ?")
            params.append(cutoff)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY collected_at DESC LIMIT ? OFFSET ?"
        params.extend([limit, offset])

        async with self._pool.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_raw_listing(row) for row in rows]

    async def count_raw_listings(self, city: Optional[City] = None) -> int:
        """Count raw listings."""
        query = "SELECT COUNT(*) FROM raw_listings"
        params = []
        if city:
            query += " WHERE city = ?"
            params.append(city.value)
        async with self._pool.execute(query, params) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0

    def _row_to_raw_listing(self, row: tuple) -> RawListing:
        """Convert database row to RawListing model."""
        return RawListing(
            id=row[0],
            listing_id=row[1],
            url=row[2],
            city=City(row[3]),
            title=row[4],
            price=row[5],
            description=row[6] or "",
            condition=Condition(row[7]) if row[7] else Condition.UNKNOWN,
            seller_name=row[8],
            seller_type=row[9],
            seller_rating=row[10],
            listing_date=datetime.fromisoformat(row[11]) if row[11] else None,
            images=json.loads(row[12]) if row[12] else [],
            collected_at=datetime.fromisoformat(row[13]),
            source=ListingSource(row[14]),
            raw_html=row[15],
        )

    # Phone Specs Operations
    async def save_phone_spec(self, spec: PhoneSpec) -> str:
        """Save phone spec, return existing or new ID."""
        async with self.transaction() as db:
            # Check if exists
            async with db.execute(
                """SELECT id FROM phone_specs
                WHERE brand = ? AND model = ? AND variant = ? AND ram_gb = ? AND storage_gb = ?""",
                (spec.brand, spec.model, spec.variant, spec.ram_gb, spec.storage_gb)
            ) as cursor:
                row = await cursor.fetchone()
                if row:
                    return row[0]

            # Insert new
            await db.execute(
                """INSERT INTO phone_specs
                (id, brand, model, variant, ram_gb, storage_gb, virtual_ram_gb,
                 expandable_storage, launch_year, launch_date, original_msrp_inr,
                 original_msrp_usd, display_size_inches, display_type, processor,
                 battery_mah, rear_camera_mp, front_camera_mp, os_at_launch,
                 weight_grams, dimensions_mm, colors, network_technologies,
                 source_urls, source_retrieved_at, confidence, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    spec.id,
                    spec.brand,
                    spec.model,
                    spec.variant,
                    spec.ram_gb,
                    spec.storage_gb,
                    spec.virtual_ram_gb,
                    int(spec.expandable_storage),
                    spec.launch_year,
                    spec.launch_date,
                    spec.original_msrp_inr,
                    spec.original_msrp_usd,
                    spec.display_size_inches,
                    spec.display_type,
                    spec.processor,
                    spec.battery_mah,
                    spec.rear_camera_mp,
                    spec.front_camera_mp,
                    spec.os_at_launch,
                    spec.weight_grams,
                    spec.dimensions_mm,
                    json.dumps(spec.colors),
                    json.dumps(spec.network_technologies),
                    json.dumps(spec.source_urls),
                    spec.source_retrieved_at.isoformat(),
                    spec.confidence,
                    spec.notes,
                )
            )
            return spec.id

    async def get_phone_spec(self, spec_id: str) -> Optional[PhoneSpec]:
        """Get phone spec by ID."""
        async with self._pool.execute(
            "SELECT * FROM phone_specs WHERE id = ?", (spec_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return self._row_to_phone_spec(row)
            return None

    async def find_phone_spec(
        self, brand: str, model: str, variant: Optional[str] = None,
        ram_gb: Optional[int] = None, storage_gb: Optional[int] = None
    ) -> Optional[PhoneSpec]:
        """Find phone spec by attributes."""
        query = "SELECT * FROM phone_specs WHERE brand = ? AND model = ?"
        params = [brand, model]
        if variant:
            query += " AND variant = ?"
            params.append(variant)
        if ram_gb is not None:
            query += " AND ram_gb = ?"
            params.append(ram_gb)
        if storage_gb is not None:
            query += " AND storage_gb = ?"
            params.append(storage_gb)
        query += " ORDER BY confidence DESC LIMIT 1"

        async with self._pool.execute(query, params) as cursor:
            row = await cursor.fetchone()
            if row:
                return self._row_to_phone_spec(row)
            return None

    def _row_to_phone_spec(self, row: tuple) -> PhoneSpec:
        """Convert database row to PhoneSpec model."""
        return PhoneSpec(
            id=row[0],
            brand=row[1],
            model=row[2],
            variant=row[3],
            ram_gb=row[4],
            storage_gb=row[5],
            virtual_ram_gb=row[6],
            expandable_storage=bool(row[7]),
            launch_year=row[8],
            launch_date=row[9],
            original_msrp_inr=row[10],
            original_msrp_usd=row[11],
            display_size_inches=row[12],
            display_type=row[13],
            processor=row[14],
            battery_mah=row[15],
            rear_camera_mp=row[16],
            front_camera_mp=row[17],
            os_at_launch=row[18],
            weight_grams=row[19],
            dimensions_mm=row[20],
            colors=json.loads(row[21]) if row[21] else [],
            network_technologies=json.loads(row[22]) if row[22] else [],
            source_urls=json.loads(row[23]) if row[23] else [],
            source_retrieved_at=datetime.fromisoformat(row[24]),
            confidence=row[25],
            notes=row[26],
        )

    # Enriched Listings Operations
    async def save_enriched_listing(self, enriched: EnrichedListing) -> None:
        """Save enriched listing."""
        async with self.transaction() as db:
            phone_spec_id = None
            if enriched.phone_spec:
                phone_spec_id = await self.save_phone_spec(enriched.phone_spec)

            await db.execute(
                """INSERT OR REPLACE INTO enriched_listings
                (id, raw_listing_id, phone_spec_id, match_confidence, match_method,
                 age_years, price_vs_msrp_pct, depreciation_pct, enriched_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    enriched.raw_listing.id,
                    enriched.raw_listing.id,
                    phone_spec_id,
                    enriched.match_confidence,
                    enriched.match_method,
                    enriched.age_years,
                    enriched.price_vs_msrp_pct,
                    enriched.depreciation_pct,
                    enriched.enriched_at.isoformat(),
                )
            )

    async def get_enriched_listing(self, raw_listing_id: str) -> Optional[EnrichedListing]:
        """Get enriched listing by raw listing ID."""
        async with self._pool.execute(
            """SELECT el.*, rl.*, ps.* FROM enriched_listings el
            JOIN raw_listings rl ON el.raw_listing_id = rl.id
            LEFT JOIN phone_specs ps ON el.phone_spec_id = ps.id
            WHERE el.raw_listing_id = ?""",
            (raw_listing_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return self._row_to_enriched_listing(row)
            return None

    def _row_to_enriched_listing(self, row: tuple) -> EnrichedListing:
        """Convert database row to EnrichedListing model."""
        # Row structure: enriched_listings columns + raw_listings columns + phone_specs columns
        raw_listing = RawListing(
            id=row[10],  # raw_listings.id
            listing_id=row[11],
            url=row[12],
            city=City(row[13]),
            title=row[14],
            price=row[15],
            description=row[16] or "",
            condition=Condition(row[17]) if row[17] else Condition.UNKNOWN,
            seller_name=row[18],
            seller_type=row[19],
            seller_rating=row[20],
            listing_date=datetime.fromisoformat(row[21]) if row[21] else None,
            images=json.loads(row[22]) if row[22] else [],
            collected_at=datetime.fromisoformat(row[23]),
            source=ListingSource(row[24]),
            raw_html=row[25],
        )

        phone_spec = None
        if row[30]:  # phone_specs.id exists
            phone_spec = PhoneSpec(
                id=row[30],
                brand=row[31],
                model=row[32],
                variant=row[33],
                ram_gb=row[34],
                storage_gb=row[35],
                virtual_ram_gb=row[36],
                expandable_storage=bool(row[37]),
                launch_year=row[38],
                launch_date=row[39],
                original_msrp_inr=row[40],
                original_msrp_usd=row[41],
                display_size_inches=row[42],
                display_type=row[43],
                processor=row[44],
                battery_mah=row[45],
                rear_camera_mp=row[46],
                front_camera_mp=row[47],
                os_at_launch=row[48],
                weight_grams=row[49],
                dimensions_mm=row[50],
                colors=json.loads(row[51]) if row[51] else [],
                network_technologies=json.loads(row[52]) if row[52] else [],
                source_urls=json.loads(row[53]) if row[53] else [],
                source_retrieved_at=datetime.fromisoformat(row[54]),
                confidence=row[55],
                notes=row[56],
            )

        return EnrichedListing(
            raw_listing=raw_listing,
            phone_spec=phone_spec,
            match_confidence=row[3],
            match_method=row[4],
            age_years=row[5],
            price_vs_msrp_pct=row[6],
            depreciation_pct=row[7],
            enriched_at=datetime.fromisoformat(row[8]),
        )

    # Fraud Analysis Operations
    async def save_fraud_analysis(self, analysis: FraudAnalysis) -> None:
        """Save fraud analysis."""
        async with self.transaction() as db:
            await db.execute(
                """INSERT OR REPLACE INTO fraud_analysis
                (id, listing_id, risk_level, risk_score, flags, analyzed_at, analyzer_version)
                VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    analysis.listing_id,
                    analysis.listing_id,
                    analysis.risk_level.value,
                    analysis.risk_score,
                    json.dumps([f.model_dump() for f in analysis.flags]),
                    analysis.analyzed_at.isoformat(),
                    analysis.analyzer_version,
                )
            )

    async def get_fraud_analysis(self, listing_id: str) -> Optional[FraudAnalysis]:
        """Get fraud analysis for a listing."""
        async with self._pool.execute(
            "SELECT * FROM fraud_analysis WHERE listing_id = ?", (listing_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return FraudAnalysis(
                    listing_id=row[1],
                    risk_level=RiskLevel(row[2]),
                    risk_score=row[3],
                    flags=[FraudFlag(**f) for f in json.loads(row[4])],
                    analyzed_at=datetime.fromisoformat(row[5]),
                    analyzer_version=row[6],
                )
            return None

    # Collection Runs Operations
    async def save_collection_run(self, run: CollectionRun) -> None:
        """Save collection run metadata."""
        async with self.transaction() as db:
            await db.execute(
                """INSERT OR REPLACE INTO collection_runs
                (id, started_at, completed_at, status, cities_scraped,
                 total_listings_found, total_listings_saved, total_duplicates,
                 total_errors, error_details, config_snapshot)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    run.id,
                    run.started_at.isoformat(),
                    run.completed_at.isoformat() if run.completed_at else None,
                    run.status,
                    json.dumps([c.value if hasattr(c, 'value') else c for c in run.cities_scraped]),
                    run.total_listings_found,
                    run.total_listings_saved,
                    run.total_duplicates,
                    run.total_errors,
                    json.dumps(run.error_details),
                    json.dumps(run.config_snapshot),
                )
            )

    async def get_collection_run(self, run_id: str) -> Optional[CollectionRun]:
        """Get collection run by ID."""
        async with self._pool.execute(
            "SELECT * FROM collection_runs WHERE id = ?", (run_id,)
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return CollectionRun(
                    id=row[0],
                    started_at=datetime.fromisoformat(row[1]),
                    completed_at=datetime.fromisoformat(row[2]) if row[2] else None,
                    status=row[3],
                    cities_scraped=[City(c) for c in json.loads(row[4])] if row[4] else [],
                    total_listings_found=row[5],
                    total_listings_saved=row[6],
                    total_duplicates=row[7],
                    total_errors=row[8],
                    error_details=json.loads(row[9]) if row[9] else [],
                    config_snapshot=json.loads(row[10]) if row[10] else {},
                )
            return None

    # Spec Cache Operations
    async def get_spec_cache(self, query_key: str, max_age_days: int = 30) -> Optional[Dict[str, Any]]:
        """Get cached spec data if not expired."""
        async with self._pool.execute(
            """SELECT response_data FROM spec_cache
            WHERE query_key = ? AND expires_at > ?""",
            (query_key, datetime.utcnow().isoformat())
        ) as cursor:
            row = await cursor.fetchone()
            if row:
                return json.loads(row[0])
            return None

    async def set_spec_cache(
        self, query_key: str, response_data: Dict[str, Any],
        source: str, ttl_days: int = 30,
        brand: Optional[str] = None, model: Optional[str] = None, variant: Optional[str] = None
    ) -> None:
        """Cache spec data with TTL."""
        expires_at = datetime.utcnow() + timedelta(days=ttl_days)
        async with self.transaction() as db:
            await db.execute(
                """INSERT OR REPLACE INTO spec_cache
                (id, query_key, brand, model, variant, response_data, source, retrieved_at, expires_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    str(uuid.uuid4()),
                    query_key,
                    brand, model, variant,
                    json.dumps(response_data),
                    source,
                    datetime.utcnow().isoformat(),
                    expires_at.isoformat(),
                )
            )

    async def cleanup_expired_cache(self) -> int:
        """Remove expired cache entries. Returns count removed."""
        async with self.transaction() as db:
            cursor = await db.execute(
                "DELETE FROM spec_cache WHERE expires_at < ?",
                (datetime.utcnow().isoformat(),)
            )
            return cursor.rowcount

    async def get_all_phone_specs(self) -> List[PhoneSpec]:
        """Get all phone specs."""
        async with self._pool.execute("SELECT * FROM phone_specs ORDER BY brand, model") as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_phone_spec(row) for row in rows]

    async def get_enriched_listings(
        self, city: Optional[City] = None, limit: int = 1000, days_back: Optional[int] = None
    ) -> List[EnrichedListing]:
        """Get enriched listings with optional city filter."""
        query = """SELECT el.*, rl.*, ps.* FROM enriched_listings el
            JOIN raw_listings rl ON el.raw_listing_id = rl.id
            LEFT JOIN phone_specs ps ON el.phone_spec_id = ps.id"""
        params = []
        conditions = []
        if city:
            conditions.append("rl.city = ?")
            params.append(city.value)
        if days_back:
            from datetime import datetime, timedelta
            cutoff = (datetime.utcnow() - timedelta(days=days_back)).isoformat()
            conditions.append("el.enriched_at >= ?")
            params.append(cutoff)

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        query += " ORDER BY el.enriched_at DESC LIMIT ?"
        params.append(limit)

        async with self._pool.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [self._row_to_enriched_listing(row) for row in rows]

    async def get_fraud_analyses(self, limit: int = 1000, days_back: Optional[int] = None) -> List[FraudAnalysis]:
        """Get fraud analyses."""
        query = "SELECT * FROM fraud_analysis"
        params = []
        if days_back:
            from datetime import datetime, timedelta
            cutoff = (datetime.utcnow() - timedelta(days=days_back)).isoformat()
            query += " WHERE analyzed_at >= ?"
            params.append(cutoff)
        query += " ORDER BY analyzed_at DESC LIMIT ?"
        params.append(limit)

        async with self._pool.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            results = []
            for row in rows:
                results.append(FraudAnalysis(
                    listing_id=row[1],
                    risk_level=RiskLevel(row[2]),
                    risk_score=row[3],
                    flags=[FraudFlag(**f) for f in json.loads(row[4])],
                    analyzed_at=datetime.fromisoformat(row[5]),
                    analyzer_version=row[6],
                ))
            return results

    async def get_statistics(self) -> Dict[str, Any]:
        """Get database statistics."""
        stats = {}

        # Raw listings count
        async with self._pool.execute("SELECT COUNT(*) FROM raw_listings") as cursor:
            stats["raw_listings"] = (await cursor.fetchone())[0]

        # Enriched listings count
        async with self._pool.execute("SELECT COUNT(*) FROM enriched_listings") as cursor:
            stats["enriched_listings"] = (await cursor.fetchone())[0]

        # Phone specs count
        async with self._pool.execute("SELECT COUNT(*) FROM phone_specs") as cursor:
            stats["phone_specs"] = (await cursor.fetchone())[0]

        # Fraud analyses count
        async with self._pool.execute("SELECT COUNT(*) FROM fraud_analysis") as cursor:
            stats["fraud_analyses"] = (await cursor.fetchone())[0]

        # Listings by city
        async with self._pool.execute(
            "SELECT city, COUNT(*) FROM raw_listings GROUP BY city"
        ) as cursor:
            stats["by_city"] = dict(await cursor.fetchall())

        # Listings by condition
        async with self._pool.execute(
            "SELECT condition, COUNT(*) FROM raw_listings GROUP BY condition"
        ) as cursor:
            stats["by_condition"] = dict(await cursor.fetchall())

        # Fraud by level
        async with self._pool.execute(
            "SELECT risk_level, COUNT(*) FROM fraud_analysis GROUP BY risk_level"
        ) as cursor:
            stats["fraud_by_level"] = dict(await cursor.fetchall())

        # Collection runs
        async with self._pool.execute("SELECT COUNT(*) FROM collection_runs") as cursor:
            stats["collection_runs"] = (await cursor.fetchone())[0]

        return stats