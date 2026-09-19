"""Campus imagery.

Order of preference:
  1. Whatever the provided database already holds.
  2. Wikipedia's page image (reliable for the building front).
  3. Wikimedia Commons search, scoped per slot: exteriors, interiors, halls of
     residence.
  4. Openverse, as a last resort for the interior and housing shots.

Anything found is written back to the University row with its attribution, so
each school is only looked up once. If the network is unavailable the frontend
draws a generated placeholder — the page never shows a broken image.
"""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote

import requests
from django.conf import settings
from django.utils import timezone

log = logging.getLogger(__name__)

SLOT_QUERIES = {
    "front": ["{name} building", "{name} campus {city}", "{name} main entrance"],
    "inside": ["{name} library interior", "{name} lecture hall", "{name} interior"],
    "housing": ["{name} student residence", "{name} student housing", "{city} student dormitory"],
}

# Commons returns a lot of logos, coats of arms and scanned documents; those make
# for a poor gallery, so they're filtered out by filename.
REJECT_TOKENS = (
    "logo", "coat_of_arms", "coa_", "seal", "wappen", "signature", "map_of",
    "locator", "flag", ".svg", ".pdf", "diagram", "chart", "graph",
)


def _session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": settings.HTTP_USER_AGENT})
    return session


def _acceptable(title: str) -> bool:
    lowered = title.lower()
    return not any(token in lowered for token in REJECT_TOKENS)


def _wikipedia_page_image(session: requests.Session, name: str) -> dict | None:
    try:
        response = session.get(
            f"https://en.wikipedia.org/api/rest_v1/page/summary/{quote(name.replace(' ', '_'))}",
            timeout=settings.IMAGE_LOOKUP_TIMEOUT,
        )
        if response.status_code != 200:
            return None
        data = response.json()
        source = (data.get("originalimage") or data.get("thumbnail") or {}).get("source")
        if not source or not _acceptable(source):
            return None
        return {
            "url": source,
            "credit": "Wikipedia",
            "source_page": (data.get("content_urls", {}).get("desktop", {}) or {}).get("page", ""),
        }
    except (requests.RequestException, ValueError) as exc:
        log.debug("Wikipedia lookup failed for %s: %s", name, exc)
        return None


def _commons_search(session: requests.Session, query: str) -> dict | None:
    try:
        response = session.get(
            "https://commons.wikimedia.org/w/api.php",
            params={
                "action": "query",
                "format": "json",
                "generator": "search",
                "gsrsearch": f"{query} filetype:bitmap",
                "gsrnamespace": "6",
                "gsrlimit": "8",
                "prop": "imageinfo",
                "iiprop": "url|extmetadata",
                "iiurlwidth": "1280",
            },
            timeout=settings.IMAGE_LOOKUP_TIMEOUT,
        )
        if response.status_code != 200:
            return None
        pages = (response.json().get("query") or {}).get("pages") or {}
        for page in pages.values():
            title = page.get("title", "")
            if not _acceptable(title):
                continue
            info = (page.get("imageinfo") or [{}])[0]
            url = info.get("thumburl") or info.get("url")
            if not url:
                continue
            meta = info.get("extmetadata") or {}
            return {
                "url": url,
                "credit": _strip_html(meta.get("Artist", {}).get("value", "Wikimedia Commons")),
                "licence": _strip_html(meta.get("LicenseShortName", {}).get("value", "")),
                "source_page": info.get("descriptionurl", ""),
            }
    except (requests.RequestException, ValueError) as exc:
        log.debug("Commons lookup failed for %s: %s", query, exc)
    return None


def _openverse_search(session: requests.Session, query: str) -> dict | None:
    try:
        response = session.get(
            "https://api.openverse.org/v1/images/",
            params={"q": query, "page_size": 5, "mature": "false"},
            timeout=settings.IMAGE_LOOKUP_TIMEOUT,
        )
        if response.status_code != 200:
            return None
        for item in response.json().get("results", []):
            url = item.get("url")
            if url and _acceptable(url):
                return {
                    "url": url,
                    "credit": item.get("creator") or item.get("source") or "Openverse",
                    "licence": item.get("license", ""),
                    "source_page": item.get("foreign_landing_url", ""),
                }
    except (requests.RequestException, ValueError) as exc:
        log.debug("Openverse lookup failed for %s: %s", query, exc)
    return None


