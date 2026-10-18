"""Tests for enrichment module."""

import pytest
from unittest.mock import AsyncMock, MagicMock
from src.enrichment import PhoneSpecMatcher
from src.storage import PhoneSpec, City, Condition, Database
from datetime import datetime


@pytest.fixture
def sample_specs():
    """Create sample phone specs for testing."""
    return [
        PhoneSpec(
            id="apple_iphone_13_128",
            brand="Apple",
            model="iPhone 13",
            variant="128GB",
            launch_year=2021,
            launch_date="2021-09-24",
            original_msrp_inr=79900,
            ram_gb=4,
            storage_gb=128,
        ),
        PhoneSpec(
            id="samsung_galaxy_s22_256",
            brand="Samsung",
            model="Galaxy S22",
            variant="256GB",
            launch_year=2022,
            launch_date="2022-02-09",
            original_msrp_inr=72999,
            ram_gb=8,
            storage_gb=256,
        ),
        PhoneSpec(
            id="oneplus_11_128",
            brand="OnePlus",
            model="11",
            variant="128GB",
            launch_year=2023,
            launch_date="2023-02-07",
            original_msrp_inr=56999,
            ram_gb=8,
            storage_gb=128,
        ),
    ]


@pytest.fixture
def mock_db(sample_specs):
    """Create a mock database."""
    db = AsyncMock(spec=Database)

    # Mock find_phone_spec to return matching spec
    async def find_spec(brand, model, variant=None, ram_gb=None, storage_gb=None):
        for spec in sample_specs:
            if (spec.brand.lower() == brand.lower() and
                spec.model.lower() == model.lower()):
                if variant is None or spec.variant == variant:
                    if ram_gb is None or spec.ram_gb == ram_gb:
                        if storage_gb is None or spec.storage_gb == storage_gb:
                            return spec
        return None

    db.find_phone_spec = find_spec
    db.save_phone_spec = AsyncMock(side_effect=lambda spec: spec.id)
    return db


@pytest.fixture
def matcher(mock_db):
    """Create matcher instance with mock database."""
    return PhoneSpecMatcher(mock_db)


def test_brand_normalization(matcher):
    """Test brand name normalization."""
    assert matcher.normalize_brand("Apple") == "apple"
    assert matcher.normalize_brand("APPLE") == "apple"
    assert matcher.normalize_brand("Samsung") == "samsung"
    assert matcher.normalize_brand("Xiaomi") == "xiaomi"
    assert matcher.normalize_brand("OnePlus") == "oneplus"
    assert matcher.normalize_brand("unknown") == "unknown"


def test_extract_brand_model(matcher):
    """Test brand and model extraction from title."""
    # Test with Apple
    brand, model, variant = matcher.extract_brand_model("Apple iPhone 13 128GB Blue", "")
    assert brand == "apple"
    assert "iphone 13" in model.lower()

    # Test with Samsung
    brand, model, variant = matcher.extract_brand_model("Samsung Galaxy S22 256GB", "")
    assert brand == "samsung"
    assert "galaxy s22" in model.lower()

    # Test with Xiaomi
    brand, model, variant = matcher.extract_brand_model("Xiaomi Redmi Note 12 Pro 5G", "")
    assert brand == "xiaomi"

    # Test with OnePlus
    brand, model, variant = matcher.extract_brand_model("OnePlus 11 128GB", "")
    assert brand == "oneplus"


def test_calculate_match_score(matcher):
    """Test match score calculation."""
    listing = MagicMock()
    listing.title = "Apple iPhone 13 128GB Blue Excellent Condition"
    listing.description = "Selling my iPhone 13 128GB in excellent condition"

    spec = PhoneSpec(
        id="apple_iphone_13_128",
        brand="Apple",
        model="iPhone 13",
        variant="128GB",
        launch_year=2021,
        original_msrp_inr=79900,
        ram_gb=4,
        storage_gb=128,
    )

    confidence, matched = matcher.calculate_match_score(listing, spec)

    assert confidence > 0.5
    assert matched.get("brand") is True
    assert matched.get("model_ratio", 0) >= 0.5
    assert matched.get("variant") is True


@pytest.mark.asyncio
async def test_find_or_fetch_spec_existing(matcher, sample_specs):
    """Test finding existing spec in database."""
    spec = await matcher.find_or_fetch_spec("Apple", "iPhone 13", "128GB", 4, 128)

    assert spec is not None
    assert spec.brand == "Apple"
    assert spec.model == "iPhone 13"
    assert spec.variant == "128GB"
    assert spec.ram_gb == 4
    assert spec.storage_gb == 128


@pytest.mark.asyncio
async def test_find_or_fetch_spec_not_found(matcher):
    """Test when spec not found in database."""
    # Mock db to return None for unknown phone
    matcher.db.find_phone_spec = AsyncMock(return_value=None)
    # Mock gsmarena search to return None
    import src.enrichment.engine as engine_module
    engine_module.gsmarena_search = AsyncMock(return_value=None)

    spec = await matcher.find_or_fetch_spec("Unknown", "Brand", "Model", 4, 128)

    assert spec is None


def test_create_phone_spec(matcher):
    """Test creating PhoneSpec from GSMArena data."""
    data = {
        "ram_gb": 8,
        "storage_gb": 256,
        "launch_year": 2022,
        "launch_date": "2022-02-09",
        "original_msrp_inr": 72999,
        "display_size_inches": 6.1,
        "display_type": "Dynamic AMOLED 2X",
        "processor": "Exynos 2200",
        "battery_mah": 3700,
        "rear_camera_mp": "50+12+10 MP",
        "front_camera_mp": "10 MP",
        "os_at_launch": "Android 12",
        "weight_grams": 167,
        "colors": ["Phantom Black", "Phantom White", "Green"],
        "network_technologies": ["5G", "4G", "3G", "2G"],
        "source_url": "https://www.gsmarena.com/samsung_galaxy_s22-11285.php",
    }

    spec = matcher._create_phone_spec(data, "samsung", "Galaxy S22", "256GB", 8, 256)

    assert spec.brand == "Samsung"
    assert spec.model == "Galaxy S22"
    assert spec.variant == "256GB"
    assert spec.ram_gb == 8
    assert spec.storage_gb == 256
    assert spec.launch_year == 2022
    assert spec.original_msrp_inr == 72999
    assert "gsmarena" in spec.notes.lower()


if __name__ == "__main__":
    pytest.main([__file__, "-v"])