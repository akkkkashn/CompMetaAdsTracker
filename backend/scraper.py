import os
import re
from datetime import datetime, timedelta

import httpx

from models import Ad

META_API_URL = "https://graph.facebook.com/v19.0/ads_archive"
META_TOKEN = os.environ.get("META_TOKEN", "")
META_COUNTRY = os.environ.get("META_COUNTRY", "SE")

# Brand name -> Facebook Page ID
BRANDS = {
    "Edblad": "202938459747673",
    "Mockberg": "1414744892080419",
}

ADS_PER_BRAND = 100

FIELDS = [
    "id",
    "page_name",
    "ad_creative_body",
    "ad_creative_link_title",
    "ad_delivery_start_time",
    "ad_delivery_stop_time",
    "ad_snapshot_url",
    "impressions",
    "spend",
    "publisher_platforms",
    "languages",
]

FORMAT_KEYWORDS = {
    "Unboxing": ["unbox", "unpacking", "haul", "what's in"],
    "GRWM/Styling": ["grwm", "get ready", "styling", "outfit", "how i style", "how to wear"],
    "Promotional": ["sale", "discount", "off", "deal", "promo", "free shipping", "limited time", "offer"],
    "Gift/Seasonal": ["gift", "christmas", "valentine", "mother's day", "father's day", "holiday", "birthday", "present"],
    "Review/Testimonial": ["review", "testimonial", "honest", "tried", "worth it", "feedback", "recommend"],
    "Educational": ["how to", "guide", "tip", "learn", "did you know", "tutorial"],
    "Aesthetic/Visual": ["aesthetic", "visual", "mood", "vibe", "minimal", "look"],
}


def classify_format(text: str) -> str:
    if not text:
        return "Brand/Awareness"
    lower = text.lower()
    for fmt, keywords in FORMAT_KEYWORDS.items():
        for kw in keywords:
            if re.search(r"\b" + re.escape(kw) + r"\b", lower):
                return fmt
    return "Brand/Awareness"


def parse_impressions(impressions_data: dict | None) -> int:
    if not impressions_data:
        return 0
    lower = int(impressions_data.get("lower_bound", 0) or 0)
    upper = int(impressions_data.get("upper_bound", 0) or 0)
    if upper == 0:
        return lower
    return (lower + upper) // 2


def parse_spend(spend_data: dict | None) -> int:
    if not spend_data:
        return 0
    lower = int(spend_data.get("lower_bound", 0) or 0)
    upper = int(spend_data.get("upper_bound", 0) or 0)
    if upper == 0:
        return lower
    return (lower + upper) // 2


def compute_run_days(start_str: str, end_str: str | None) -> int:
    if not start_str:
        return 0
    try:
        start = datetime.fromisoformat(start_str.replace("Z", "+00:00")).replace(tzinfo=None)
        if end_str:
            end = datetime.fromisoformat(end_str.replace("Z", "+00:00")).replace(tzinfo=None)
        else:
            end = datetime.utcnow()
        return max((end - start).days, 0)
    except Exception:
        return 0


async def fetch_ads_for_brand(brand: str, page_id: str) -> list[dict]:
    """Fetch up to ADS_PER_BRAND ads from Meta Ad Library for a given page ID."""
    ads_raw: list[dict] = []
    params = {
        "access_token": META_TOKEN,
        "search_page_ids": page_id,
        "ad_reached_countries": META_COUNTRY,
        "ad_type": "ALL",
        "fields": ",".join(FIELDS),
        "limit": 50,
    }

    url = META_API_URL
    async with httpx.AsyncClient(timeout=30) as client:
        while len(ads_raw) < ADS_PER_BRAND and url:
            try:
                resp = await client.get(url, params=params if url == META_API_URL else None)
                data = resp.json()

                if "error" in data:
                    print(f"[scraper] API error for {brand}: {data['error'].get('message', data['error'])}")
                    break

                batch = data.get("data", [])
                if not batch:
                    break
                ads_raw.extend(batch)
                print(f"[scraper] Fetched {len(ads_raw)} ads for {brand} so far...")
                paging = data.get("paging", {})
                url = paging.get("next")
                params = None  # next URL has params embedded
            except Exception as e:
                print(f"[scraper] Error fetching {brand}: {e}")
                break

    return ads_raw[:ADS_PER_BRAND]


def raw_to_ad(raw: dict, brand: str, now: datetime) -> Ad:
    body = raw.get("ad_creative_body", "") or ""
    title = raw.get("ad_creative_link_title", "") or ""
    hook_source = title if title else body
    hook = hook_source[:80].strip()

    start_date = raw.get("ad_delivery_start_time", "")
    end_date = raw.get("ad_delivery_stop_time")
    status = "Inactive" if end_date else "Active"

    platforms_list = raw.get("publisher_platforms", [])
    platforms = ", ".join(platforms_list) if isinstance(platforms_list, list) else str(platforms_list)

    return Ad(
        id=str(raw.get("id", "")),
        brand=brand,
        page_name=raw.get("page_name", ""),
        status=status,
        format=classify_format(body + " " + title),
        hook=hook,
        body_copy=body,
        platforms=platforms,
        start_date=start_date[:10] if start_date else "",
        end_date=end_date[:10] if end_date else None,
        run_days=compute_run_days(start_date, end_date),
        impressions_est=parse_impressions(raw.get("impressions")),
        spend_est=parse_spend(raw.get("spend")),
        snapshot_url=raw.get("ad_snapshot_url", ""),
        first_seen=now,
        last_seen=now,
        is_new=True,
        saved=False,
    )


async def pull_all_brands(session) -> dict:
    """Pull ads for all brands and upsert into the database. Returns summary."""
    from sqlmodel import select

    now = datetime.utcnow()
    cutoff = now - timedelta(hours=24)
    total_new = 0
    total_updated = 0

    for brand, page_id in BRANDS.items():
        print(f"[scraper] Pulling ads for {brand} (page_id={page_id})...")
        raw_ads = await fetch_ads_for_brand(brand, page_id)
        print(f"[scraper] Got {len(raw_ads)} ads for {brand}")

        for raw in raw_ads:
            ad_id = str(raw.get("id", ""))
            if not ad_id:
                continue

            existing = session.get(Ad, ad_id)
            new_ad = raw_to_ad(raw, brand, now)

            if existing:
                existing.status = new_ad.status
                existing.run_days = new_ad.run_days
                existing.impressions_est = new_ad.impressions_est
                existing.spend_est = new_ad.spend_est
                existing.last_seen = now
                existing.end_date = new_ad.end_date
                existing.is_new = existing.first_seen >= cutoff
                session.add(existing)
                total_updated += 1
            else:
                session.add(new_ad)
                total_new += 1

        session.commit()

    # Mark ads not seen in this pull as potentially inactive
    all_ads = session.exec(select(Ad)).all()
    for ad in all_ads:
        ad.is_new = ad.first_seen >= cutoff
    session.commit()

    return {"new": total_new, "updated": total_updated, "brands": list(BRANDS.keys())}
