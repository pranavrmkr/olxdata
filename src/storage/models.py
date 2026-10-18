"""
Data models for OLX scraper pipeline.
Uses Pydantic for validation and serialization.
"""

from datetime import datetime
from enum import Enum
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field, HttpUrl, validator
import uuid


class City(str, Enum):
    """Supported cities for scraping."""
    DELHI = "delhi"
    MUMBAI = "mumbai"
    CHENNAI = "chennai"
    BENGALURU = "bengaluru"
    KOLKATA = "kolkata"
    HYDERABAD = "hyderabad"


class Condition(str, Enum):
    """Phone condition categories."""
    NEW = "new"
    LIKE_NEW = "like_new"
    GOOD = "good"
    FAIR = "fair"
    POOR = "poor"
    UNKNOWN = "unknown"


class RiskLevel(str, Enum):
    """Fraud risk levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ListingSource(str, Enum):
    """Source of the listing data."""
    OLX = "olx"


class RawListing(BaseModel):
    """Raw listing as scraped from OLX."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    listing_id: str = Field(..., description="OLX's internal listing ID")
    url: HttpUrl = Field(..., description="Canonical listing URL")
    city: City = Field(..., description="City where listed")
    title: str = Field(..., description="Listing title")
    price: int = Field(..., ge=0, description="Asking price in INR")
    description: str = Field(default="", description="Full listing description")
    condition: Condition = Field(default=Condition.UNKNOWN)
    seller_name: Optional[str] = Field(None, description="Seller name if public")
    seller_type: Optional[str] = Field(None, description="Individual or dealer")
    seller_rating: Optional[float] = Field(None, ge=0, le=5)
    listing_date: Optional[datetime] = Field(None, description="When listing was posted")
    images: List[str] = Field(default_factory=list, description="Image URLs")
    collected_at: datetime = Field(default_factory=datetime.utcnow, description="Collection timestamp")
    source: ListingSource = ListingSource.OLX
    raw_html: Optional[str] = Field(None, description="Raw HTML for debugging")

    @validator('listing_id')
    def validate_listing_id(cls, v):
        if not v or not v.strip():
            raise ValueError("listing_id cannot be empty")
        return v.strip()

    @validator('price')
    def validate_price(cls, v):
        if v < 0:
            raise ValueError("Price cannot be negative")
        if v > 500000:  # 5 lakh upper bound for phones
            raise ValueError("Price seems unrealistic for a phone")
        return v

    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat(),
            HttpUrl: lambda v: str(v),
        }