def _strip_html(value: str) -> str:
    import re

    return re.sub(r"<[^>]+>", "", value or "").strip()[:160]


def resolve_slot(session: requests.Session, university, slot: str) -> dict | None:
    name, city = university.name, university.city or university.country

    if slot == "front":
        found = _wikipedia_page_image(session, name)
        if found:
            return found

    for template in SLOT_QUERIES[slot]:
        query = template.format(name=name, city=city)
        found = _commons_search(session, query)
        if found:
            return found

    if slot in {"inside", "housing"}:
        for template in SLOT_QUERIES[slot][:2]:
            found = _openverse_search(session, template.format(name=name, city=city))
            if found:
                return found
    return None


def ensure_images(university, force: bool = False) -> dict:
    """Fill in any missing image slots for one university and persist them."""
    slots = ["front", "inside", "housing"] if force else university.missing_image_slots()
    if not slots or not settings.IMAGE_LOOKUP_ENABLED:
        return _payload(university)

    session = _session()
    credits = dict(university.image_credits or {})
    changed = False

    for slot in slots:
        found = resolve_slot(session, university, slot)
        if not found:
            continue
        setattr(university, f"image_{slot}", found["url"][:700])
        credits[slot] = {k: v for k, v in found.items() if k != "url"}
        changed = True

    if changed:
        university.image_credits = credits
        university.images_fetched_at = timezone.now()
        university.save(
            update_fields=[
                "image_front", "image_inside", "image_housing",
                "image_credits", "images_fetched_at", "updated_at",
            ]
        )
        log.info("Cached %s image(s) for %s.", len(slots), university.name)
    return _payload(university)


def ensure_images_bulk(universities: list, force: bool = False) -> None:
    """Four universities, looked up in parallel — the difference between a 12
    second wait and a 3 second one."""
    if not settings.IMAGE_LOOKUP_ENABLED:
        return
    pending = [u for u in universities if force or u.missing_image_slots()]
    if not pending:
        return
    with ThreadPoolExecutor(max_workers=min(4, len(pending))) as pool:
        list(pool.map(lambda u: _safe_ensure(u, force), pending))


def _safe_ensure(university, force: bool) -> None:
    try:
        ensure_images(university, force=force)
    except Exception as exc:  # never let a photo lookup break a recommendation
        log.warning("Image lookup failed for %s: %s", university.name, exc)


def _payload(university) -> dict:
    return {
        "front": university.image_front or "",
        "inside": university.image_inside or "",
        "housing": university.image_housing or "",
        "credits": university.image_credits or {},
    }


# ---------------------------------------------------------------------------
# Campus map
# ---------------------------------------------------------------------------
def campus_map(university) -> dict:
    """An embeddable OpenStreetMap view of the campus, plus links out.

    OSM needs no API key, which matters when the judges run this on their own
    machine. `official_url` is whatever campus map the provided database holds.
    """
    lat, lng = university.latitude, university.longitude
    if lat is None or lng is None:
        return {
            "available": False,
            "official_url": university.campus_map_url or "",
            "search_url": f"https://www.openstreetmap.org/search?query={quote(university.name)}",
        }
    d = 0.008  # ~900m box: a campus, not a country
    bbox = f"{lng - d},{lat - d},{lng + d},{lat + d}"
    return {
        "available": True,
        "lat": lat,
        "lng": lng,
        "embed_url": (
            f"https://www.openstreetmap.org/export/embed.html?bbox={bbox}"
            f"&layer=mapnik&marker={lat},{lng}"
        ),
        "full_url": f"https://www.openstreetmap.org/?mlat={lat}&mlon={lng}#map=16/{lat}/{lng}",
        "directions_url": f"https://www.google.com/maps/search/?api=1&query={lat},{lng}",
        "official_url": university.campus_map_url or "",
    }
