"""
Content ingestion for competitive intelligence dashboard.
Uses RSS where available, falls back to HTML scraping.
Output: data/raw_feeds.json
"""

import feedparser
import requests
import json
import time
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

RSS_FEEDS = {
    "HubSpot": "https://blog.hubspot.com/marketing/rss.xml",
    "Salesforce": "https://www.salesforce.com/blog/feed/",
}


# ── RSS ───────────────────────────────────────────────────────────────────────

def _parse_date(entry) -> str | None:
    for attr in ("published_parsed", "updated_parsed", "created_parsed"):
        t = getattr(entry, attr, None)
        if t:
            try:
                return datetime(*t[:6], tzinfo=timezone.utc).isoformat()
            except Exception:
                pass
    return None


def fetch_rss(company: str, url: str) -> list[dict]:
    print(f"  [RSS] {company}")
    d = feedparser.parse(url)
    return [
        {
            "company": company,
            "title": e.get("title", "").strip(),
            "url": e.get("link", ""),
            "date": _parse_date(e),
            "summary": e.get("summary", "")[:400],
            "tags": [t.get("term", "") for t in getattr(e, "tags", [])],
        }
        for e in d.entries
    ]


# ── HTML scraping ─────────────────────────────────────────────────────────────

def _get_soup(url: str) -> BeautifulSoup | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
        return BeautifulSoup(r.text, "html.parser")
    except Exception as e:
        print(f"    HTTP error: {e}")
        return None


def _try_parse_date(raw: str) -> str | None:
    if not raw:
        return None
    raw = raw.strip()
    m = re.match(r"(\d{4}-\d{2}-\d{2})", raw)
    if m:
        try:
            return datetime.strptime(m.group(1), "%Y-%m-%d").replace(
                tzinfo=timezone.utc
            ).isoformat()
        except ValueError:
            pass
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%d %B %Y", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw[: len(fmt) + 5], fmt).replace(
                tzinfo=timezone.utc
            ).isoformat()
        except ValueError:
            pass
    return None


def scrape_klaviyo() -> list[dict]:
    """Klaviyo: scrape blog index + several category pages for breadth."""
    print("  [SCRAPE] Klaviyo")
    base = "https://www.klaviyo.com"
    categories = [
        "/blog/category/all-articles",
        "/blog/category/email-marketing",
        "/blog/category/marketing-campaign-strategy",
        "/blog/category/customer-acquisition",
        "/blog/category/artificial-intelligence",
    ]
    seen, posts = set(), []
    for cat_path in categories:
        soup = _get_soup(base + cat_path)
        if not soup:
            continue
        for a in soup.select("a[href*='/blog/']"):
            href = a["href"]
            if "/blog/category" in href:
                continue
            full_url = urljoin(base, href)
            if full_url in seen:
                continue
            title = a.get_text(strip=True)
            # Skip nav/menu links
            if len(title) < 15:
                continue
            seen.add(full_url)
            # Date from URL slug pattern if present e.g. /blog/2024-..
            date_match = re.search(r"(\d{4})-(\d{2})-(\d{2})", href)
            date_str = None
            if date_match:
                date_str = f"{date_match.group(1)}-{date_match.group(2)}-{date_match.group(3)}T00:00:00+00:00"
            # Infer topic tags from category path
            posts.append({
                "company": "Klaviyo",
                "title": title,
                "url": full_url,
                "date": date_str,
                "summary": "",
                "tags": [],
            })
        time.sleep(0.4)
    return posts


def scrape_activecampaign() -> list[dict]:
    """ActiveCampaign: scrape blog listing pages."""
    print("  [SCRAPE] ActiveCampaign")
    base = "https://www.activecampaign.com"
    pages = ["/blog/", "/blog/?page=2", "/blog/?page=3"]
    seen, posts = set(), []
    for page in pages:
        soup = _get_soup(base + page)
        if not soup:
            continue
        for article in soup.select("article"):
            title_el = article.select_one("h2, h3, h1")
            if not title_el:
                continue
            title = title_el.get_text(strip=True)
            if len(title) < 10:
                continue
            # Post link is not the category link — find the deepest /blog/slug link
            post_url = ""
            for a in article.select("a[href]"):
                href = a["href"]
                if "/blog/" in href and "/blog/category/" not in href:
                    post_url = href if href.startswith("http") else base + href
                    break
            if not post_url:
                continue
            if post_url in seen:
                continue
            seen.add(post_url)
            time_el = article.select_one("time")
            date_str = None
            if time_el:
                date_str = _try_parse_date(
                    time_el.get("datetime") or time_el.get_text(strip=True)
                )
            cats = [
                a.get_text(strip=True)
                for a in article.select("a[href*='/category/']")
            ]
            summary_el = article.select_one("p")
            posts.append({
                "company": "ActiveCampaign",
                "title": title,
                "url": post_url,
                "date": date_str,
                "summary": summary_el.get_text(strip=True)[:300] if summary_el else "",
                "tags": cats,
            })
        time.sleep(0.5)
    return posts


def scrape_mailchimp() -> list[dict]:
    """Mailchimp: scrape resources hub."""
    print("  [SCRAPE] Mailchimp")
    base = "https://mailchimp.com"
    pages = ["/resources/", "/resources/?page=2", "/resources/?page=3"]
    seen, posts = set(), []
    for page in pages:
        soup = _get_soup(base + page)
        if not soup:
            continue
        # cardItem links contain title text
        for card in soup.select("a[class*='cardItem'], a[class*='card-item']"):
            href = card.get("href", "")
            full_url = urljoin(base, href)
            if full_url in seen:
                continue
            title_el = card.select_one("h2,h3,h4,[class*='title'],[class*='heading']")
            title = (
                title_el.get_text(strip=True) if title_el else card.get_text(strip=True)
            )
            title = re.sub(r"\s+", " ", title).strip()
            if len(title) < 10:
                continue
            seen.add(full_url)
            # No dates in Mailchimp resource hub HTML
            posts.append({
                "company": "Mailchimp",
                "title": title,
                "url": full_url,
                "date": None,
                "summary": "",
                "tags": [],
            })
        time.sleep(0.5)
    return posts


# ── Main ──────────────────────────────────────────────────────────────────────

def ingest_all() -> dict:
    Path("data").mkdir(exist_ok=True)
    results = {}

    for company, url in RSS_FEEDS.items():
        results[company] = fetch_rss(company, url)
        print(f"    → {len(results[company])} posts")
        time.sleep(0.3)

    results["Klaviyo"] = scrape_klaviyo()
    print(f"    → {len(results['Klaviyo'])} posts")

    results["ActiveCampaign"] = scrape_activecampaign()
    print(f"    → {len(results['ActiveCampaign'])} posts")

    results["Mailchimp"] = scrape_mailchimp()
    print(f"    → {len(results['Mailchimp'])} posts")

    meta = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "companies": list(results.keys()),
        "total_posts": sum(len(v) for v in results.values()),
    }
    output = {"meta": meta, "feeds": results}
    Path("data/raw_feeds.json").write_text(
        json.dumps(output, indent=2, ensure_ascii=False)
    )
    print(f"\nSaved {meta['total_posts']} posts → data/raw_feeds.json")
    return output


if __name__ == "__main__":
    print("=== Ingesting content ===\n")
    data = ingest_all()
    print("\nSummary:")
    for company, posts in data["feeds"].items():
        dated = sum(1 for p in posts if p["date"])
        print(f"  {company:20s}: {len(posts):3d} posts  ({dated} with dates)")
