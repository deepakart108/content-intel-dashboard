"""
Analysis layer: transforms raw feed data into metrics for the dashboard.
Returns structured dicts consumed by app.py.
"""

import json
import re
from collections import defaultdict, Counter
from datetime import datetime, timezone
from pathlib import Path


# ── Topic classification ───────────────────────────────────────────────────────

TOPIC_KEYWORDS: dict[str, list[str]] = {
    "AI / Automation": [
        "ai", "artificial intelligence", "automation", "machine learning",
        "chatgpt", "gpt", "llm", "autonomous", "agent", "copilot",
    ],
    "Email Marketing": [
        "email", "newsletter", "subject line", "open rate", "inbox",
        "deliverability", "drip", "sequence", "campaign",
    ],
    "SMS / Mobile": [
        "sms", "text message", "mobile", "push notification", "whatsapp",
    ],
    "CRM / Sales": [
        "crm", "sales", "pipeline", "revenue", "lead", "prospect",
        "deal", "salesforce", "hubspot crm",
    ],
    "E-commerce": [
        "ecommerce", "shopify", "cart", "checkout", "retail",
        "product", "inventory", "abandoned cart",
    ],
    "Content Marketing": [
        "content", "blog", "seo", "keyword", "organic", "social media",
        "video", "podcast", "webinar",
    ],
    "Customer Retention": [
        "retention", "churn", "loyalty", "lifecycle", "winback",
        "re-engagement", "customer success",
    ],
    "Analytics / Data": [
        "analytics", "data", "metrics", "reporting", "dashboard",
        "attribution", "roi", "measurement", "a/b test",
    ],
    "Personalization": [
        "personalization", "segmentation", "dynamic", "behaviour",
        "targeting", "audience",
    ],
    "Strategy / Growth": [
        "strategy", "growth", "marketing tips", "best practices",
        "guide", "how to", "playbook",
    ],
}


def classify_topics(title: str, summary: str, tags: list[str]) -> list[str]:
    text = f"{title} {summary} {' '.join(tags)}".lower()
    matched = []
    for topic, keywords in TOPIC_KEYWORDS.items():
        if any(kw in text for kw in keywords):
            matched.append(topic)
    return matched if matched else ["Other"]


# ── Date helpers ──────────────────────────────────────────────────────────────

def parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def month_label(dt: datetime) -> str:
    return dt.strftime("%Y-%m")


# ── Core analysis ─────────────────────────────────────────────────────────────

def run(data_path: str = "data/raw_feeds.json") -> dict:
    raw = json.loads(Path(data_path).read_text())
    feeds: dict[str, list[dict]] = raw["feeds"]
    companies = list(feeds.keys())

    # Enrich posts with topics
    all_posts = []
    for company, posts in feeds.items():
        for p in posts:
            p["topics"] = classify_topics(p["title"], p["summary"], p["tags"])
            p["dt"] = parse_iso(p["date"])
            all_posts.append(p)

    # ── 1. Publishing frequency by month ─────────────────────────────────────
    monthly: dict[str, Counter] = {c: Counter() for c in companies}
    for p in all_posts:
        if p["dt"]:
            monthly[p["company"]][month_label(p["dt"])] += 1

    all_months = sorted(
        {m for c in monthly.values() for m in c}
    )

    # ── 2. Topic distribution per company ─────────────────────────────────────
    topic_dist: dict[str, Counter] = {c: Counter() for c in companies}
    for p in all_posts:
        for t in p["topics"]:
            topic_dist[p["company"]][t] += 1

    all_topics = [t for t in TOPIC_KEYWORDS] + ["Other"]

    # ── 3. Content gap analysis ───────────────────────────────────────────────
    # For each topic: which companies cover it and which don't
    gaps: dict[str, dict] = {}
    for topic in all_topics:
        covers = [c for c in companies if topic_dist[c][topic] > 0]
        missing = [c for c in companies if topic_dist[c][topic] == 0]
        if covers and missing:
            gaps[topic] = {
                "covers": covers,
                "missing": missing,
                "total_posts": sum(topic_dist[c][topic] for c in covers),
            }

    # ── 4. Posting trend: recent 90 days vs prior 90 days ────────────────────
    now = datetime.now(timezone.utc)
    trends: dict[str, dict] = {}
    for company in companies:
        posts = [p for p in all_posts if p["company"] == company and p["dt"]]
        def days_ago(p):
            dt = p["dt"]
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return (now - dt).days
        recent = sum(1 for p in posts if 0 <= days_ago(p) <= 90)
        prior = sum(1 for p in posts if 91 <= days_ago(p) <= 180)
        trends[company] = {
            "recent_90d": recent,
            "prior_90d": prior,
            "direction": (
                "up" if recent > prior else "down" if recent < prior else "flat"
            ),
            "pct_change": (
                round((recent - prior) / max(prior, 1) * 100)
            ),
        }

    # ── 5. Synthesized insights ───────────────────────────────────────────────
    insights = _synthesize(companies, topic_dist, trends, gaps)

    return {
        "companies": companies,
        "monthly_counts": {c: dict(monthly[c]) for c in companies},
        "all_months": all_months,
        "topic_dist": {c: dict(topic_dist[c]) for c in companies},
        "all_topics": all_topics,
        "gaps": gaps,
        "trends": trends,
        "insights": insights,
        "meta": raw["meta"],
    }


