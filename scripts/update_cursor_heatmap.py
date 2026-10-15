#!/usr/bin/env python3
"""Render the public Cursor activity calendar without credentials or dependencies."""

import argparse
import calendar
from datetime import date, datetime, timedelta
from html import escape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

PROFILE_URL = "https://cursor.com/@insterest"
ROOT = Path(__file__).resolve().parents[1]
LABEL = re.compile(
    r"(?:(\d+(?:\.\d+)?)([KMB]?) tokens on )?"
    r"([A-Za-z]{3}) (\d{1,2}), (\d{4})"
)
MONTHS = {name: index for index, name in enumerate(calendar.month_abbr) if name}
MULTIPLIERS = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}


class ActivityParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.days = {}

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if attrs.get("data-tooltip-id") != "profile-activity-tooltip":
            return
        label = attrs.get("data-tooltip-content", "")
        match = LABEL.fullmatch(label)
        if not match:
            raise ValueError(f"Unrecognized activity label: {label!r}")
        number, unit, month, day, year = match.groups()
        day = date(int(year), MONTHS[month], int(day))
        if day in self.days:
            raise ValueError(f"Duplicate activity date: {day}")
        tokens = round(float(number) * MULTIPLIERS[unit]) if number else 0
        self.days[day] = {"date": day.isoformat(), "tokensApprox": tokens, "label": label}


def fetch_days(as_of):
    request = Request(PROFILE_URL, headers={"User-Agent": "orange-gi-cursor-heatmap/1.0"})
    with urlopen(request, timeout=45) as response:
        if response.status != 200 or response.url.rstrip("/") != PROFILE_URL:
            raise ValueError("Cursor did not return the public profile")
        source = response.read(5_000_001)
    if len(source) > 5_000_000:
        raise ValueError("Unexpectedly large profile response")
    parser = ActivityParser()
    parser.feed(source.decode("utf-8"))
    start, end = date(as_of.year, 1, 1), date(as_of.year + 1, 1, 1)
    expected = {start + timedelta(days=i) for i in range((end - start).days)}
    if set(parser.days) != expected:
        raise ValueError("Missing or unexpected calendar dates; keeping the previous heatmap")
    if any(row["tokensApprox"] for day, row in parser.days.items() if day > as_of):
        raise ValueError("Unexpected usage on future dates")
    return [parser.days[day] for day in sorted(expected) if day <= as_of]


def summarize(days):
    longest = run = 0
    for day in days:
        run = run + 1 if day["tokensApprox"] else 0
        longest = max(longest, run)
    return {
        "tokensApprox": sum(day["tokensApprox"] for day in days),
        "activeDays": sum(day["tokensApprox"] > 0 for day in days),
        "longestStreakDays": longest,
    }


def compact(number):
    for unit, divisor in (("B", 1_000_000_000), ("M", 1_000_000), ("K", 1_000)):
        if number >= divisor:
            return f"{number / divisor:.2f}".rstrip("0").rstrip(".") + unit
    return str(number)