class PhoneSpec(BaseModel):
    """Phone specifications from reliable sources."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    brand: str = Field(..., description="Manufacturer (e.g., Samsung, Apple)")
    model: str = Field(..., description="Exact model name (e.g., Galaxy S23 Ultra)")
    variant: Optional[str] = Field(None, description="Variant (e.g., 5G, Dual SIM)")
    ram_gb: int = Field(..., ge=0, description="Physical RAM in GB")
    storage_gb: int = Field(..., ge=0, description="Internal storage in GB")
    virtual_ram_gb: Optional[int] = Field(None, ge=0, description="Virtual/extended RAM if advertised")
    expandable_storage: bool = Field(default=False, description="Supports microSD")
    launch_year: int = Field(..., ge=2000, le=2030, description="Original launch year")
    launch_date: Optional[str] = Field(None, description="Exact launch date if known (YYYY-MM-DD)")
    original_msrp_inr: Optional[int] = Field(None, ge=0, description="Original Indian launch price in INR")
    original_msrp_usd: Optional[int] = Field(None, ge=0, description="Original global launch price in USD")
    display_size_inches: Optional[float] = Field(None, gt=0)
    display_type: Optional[str] = Field(None)
    processor: Optional[str] = Field(None)
    battery_mah: Optional[int] = Field(None, gt=0)
    rear_camera_mp: Optional[str] = Field(None)
    front_camera_mp: Optional[str] = Field(None)
    os_at_launch: Optional[str] = Field(None)
    weight_grams: Optional[int] = Field(None, gt=0)
    dimensions_mm: Optional[str] = Field(None)
    colors: List[str] = Field(default_factory=list)
    network_technologies: List[str] = Field(default_factory=list)
    source_urls: List[str] = Field(default_factory=list, description="URLs where specs were found")
    source_retrieved_at: datetime = Field(default_factory=datetime.utcnow)
    confidence: float = Field(default=1.0, ge=0, le=1, description="Confidence in spec accuracy")
    notes: Optional[str] = Field(None, description="Any caveats or discrepancies")

    @validator('ram_gb', 'storage_gb')
    def validate_memory(cls, v):
        if v not in [0, 1, 2, 3, 4, 6, 8, 12, 16, 18, 24, 32, 48, 64, 128, 256, 512, 1024]:
            pass
        return v

    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }


class EnrichedListing(BaseModel):
    """Raw listing enriched with phone specifications."""
    raw_listing: RawListing
    phone_spec: Optional[PhoneSpec] = None
    match_confidence: float = Field(default=0.0, ge=0, le=1, description="Confidence in model match")
    match_method: Optional[str] = Field(None, description="How the match was made")
    age_years: Optional[float] = Field(None, ge=0, description="Age in years at collection time")
    price_vs_msrp_pct: Optional[float] = Field(None, description="Current price as % of original MSRP")
    depreciation_pct: Optional[float] = Field(None, description="Depreciation from MSRP")
    enriched_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }


class FraudFlag(BaseModel):
    """Individual fraud/suspicion flag with evidence."""
    flag_type: str = Field(..., description="Type of flag (e.g., price_anomaly, spec_contradiction)")
    severity: RiskLevel = Field(..., description="Severity of this flag")
    description: str = Field(..., description="Human-readable description")
    evidence: Dict[str, Any] = Field(default_factory=dict, description="Supporting evidence")
    confidence: float = Field(default=1.0, ge=0, le=1, description="Confidence in this flag")


class FraudAnalysis(BaseModel):
    """Complete fraud analysis for a listing."""
    listing_id: str
    risk_level: RiskLevel = Field(default=RiskLevel.LOW)
    risk_score: float = Field(default=0.0, ge=0, le=1, description="Overall risk score 0-1")
    flags: List[FraudFlag] = Field(default_factory=list)
    analyzed_at: datetime = Field(default_factory=datetime.utcnow)
    analyzer_version: str = Field(default="1.0")

    @property
    def is_suspicious(self) -> bool:
        return self.risk_level in [RiskLevel.MEDIUM, RiskLevel.HIGH]

    @property
    def flag_count(self) -> int:
        return len(self.flags)

    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }


class PriceStats(BaseModel):
    """Price statistics for a phone model."""
    phone_spec_id: str
    city: Optional[City] = None
    condition: Optional[Condition] = None
    ram_gb: Optional[int] = None
    storage_gb: Optional[int] = None
    sample_size: int
    min_price: int
    max_price: int
    mean_price: float
    median_price: float
    std_dev: float
    percentile_25: int
    percentile_75: int
    condition_breakdown: Dict[str, Any] = Field(default_factory=dict)
    depreciation_curve: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = Field(default=0.0, ge=0, le=1)
    calculated_at: datetime = Field(default_factory=datetime.utcnow)

    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }


class CollectionRun(BaseModel):
    """Metadata about a collection run."""
    id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    started_at: datetime = Field(default_factory=datetime.utcnow)
    completed_at: Optional[datetime] = None
    status: str = Field(default="running")  # running, completed, failed, interrupted
    cities_scraped: List[City] = Field(default_factory=list)
    total_listings_found: int = 0
    total_listings_saved: int = 0
    total_duplicates: int = 0
    total_errors: int = 0
    error_details: List[str] = Field(default_factory=list)
    config_snapshot: Dict[str, Any] = Field(default_factory=dict)

    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }


class DataQualityReport(BaseModel):
    """Data quality metrics for a collection."""
    generated_at: datetime = Field(default_factory=datetime.utcnow)
    total_listings: int = 0
    by_city: Dict[str, int] = Field(default_factory=dict)
    by_brand: Dict[str, int] = Field(default_factory=dict)
    by_condition: Dict[str, int] = Field(default_factory=dict)
    missing_fields: Dict[str, int] = Field(default_factory=dict)
    duplicate_count: int = 0
    price_range: Dict[str, int] = Field(default_factory=dict)  # min, max, median
    enrichment_rate: float = Field(default=0.0, description="Fraction with phone specs")
    fraud_flagged_count: int = 0
    fraud_by_level: Dict[str, int] = Field(default_factory=dict)
    collection_runs: int = 0

    class Config:
        use_enum_values = True
        json_encoders = {
            datetime: lambda v: v.isoformat(),
        }