def _synthesize(
    companies: list[str],
    topic_dist: dict[str, Counter],
    trends: dict[str, dict],
    gaps: dict[str, dict],
) -> list[str]:
    insights = []

    # Most prolific publisher
    totals = {c: sum(topic_dist[c].values()) for c in companies}
    top = max(totals, key=totals.get)
    insights.append(
        f"**{top}** leads in total indexed content volume ({totals[top]} posts), "
        f"suggesting a high-investment content operation."
    )

    # Biggest gaps (topics with highest total posts where some co's are absent)
    sorted_gaps = sorted(
        gaps.items(), key=lambda x: (len(x[1]["missing"]), -x[1]["total_posts"]), reverse=True
    )
    if sorted_gaps:
        topic_name, gap_data = sorted_gaps[0]
        missing_str = ", ".join(gap_data["missing"])
        insights.append(
            f"**Content gap opportunity:** The \"{topic_name}\" category is well-covered "
            f"by {', '.join(gap_data['covers'])}, but absent from {missing_str}'s indexed content — "
            f"a potential differentiation opportunity."
        )

    # Trend leaders
    up_movers = [c for c, t in trends.items() if t["direction"] == "up" and t["recent_90d"] > 0]
    down_movers = [c for c, t in trends.items() if t["direction"] == "down" and t["prior_90d"] > 0]
    if up_movers:
        insights.append(
            f"**Publishing acceleration:** {', '.join(up_movers)} increased content "
            f"output in the last 90 days vs. the prior 90 days — possible product launch or campaign push."
        )
    if down_movers:
        insights.append(
            f"**Publishing slowdown:** {', '.join(down_movers)} published less recently than the prior period. "
            f"This could signal a strategy shift or content consolidation."
        )

    # AI topic dominance
    ai_leaders = sorted(
        companies, key=lambda c: topic_dist[c].get("AI / Automation", 0), reverse=True
    )[:2]
    insights.append(
        f"**AI content race:** {' and '.join(ai_leaders)} are the heaviest publishers "
        f"on AI/Automation topics, signalling where competitive positioning is heating up."
    )

    # Unique topic focus
    for company in companies:
        top_topic = max(topic_dist[company], key=topic_dist[company].get, default=None)
        if top_topic and topic_dist[company][top_topic] > 2:
            pct = round(topic_dist[company][top_topic] / max(sum(topic_dist[company].values()), 1) * 100)
            if pct > 40:
                insights.append(
                    f"**Niche focus:** {company} concentrates {pct}% of its content on "
                    f"\"{top_topic}\" — a highly focused editorial strategy."
                )
                break

    return insights


if __name__ == "__main__":
    result = run()
    print("Companies:", result["companies"])
    print("Months available:", result["all_months"][-6:] if result["all_months"] else "none")
    print("\nTopic distribution:")
    for c in result["companies"]:
        top = sorted(result["topic_dist"][c].items(), key=lambda x: -x[1])[:3]
        print(f"  {c:20s}: {top}")
    print("\nGaps (topics with missing companies):")
    for t, g in list(result["gaps"].items())[:5]:
        print(f"  {t:30s}: missing → {g['missing']}")
    print("\nTrends:")
    for c, t in result["trends"].items():
        print(f"  {c:20s}: {t['recent_90d']} recent / {t['prior_90d']} prior → {t['direction']}")
    print("\nInsights:")
    for i, ins in enumerate(result["insights"], 1):
        print(f"  {i}. {ins[:100]}")
