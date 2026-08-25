#!/usr/bin/env python3
"""
Signal Desk bot — pulls high-impact economic calendar events (ForexFactory's
official JSON export, linked right on forexfactory.com/calendar) and mining/
commodity news (RSS), tags each with a category + impact level using simple
keyword rules (no AI involved), and writes one merged JSON file for the
frontend to fetch directly.

Standard library only — nothing to pip install, nothing to keep secret.
Runs free forever on a GitHub Actions schedule.
"""

import json
import os
import re
import urllib.request
from datetime import datetime, timezone
from xml.etree import ElementTree

FOREX_FACTORY_URL = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"

RSS_FEEDS = [
    {"url": "https://www.mining.com/feed/", "source": "Mining.com"},
    {"url": "https://oilprice.com/rss/main", "source": "OilPrice.com"},
]

MAX_RSS_ITEMS_PER_FEED = 8
MAX_STORIES_OUTPUT = 14

CATEGORY_KEYWORDS = {
    "minerals": ["rare earth", "lithium", "cobalt", "copper", "nickel", "mine",
                 "mining", "smelter", "refinery", "critical mineral", "graphite",
                 "magnet", "cnpc", "codelco"],
    "chips": ["semiconductor", "chip", "nvidia", "tsmc", "asml", "export control",
              "chipmaker", "wafer", "lithography", "amd", "intel"],
    "geo": ["sanction", "tariff", "iran", "trade war", "embargo", "geopolit",
            "military", "conflict", "opec"],
}
DEFAULT_CATEGORY = "macro"

CRITICAL_KEYWORDS = ["export ban", "embargo", "invasion", " war ", "supply disruption",
                      "halts production", "state of emergency"]
HIGH_KEYWORDS = ["tariff", "sanction", "shutdown", "suspend", "shortage", "deficit",
                  "license revoked", "licence revoked", "strike", "surge", "plunge",
                  "record high", "record low"]
DEFAULT_IMPACT = "medium"


def classify_category(text):
    t = text.lower()
    for cat, words in CATEGORY_KEYWORDS.items():
        if any(w in t for w in words):
            return cat
    return DEFAULT_CATEGORY


def classify_impact(text):
    t = text.lower()
    if any(w in t for w in CRITICAL_KEYWORDS):
        return "critical"
    if any(w in t for w in HIGH_KEYWORDS):
        return "high"
    return DEFAULT_IMPACT


def fetch_json(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "signal-desk-bot/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8", errors="replace"))


def fetch_text(url, timeout=15):
    req = urllib.request.Request(url, headers={"User-Agent": "signal-desk-bot/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def get_calendar_events():
    events = []
    try:
        raw = fetch_json(FOREX_FACTORY_URL)
    except Exception as e:
        print(f"WARN: ForexFactory fetch failed: {e}")
        return events

    impact_map = {"high": "high", "medium": "medium"}
    for row in raw:
        impact_raw = str(row.get("impact", "")).strip().lower()
        mapped = impact_map.get(impact_raw)
        if not mapped:
            continue

        title = row.get("title") or row.get("event") or "Scheduled release"
        country = row.get("country", "")
        headline = f"{country} {title}".strip()

        forecast = row.get("forecast", "")
        previous = row.get("previous", "")
        bits = []
        if forecast:
            bits.append(f"Forecast: {forecast}")
        if previous:
            bits.append(f"Previous: {previous}")
        summary = " · ".join(bits) or "Scheduled economic release."

        events.append({
            "category": "macro",
            "impact": mapped,
            "time": row.get("date", "") or row.get("time", "") or "This week",
            "source": "ForexFactory calendar",
            "headline": headline[:120],
            "why": f"Scheduled {country} data release — historically moves {country} pairs, yields, and risk sentiment.",
            "summary": summary,
        })
    return events


def get_rss_items():
    items = []
    for feed in RSS_FEEDS:
        try:
            xml_text = fetch_text(feed["url"])
            root = ElementTree.fromstring(xml_text)
        except Exception as e:
            print(f"WARN: RSS fetch failed for {feed['url']}: {e}")
            continue

        found = 0
        for item in root.iter("item"):
            if found >= MAX_RSS_ITEMS_PER_FEED:
                break
            title_el = item.find("title")
            desc_el = item.find("description")
            date_el = item.find("pubDate")

            title = (title_el.text or "").strip() if title_el is not None else ""
            if not title:
                continue

            desc = re.sub("<[^<]+?>", "", (desc_el.text or "")) if desc_el is not None else ""
            desc = desc.strip()[:220]
            combined = f"{title} {desc}"

            items.append({
                "category": classify_category(combined),
                "impact": classify_impact(combined),
                "time": (date_el.text or "").strip() if date_el is not None else "",
                "source": feed["source"],
                "headline": title[:120],
                "why": "Flagged by keyword match on the headline/summary — check the source for full context.",
                "summary": desc or "No summary available — see source link.",
            })
            found += 1
    return items


def main():
    calendar_events = get_calendar_events()
    rss_items = get_rss_items()

    impact_rank = {"critical": 3, "high": 2, "medium": 1}
    all_items = calendar_events + rss_items
    all_items.sort(key=lambda x: impact_rank.get(x["impact"], 0), reverse=True)
    all_items = all_items[:MAX_STORIES_OUTPUT]

    output = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stories": all_items,
    }

    os.makedirs("data", exist_ok=True)
    with open("data/live.json", "w", encoding="utf-8") as f:
        json.dump(output, f, indent=2, ensure_ascii=False)

    print(f"Wrote {len(all_items)} items to data/live.json")


if __name__ == "__main__":
    main()