def render_svg(data):
    year = data["year"]
    as_of = date.fromisoformat(data["asOf"])
    start, end = date(year, 1, 1), date(year + 1, 1, 1)
    grid_start = start - timedelta(days=(start.weekday() + 1) % 7)
    days = {row["date"]: row for row in data["days"]}
    peak = max((row["tokensApprox"] for row in data["days"]), default=0)
    summary = data["summary"]
    total = compact(summary["tokensApprox"])
    elements = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="860" height="260" viewBox="0 0 860 260" role="img" aria-labelledby="title desc">',
        f'<title id="title">Cursor activity · {year} · @insterest</title>',
        f'<desc id="desc">Approximately {total} tokens across {summary["activeDays"]} active days. Longest streak: {summary["longestStreakDays"]} days. January 1 through {as_of.isoformat()}. Daily values are rounded by Cursor.</desc>',
        '<style>text{font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Arial,sans-serif;fill:#1f2328}.muted{fill:#656d76}.frame{fill:#fff;stroke:#d1d9e0}.empty{fill:#ebedf0}.future{fill:#f6f8fa}.l1{fill:#f5c4a5}.l2{fill:#eea075}.l3{fill:#e7814e}.l4{fill:#dc602f}@media(prefers-color-scheme:dark){text{fill:#e6edf3}.muted{fill:#9198a1}.frame{fill:#0d1117;stroke:#30363d}.empty{fill:#21262d}.future{fill:#161b22}.l1{fill:#613826}.l2{fill:#985033}.l3{fill:#ca683e}.l4{fill:#f28b54}}</style>',
        '<rect class="frame" x="0.5" y="0.5" width="859" height="259" rx="12"/>',
        '<circle cx="29" cy="32" r="5" fill="#e7814e"/>',
        '<text x="44" y="38" font-size="20" font-weight="600">Cursor activity</text>',
        f'<text class="muted" x="832" y="37" text-anchor="end" font-size="13">@insterest · {year}</text>',
        f'<text x="24" y="67" font-size="14">≈ {total} tokens<tspan class="muted">  ·  {summary["activeDays"]} active days  ·  {summary["longestStreakDays"]}-day longest streak</tspan></text>',
    ]
    for month in range(1, 13):
        week = (date(year, month, 1) - grid_start).days // 7
        elements.append(f'<text class="muted" x="{72 + week * 14}" y="100" font-size="11">{calendar.month_abbr[month]}</text>')
    for row, label in ((1, "Mon"), (3, "Wed"), (5, "Fri")):
        elements.append(f'<text class="muted" x="24" y="{121 + row * 14}" font-size="10">{label}</text>')
    for offset in range((end - start).days):
        day = start + timedelta(days=offset)
        cell = days.get(day.isoformat())
        tokens = cell["tokensApprox"] if cell else 0
        level = min(4, 1 + int(tokens / peak * 4)) if tokens and peak else 0
        css_class = "future" if day > as_of else f"l{level}" if level else "empty"
        label = cell["label"] if cell else day.isoformat() + " (future)"
        delta = (day - grid_start).days
        elements.append(f'<circle class="{css_class}" cx="{72 + delta // 7 * 14}" cy="{117 + delta % 7 * 14}" r="4.8"><title>{escape(label)}</title></circle>')
    elements.append(f'<text class="muted" x="24" y="238" font-size="11">Updated {as_of.isoformat()} · Approximate tokens from public Cursor activity</text>')
    elements.append('<text class="muted" x="688" y="238" font-size="10">Less</text>')
    for index, css_class in enumerate(("empty", "l1", "l2", "l3", "l4")):
        elements.append(f'<circle class="{css_class}" cx="{724 + index * 14}" cy="234" r="4.8"/>')
    elements.extend(['<text class="muted" x="796" y="238" font-size="10">More</text>', '</svg>'])
    return "\n".join(elements) + "\n"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--as-of", type=date.fromisoformat, default=datetime.now(ZoneInfo("Asia/Shanghai")).date())
    args = parser.parse_args()
    days = fetch_days(args.as_of)
    summary = summarize(days)
    data = {
        "source": PROFILE_URL,
        "year": args.as_of.year,
        "asOf": args.as_of.isoformat(),
        "note": "Approximate totals summed from Cursor's rounded daily tooltip values; not billing data.",
        "summary": summary,
        "days": days,
    }
    svg = render_svg(data)
    output = ROOT / "assets"
    output.mkdir(exist_ok=True)
    # Fetch, parse, validate and render before replacing either existing artifact.
    for name, content in (("cursor-activity.json", json.dumps(data, ensure_ascii=False, indent=2) + "\n"), ("cursor-heatmap.svg", svg)):
        temporary = output / (name + ".tmp")
        temporary.write_text(content, encoding="utf-8")
        temporary.replace(output / name)
    print(f"Updated {args.as_of}: ≈ {compact(summary['tokensApprox'])} tokens, {summary['activeDays']} active days")


if __name__ == "__main__":
    main()
