"""
HTML parsing for OLX listings.
Extracts structured data from listing pages and search results.
"""

import re
import json
from datetime import datetime
from typing import Optional, List, Dict, Any
from urllib.parse import urljoin
from bs4 import BeautifulSoup

from ..utils.logging import get_logger
from ..utils.helpers import (
    extract_price, extract_listing_id, normalize_text,
    parse_ram_storage, detect_condition, is_valid_phone_listing,
    build_olx_search_url
)
from ..storage.models import RawListing, City, Condition, ListingSource

logger = get_logger(__name__)


class OLXListingParser:
    """Parse OLX listing pages and search results."""

    def __init__(self, city: City):
        self.city = city

    def parse_search_results(self, html: str, page_url: str) -> List[Dict[str, Any]]:
        """Parse search results page to extract listing summaries."""
        soup = BeautifulSoup(html, "lxml")
        listings = []

        # OLX uses various selectors - try multiple patterns
        selectors = [
            "li[data-aut-id='itemBox']",
            "li.EIR5N",
            "div[data-aut-id='itemBox']",
            "article[data-aut-id='itemBox']",
            ".IKo3_",
            ".EIR5N",
            "li._1DNjQ",
        ]

        items = []
        for selector in selectors:
            items = soup.select(selector)
            if items:
                logger.debug(f"Found {len(items)} items with selector: {selector}")
                break

        if not items:
            logger.warning("No listing items found on search results page")
            return listings

        for item in items:
            try:
                listing_data = self._parse_listing_card(item, page_url)
                if listing_data:
                    listings.append(listing_data)
            except Exception as e:
                logger.warning("Failed to parse listing card", error=str(e))
                continue

        return listings

    def _parse_listing_card(self, item: BeautifulSoup, base_url: str) -> Optional[Dict[str, Any]]:
        """Parse a single listing card from search results."""
        link_elem = item.select_one("a[href]")
        if not link_elem:
            return None

        url = link_elem.get("href", "")
        if url.startswith("/"):
            url = urljoin("https://www.olx.in", url)

        listing_id = extract_listing_id(url)
        if not listing_id:
            listing_id = item.get("data-aut-id", "").replace("itemBox", "").strip("-")
            if not listing_id:
                listing_id = item.get("data-id", "")

        title_elem = item.select_one("[data-aut-id='itemTitle'], ._2tW1I, ._2Gr10, h2, h3")
        title = title_elem.get_text(strip=True) if title_elem else ""

        price_elem = item.select_one("[data-aut-id='itemPrice'], ._89yzn, ._1zgtX, .notranslate")
        price_text = price_elem.get_text(strip=True) if price_elem else ""
        price = extract_price(price_text)

        location_elem = item.select_one("[data-aut-id='item-location'], ._2VQu4, ._1R2Lb")
        location = location_elem.get_text(strip=True) if location_elem else ""

        date_elem = item.select_one("[data-aut-id='item-date'], ._2eF8R, ._1R2Lb + span")
        date_text = date_elem.get_text(strip=True) if date_elem else ""
        listing_date = self._parse_date(date_text)

        img_elem = item.select_one("img")
        images = []
        if img_elem:
            src = img_elem.get("src") or img_elem.get("data-src") or img_elem.get("data-srcset", "").split()[0]
            if src:
                images.append(src)

        return {
            "listing_id": listing_id,
            "url": url,
            "title": title,
            "price": price,
            "location": location,
            "listing_date": listing_date,
            "images": images,
        }

    def parse_listing_detail(self, html: str, url: str) -> Optional[RawListing]:
        """Parse detailed listing page."""
        soup = BeautifulSoup(html, "lxml")

        listing_id = extract_listing_id(url)
        if not listing_id:
            script_data = self._extract_json_ld(soup)
            if script_data and "sku" in script_data:
                listing_id = script_data["sku"]

        if not listing_id:
            logger.warning("Could not extract listing ID", url=url)
            return None

        title = self._extract_title(soup)
        price = self._extract_price(soup)
        description = self._extract_description(soup)
        condition = self._extract_condition(soup, title, description)
        seller_name, seller_type, seller_rating = self._extract_seller_info(soup)
        listing_date = self._extract_listing_date(soup)
        images = self._extract_images(soup)

        if not is_valid_phone_listing(title, description, price or 0):
            logger.debug("Listing failed validation", listing_id=listing_id)
            return None

        return RawListing(
            listing_id=listing_id,
            url=url,
            city=self.city,
            title=title,
            price=price or 0,
            description=description,
            condition=Condition(condition),
            seller_name=seller_name,
            seller_type=seller_type,
            seller_rating=seller_rating,
            listing_date=listing_date,
            images=images,
            source=ListingSource.OLX,
            raw_html=html[:50000] if html else None,
        )

    def _extract_title(self, soup: BeautifulSoup) -> str:
        selectors = [
            "h1[data-aut-id='itemTitle']",
            "h1._3rJ6e",
            "h1._2tW1I",
            "h1",
            "[data-aut-id='itemTitle']",
        ]
        for selector in selectors:
            elem = soup.select_one(selector)
            if elem:
                return elem.get_text(strip=True)
        return ""

    def _extract_price(self, soup: BeautifulSoup) -> Optional[int]:
        selectors = [
            "[data-aut-id='itemPrice']",
            "._89yzn",
            "._1zgtX",
            ".notranslate",
            "span[data-aut-id='itemPrice']",
        ]
        for selector in selectors:
            elem = soup.select_one(selector)
            if elem:
                price = extract_price(elem.get_text(strip=True))
                if price:
                    return price
        return None

    def _extract_description(self, soup: BeautifulSoup) -> str:
        selectors = [
            "[data-aut-id='itemDescription']",
            "._3tL4-",
            "._2nc2E",
            ".description",
            "div[data-aut-id='description']",
        ]
        for selector in selectors:
            elem = soup.select_one(selector)
            if elem:
                return elem.get_text(separator="\n", strip=True)
        return ""

    def _extract_condition(self, soup: BeautifulSoup, title: str, description: str) -> str:
        selectors = [
            "[data-aut-id='itemCondition']",
            "._2VQu4",
            "span:contains('Condition')",
        ]
        for selector in selectors:
            elem = soup.select_one(selector)
            if elem:
                text = elem.get_text(strip=True)
                cond = detect_condition(text)
                if cond != "unknown":
                    return cond

        combined = f"{title} {description}"
        return detect_condition(combined)

    def _extract_seller_info(self, soup: BeautifulSoup) -> tuple:
        seller_name = None
        seller_type = None
        seller_rating = None

        name_selectors = [
            "[data-aut-id='sellerName']",
            "._2_4N0",
            "._1j_VG",
            ".seller-name",
        ]
        for selector in name_selectors:
            elem = soup.select_one(selector)
            if elem:
                seller_name = elem.get_text(strip=True)
                break

        type_selectors = [
            "[data-aut-id='sellerType']",
            "._2VQu4:contains('Individual')",
            "._2VQu4:contains('Dealer')",
            "._2VQu4:contains('Professional')",
        ]
        for selector in type_selectors:
            elem = soup.select_one(selector)
            if elem:
                text = elem.get_text(strip=True).lower()
                if "individual" in text or "owner" in text:
                    seller_type = "individual"
                elif "dealer" in text or "professional" in text or "shop" in text:
                    seller_type = "dealer"
                break

        rating_selectors = [
            "[data-aut-id='sellerRating']",
            "._3J8Dv",
            ".rating",
        ]
        for selector in rating_selectors:
            elem = soup.select_one(selector)
            if elem:
                text = elem.get_text(strip=True)
                rating_match = re.search(r'(\d+(?:\.\d+)?)', text)
                if rating_match:
                    seller_rating = float(rating_match.group(1))
                break

        return seller_name, seller_type, seller_rating

    def _extract_listing_date(self, soup: BeautifulSoup) -> Optional[datetime]:
        selectors = [
            "[data-aut-id='itemDate']",
            "._2eF8R",
            "time",
            "span:contains('Posted')",
            "span:contains('ago')",
        ]

        for selector in selectors:
            elem = soup.select_one(selector)
            if elem:
                text = elem.get_text(strip=True)
                dt_attr = elem.get("datetime")
                if dt_attr:
                    try:
                        return datetime.fromisoformat(dt_attr.replace("Z", "+00:00"))
                    except ValueError:
                        pass
                parsed = self._parse_date(text)
                if parsed:
                    return parsed
        return None

    def _parse_date(self, text: str) -> Optional[datetime]:
        if not text:
            return None

        text = text.lower().strip()

        if "today" in text or "just now" in text:
            return datetime.utcnow()
        if "yesterday" in text:
            from datetime import timedelta
            return datetime.utcnow() - timedelta(days=1)

        days_match = re.search(r'(\d+)\s*day', text)
        if days_match:
            from datetime import timedelta
            return datetime.utcnow() - timedelta(days=int(days_match.group(1)))

        hours_match = re.search(r'(\d+)\s*hour', text)
        if hours_match:
            from datetime import timedelta
            return datetime.utcnow() - timedelta(hours=int(hours_match.group(1)))

        weeks_match = re.search(r'(\d+)\s*week', text)
        if weeks_match:
            from datetime import timedelta
            return datetime.utcnow() - timedelta(weeks=int(weeks_match.group(1)))

        months_match = re.search(r'(\d+)\s*month', text)
        if months_match:
            from datetime import timedelta
            return datetime.utcnow() - timedelta(days=int(months_match.group(1)) * 30)

        date_patterns = [
            r'(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{4})',
            r'(\d{1,2})/(\d{1,2})/(\d{4})',
            r'(\d{4})-(\d{2})-(\d{2})',
        ]

        for pattern in date_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    if len(match.groups()) == 3:
                        if match.group(2).isalpha():
                            day, mon, year = match.groups()
                            month = datetime.strptime(mon[:3], "%b").month
                            return datetime(int(year), month, int(day))
                        else:
                            if len(match.group(1)) == 4:
                                year, month, day = match.groups()
                            else:
                                day, month, year = match.groups()
                            return datetime(int(year), int(month), int(day))
                except ValueError:
                    continue

        return None

    def _extract_images(self, soup: BeautifulSoup) -> List[str]:
        images = []

        selectors = [
            "[data-aut-id='itemImages'] img",
            "._23P7L img",
            ".gallery img",
            "figure img",
            "img[data-src]",
        ]

        for selector in selectors:
            for img in soup.select(selector):
                src = img.get("src") or img.get("data-src") or img.get("data-srcset", "").split()[0]
                if src and src not in images:
                    if src.startswith("//"):
                        src = "https:" + src
                    elif src.startswith("/"):
                        src = urljoin("https://www.olx.in", src)
                    images.append(src)

        return images[:20]

    def _extract_json_ld(self, soup: BeautifulSoup) -> Optional[Dict]:
        scripts = soup.find_all("script", type="application/ld+json")
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, list):
                    for item in data:
                        if item.get("@type") == "Product":
                            return item
                elif data.get("@type") == "Product":
                    return data
            except json.JSONDecodeError:
                continue
        return None


class OLXSearchURLBuilder:
    """Build OLX search URLs for different cities and queries."""

    CITY_CODES = {
        City.DELHI: "delhi",
        City.MUMBAI: "mumbai",
        City.CHENNAI: "chennai",
        City.BENGALURU: "bangalore",
        City.KOLKATA: "kolkata",
        City.HYDERABAD: "hyderabad",
    }

    PHONE_QUERIES = [
        "mobile phones",
        "smartphones",
        "used mobile",
        "second hand mobile",
        "android phones",
        "iphone",
        "samsung mobile",
        "xiaomi mobile",
        "oneplus mobile",
        "realme mobile",
        "vivo mobile",
        "oppo mobile",
        "poco mobile",
        "motorola mobile",
        "nokia mobile",
    ]

    @classmethod
    def build_search_url(cls, city: City, query: str = "mobile phones", page: int = 1) -> str:
        city_code = cls.CITY_CODES.get(city, city.value)
        return build_olx_search_url(city_code, query, page)

    @classmethod
    def get_all_search_urls(cls, city: City, max_pages: int = 10) -> List[str]:
        urls = []
        for query in cls.PHONE_QUERIES:
            for page in range(1, max_pages + 1):
                urls.append(cls.build_search_url(city, query, page))
        return urls