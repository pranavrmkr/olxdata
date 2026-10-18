"""Tests for storage module."""

import pytest
from datetime import datetime
from src.storage import (
    RawListing, PhoneSpec, EnrichedListing, FraudAnalysis,
    City, Condition, ListingSource, FraudFlag, RiskLevel
)


def test_city_enum():
    """Test City enum values."""
    assert City.MUMBAI.value == "mumbai"
    assert City.DELHI.value == "delhi"
    assert len(City) == 6


def test_condition_enum():
    """Test Condition enum values."""
    assert Condition.NEW.value == "new"
    assert Condition.LIKE_NEW.value == "like_new"
    assert len(Condition) == 6


def test_raw_listing_creation():
    """Test RawListing creation."""
    listing = RawListing(
        listing_id="test_123",
        url="https://olx.in/item/test_123",
        title="iPhone 13 128GB Blue",
        description="Selling my iPhone 13",
        price=55000,
        city=City.MUMBAI,
        condition=Condition.GOOD,
        seller_name="John Doe",
        seller_type="individual",
        seller_rating=4.5,
        images=["img1.jpg", "img2.jpg"],
        listing_date=datetime(2024, 1, 15),
    )

    assert listing.listing_id == "test_123"
    assert listing.price == 55000
    assert listing.city == City.MUMBAI
    assert listing.condition == Condition.GOOD


def test_phone_spec_creation():
    """Test PhoneSpec creation."""
    spec = PhoneSpec(
        id="apple_iphone_13_128",
        brand="Apple",
        model="iPhone 13",
        variant="128GB",
        launch_year=2021,
        launch_date="2021-09-24",
        original_msrp_inr=79900,
        ram_gb=4,
        storage_gb=128,
        display_size_inches=6.1,
        display_type="Super Retina XDR",
        processor="A15 Bionic",
        battery_mah=3227,
        os_at_launch="iOS 15",
    )

    assert spec.id == "apple_iphone_13_128"
    assert spec.brand == "Apple"
    assert spec.model == "iPhone 13"
    assert spec.variant == "128GB"
    assert spec.original_msrp_inr == 79900
    assert spec.launch_year == 2021
    assert spec.ram_gb == 4
    assert spec.storage_gb == 128


def test_enriched_listing_creation():
    """Test EnrichedListing creation."""
    raw_listing = RawListing(
        listing_id="test_123",
        url="https://olx.in/item/test_123",
        title="iPhone 13 128GB Blue",
        price=55000,
        city=City.MUMBAI,
        condition=Condition.GOOD,
    )

    phone_spec = PhoneSpec(
        id="apple_iphone_13_128",
        brand="Apple",
        model="iPhone 13",
        variant="128GB",
        launch_year=2021,
        original_msrp_inr=79900,
        ram_gb=4,
        storage_gb=128,
    )

    enriched = EnrichedListing(
        raw_listing=raw_listing,
        phone_spec=phone_spec,
        match_confidence=0.95,
        match_method="fuzzy_match",
        age_years=2.5,
        price_vs_msrp_pct=68.8,
        depreciation_pct=31.2,
    )

    assert enriched.raw_listing.listing_id == "test_123"
    assert enriched.phone_spec.id == "apple_iphone_13_128"
    assert enriched.match_confidence == 0.95
    assert enriched.price_vs_msrp_pct == 68.8


def test_fraud_analysis_creation():
    """Test FraudAnalysis creation."""
    analysis = FraudAnalysis(
        listing_id="test_123",
        flags=[
            FraudFlag(flag_type="price_too_low", severity=RiskLevel.HIGH, description="Price too low"),
            FraudFlag(flag_type="description_too_short", severity=RiskLevel.MEDIUM, description="Description too short"),
        ],
        risk_score=0.75,
        risk_level=RiskLevel.HIGH,
    )

    assert analysis.listing_id == "test_123"
    assert len(analysis.flags) == 2
    assert analysis.risk_score == 0.75
    assert analysis.risk_level == RiskLevel.HIGH
    assert analysis.is_suspicious is True


def test_raw_listing_to_dict():
    """Test RawListing serialization."""
    listing = RawListing(
        listing_id="test_123",
        url="https://olx.in/item/test_123",
        title="iPhone 13",
        price=55000,
        city=City.MUMBAI,
        condition=Condition.GOOD,
    )

    data = listing.model_dump()
    assert data["listing_id"] == "test_123"
    assert data["city"] == "mumbai"
    assert data["condition"] == "good"
    assert data["price"] == 55000


def test_phone_spec_to_dict():
    """Test PhoneSpec serialization."""
    spec = PhoneSpec(
        id="test_spec",
        brand="Apple",
        model="iPhone 13",
        launch_year=2021,
        original_msrp_inr=79900,
        ram_gb=4,
        storage_gb=128,
    )

    data = spec.model_dump()
    assert data["id"] == "test_spec"
    assert data["brand"] == "Apple"
    assert data["model"] == "iPhone 13"
    assert data["original_msrp_inr"] == 79900