"""
GSMArena scraper for phone specifications.
"""

import re
import asyncio
from typing import Optional, Dict, Any, List
from urllib.parse import urljoin, quote_plus
import httpx
from bs4 import BeautifulSoup

from ...utils.logging import get_logger
from ...utils.helpers import sleep_random

logger = get_logger(__name__)


class GSMArenaScraper:
    """Scrape phone specifications from GSMArena."""

    BASE_URL = "https://www.gsmarena.com"
    SEARCH_URL = "https://www.gsmarena.com/results.php3"

    def __init__(
        self,
        timeout: float = 15.0,
        max_retries: int = 3,
        min_delay: float = 1.0,
        max_delay: float = 3.0,
    ):
        self.timeout = timeout
        self.max_retries = max_retries
        self.min_delay = min_delay
        self.max_delay = max_delay
        self._client: Optional[httpx.AsyncClient] = None

    async def __aenter__(self) -> "GSMArenaScraper":
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self.timeout),
            headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            follow_redirects=True,
        )
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        if self._client:
            await self._client.aclose()
            self._client = None

    async def _get(self, url: str) -> Optional[httpx.Response]:
        if not self._client:
            return None

        for attempt in range(self.max_retries):
            try:
                await sleep_random(self.min_delay, self.max_delay)
                response = await self._client.get(url)
                response.raise_for_status()
                return response
            except httpx.HTTPError as e:
                logger.warning("Request failed", url=url, attempt=attempt + 1, error=str(e))
                if attempt == self.max_retries - 1:
                    return None
                await sleep_random(2 ** attempt, 2 ** (attempt + 1))
        return None

    async def search_phone(self, query: str) -> List[Dict[str, Any]]:
        params = {"sQuickSearch": "yes", "sName": query}
        url = f"{self.SEARCH_URL}?{httpx.QueryParams(params)}"

        response = await self._get(url)
        if not response:
            return []

        soup = BeautifulSoup(response.text, "lxml")
        results = []

        for link in soup.select(".makers a, .st-text a, .review-item a"):
            href = link.get("href", "")
            if href and "-p-" in href:
                name = link.get_text(strip=True)
                full_url = urljoin(self.BASE_URL, href)
                results.append({"name": name, "url": full_url})

        model_links = soup.select("a[href*='-p-']")
        for link in model_links[:5]:
            href = link.get("href", "")
            name = link.get_text(strip=True)
            full_url = urljoin(self.BASE_URL, href)
            if not any(r["url"] == full_url for r in results):
                results.append({"name": name, "url": full_url})

        return results[:10]

    async def get_phone_specs(self, url: str) -> Optional[Dict[str, Any]]:
        response = await self._get(url)
        if not response:
            return None

        soup = BeautifulSoup(response.text, "lxml")
        specs = self._parse_specs_page(soup)
        specs["source_url"] = url
        return specs

    def _parse_specs_page(self, soup: BeautifulSoup) -> Dict[str, Any]:
        specs = {}

        name_elem = soup.select_one("h1.specs-phone-name-title, .specs-phone-name-title")
        if name_elem:
            specs["full_name"] = name_elem.get_text(strip=True)

        for table in soup.select("table#specs-table, table.specs-table, .specs-table"):
            category = None
            for row in table.select("tr"):
                th = row.select_one("th")
                td = row.select_one("td")

                if th and th.get("scope") == "row":
                    category = th.get_text(strip=True).lower()
                    continue

                if th and td:
                    key = th.get_text(strip=True).lower()
                    value = td.get_text(strip=True)

                    if category:
                        full_key = f"{category}_{key}"
                    else:
                        full_key = key

                    specs[full_key] = value

        parsed = self._extract_key_specs(specs)
        return parsed

    def _extract_key_specs(self, raw_specs: Dict[str, str]) -> Dict[str, Any]:
        result = {}

        full_name = raw_specs.get("full_name", "")
        if full_name:
            parts = full_name.split()
            if len(parts) >= 2:
                result["brand"] = parts[0]
                result["model"] = " ".join(parts[1:])
            else:
                result["brand"] = full_name
                result["model"] = ""

        result["network_technologies"] = self._parse_list(raw_specs.get("network_technology", ""))

        launch_info = raw_specs.get("launch_announced", "") or raw_specs.get("launch_status", "")
        result["launch_year"] = self._extract_year(launch_info)
        result["launch_date"] = self._extract_date(launch_info)

        dimensions = raw_specs.get("body_dimensions", "")
        result["dimensions_mm"] = dimensions

        weight = raw_specs.get("body_weight", "")
        result["weight_grams"] = self._extract_number(weight)

        display_size = raw_specs.get("display_size", "")
        result["display_size_inches"] = self._extract_display_size(display_size)

        display_type = raw_specs.get("display_type", "")
        result["display_type"] = display_type

        result["processor"] = raw_specs.get("platform_chipset", "") or raw_specs.get("platform_cpu", "")

        memory_internal = raw_specs.get("memory_internal", "")
        ram, storage = self._parse_memory(memory_internal)
        result["ram_gb"] = ram
        result["storage_gb"] = storage

        if not ram or not storage:
            for key, val in raw_specs.items():
                if "ram" in key.lower() and not result.get("ram_gb"):
                    result["ram_gb"] = self._extract_number(val)
                if ("internal" in key.lower() or "storage" in key.lower()) and not result.get("storage_gb"):
                    result["storage_gb"] = self._extract_number(val)

        card_slot = raw_specs.get("memory_card_slot", "").lower()
        result["expandable_storage"] = "microsd" in card_slot or "yes" in card_slot

        result["rear_camera_mp"] = raw_specs.get("main_camera_single", "") or raw_specs.get("main_camera_video", "")
        result["front_camera_mp"] = raw_specs.get("selfie_camera_single", "") or raw_specs.get("selfie_camera_video", "")

        battery = raw_specs.get("battery_type", "") or raw_specs.get("battery_charging", "")
        result["battery_mah"] = self._extract_battery(battery)

        result["os_at_launch"] = raw_specs.get("platform_os", "")

        colors_text = raw_specs.get("body_colors", "") or raw_specs.get("misc_colors", "")
        result["colors"] = [c.strip() for c in colors_text.split(",") if c.strip()]

        return result

    def _parse_list(self, text: str) -> List[str]:
        if not text:
            return []
        return [item.strip() for item in re.split(r'[,;/]', text) if item.strip()]

    def _extract_year(self, text: str) -> Optional[int]:
        if not text:
            return None
        match = re.search(r'(20\d{2})', text)
        if match:
            year = int(match.group(1))
            if 2000 <= year <= 2030:
                return year
        return None

    def _extract_date(self, text: str) -> Optional[str]:
        if not text:
            return None
        patterns = [
            r'(\d{1,2})\s+(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\s+(\d{4})',
            r'(\d{4})-(\d{2})-(\d{2})',
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                try:
                    if match.group(2).isalpha():
                        day, mon, year = match.groups()
                        month = {
                            'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6,
                            'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12
                        }[mon[:3].lower()]
                        return f"{year}-{month:02d}-{int(day):02d}"
                    else:
                        return "-".join(match.groups())
                except (ValueError, KeyError):
                    continue
        return None

    def _extract_number(self, text: str) -> Optional[int]:
        if not text:
            return None
        match = re.search(r'(\d+(?:,\d{3})*(?:\.\d+)?)', text.replace(",", ""))
        if match:
            try:
                return int(float(match.group(1)))
            except ValueError:
                pass
        return None

    def _extract_display_size(self, text: str) -> Optional[float]:
        if not text:
            return None
        match = re.search(r'(\d+(?:\.\d+)?)\s*(?:inch|")', text, re.IGNORECASE)
        if match:
            try:
                return float(match.group(1))
            except ValueError:
                pass
        return None

    def _parse_memory(self, text: str) -> tuple:
        if not text:
            return None, None

        ram = None
        storage = None

        ram_match = re.search(r'(\d+)\s*GB\s*RAM', text, re.IGNORECASE)
        if ram_match:
            ram = int(ram_match.group(1))

        storage_match = re.search(r'(\d+)\s*GB\s*(?:storage|ROM)', text, re.IGNORECASE)
        if storage_match:
            storage = int(storage_match.group(1))

        if not ram or not storage:
            alt_match = re.search(r'(\d+)\s*/\s*(\d+)\s*GB', text)
            if alt_match:
                ram = ram or int(alt_match.group(1))
                storage = storage or int(alt_match.group(2))

        return ram, storage

    def _extract_battery(self, text: str) -> Optional[int]:
        if not text:
            return None
        match = re.search(r'(\d{3,5})\s*mAh', text, re.IGNORECASE)
        if match:
            try:
                return int(match.group(1))
            except ValueError:
                pass
        return None


async def search_and_get_specs(
    brand: str,
    model: str,
    variant: Optional[str] = None,
    ram_gb: Optional[int] = None,
    storage_gb: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    query_parts = [brand, model]
    if variant:
        query_parts.append(variant)
    if ram_gb:
        query_parts.append(f"{ram_gb}GB")
    if storage_gb:
        query_parts.append(f"{storage_gb}GB")

    query = " ".join(query_parts)

    async with GSMArenaScraper() as scraper:
        results = await scraper.search_phone(query)
        if not results:
            return None

        for result in results[:3]:
            specs = await scraper.get_phone_specs(result["url"])
            if specs:
                return specs

    return None