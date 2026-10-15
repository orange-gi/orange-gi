#!/usr/bin/env python3
"""Read official account token activity and publish only aggregate metadata."""

import argparse
from datetime import date, datetime
import json
import os
from pathlib import Path
import selectors
import subprocess
import tempfile
import time
from zoneinfo import ZoneInfo

from activity_card import compact, render_activity_card

ROOT = Path(__file__).resolve().parents[1]
SOURCE = "https://learn.chatgpt.com/docs/app-server"
SUMMARY_FIELDS = ("lifetimeTokens", "peakDailyTokens", "longestRunningTurnSec",
                  "currentStreakDays", "longestStreakDays")


def read_official_usage(timeout=45):
    """Use existing Codex sign-in through stdio; never read credential storage."""
    process = subprocess.Popen(["codex", "app-server"], stdin=subprocess.PIPE,
                               stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                               bufsize=0)
    selector = selectors.DefaultSelector()
    deadline = time.monotonic() + timeout
    buffer = b""

    def send(value):
        process.stdin.write((json.dumps(value) + "\n").encode())
        process.stdin.flush()

    def receive(request_id):
        nonlocal buffer
        while True:
            while b"\n" in buffer:
                line, buffer = buffer.split(b"\n", 1)
                try:
                    message = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    raise ValueError("Invalid app-server protocol response") from None
                if message.get("id") == request_id:
                    if "error" in message:
                        raise ValueError("Official usage request failed; check Codex sign-in")
                    if "result" not in message:
                        raise ValueError("Missing app-server result")
                    return message["result"]
            remaining = deadline - time.monotonic()
            if remaining <= 0 or not selector.select(max(0, remaining)):
                raise TimeoutError("Official usage request exceeded 45 seconds")
            chunk = os.read(process.stdout.fileno(), 65536)
            if not chunk:
                raise ValueError("Codex app-server closed before returning usage")
            buffer += chunk
            if len(buffer) > 10_000_000:
                raise ValueError("Unexpectedly large app-server response")

    try:
        selector.register(process.stdout, selectors.EVENT_READ)
        send({"method": "initialize", "id": 1, "params": {
            "clientInfo": {"name": "orange_gi_activity", "version": "1.0"},
            "capabilities": {}}})
        receive(1)
        send({"method": "initialized"})
        send({"method": "account/usage/read", "id": 2})
        return receive(2)
    finally:
        selector.close()
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        process.stdin.close()
        process.stdout.close()


def nonnegative_integer(value, label):
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError(f"Invalid nonnegative integer: {label}")
    return value


def normalize_usage(usage, year):
    if not isinstance(usage, dict) or not isinstance(usage.get("summary"), dict):
        raise ValueError("Missing official usage summary")
    buckets = usage.get("dailyUsageBuckets")
    if not isinstance(buckets, list) or not buckets:
        raise ValueError("No official daily usage buckets; keeping existing artifacts")
    days = {}
    for bucket in buckets:
        if not isinstance(bucket, dict):
            raise ValueError("Invalid daily usage bucket")
        key = bucket.get("startDate")
        if not isinstance(key, str) or date.fromisoformat(key).isoformat() != key:
            raise ValueError("Invalid official usage date")
        if date.fromisoformat(key) > datetime.now(ZoneInfo("Asia/Shanghai")).date():
            raise ValueError("Unexpected future usage date; keeping existing artifacts")
        if key in days:
            raise ValueError("Duplicate official usage date")
        days[key] = nonnegative_integer(bucket.get("tokens"), "daily tokens")
    selected = {k: v for k, v in sorted(days.items()) if date.fromisoformat(k).year == year}
    if not selected:
        raise ValueError("No daily usage buckets for requested year")
    summary = {key: nonnegative_integer(usage["summary"][key], key)
               for key in SUMMARY_FIELDS if usage["summary"].get(key) is not None}
    all_total = sum(days.values())
    lifetime = summary.get("lifetimeTokens")
    return {
        "source": {"documentation": SOURCE, "method": "account/usage/read",
                   "scope": "Official Codex token activity; Work and ordinary ChatGPT coverage are not independently established.",
                   "dateBasis": "Official startDate values unchanged; timezone unspecified.",
                   "missingDates": "No reported activity; not proof of zero usage.",
                   "afterLatestDate": "Not covered by returned daily buckets."},
        "year": year,
        "coverage": {"firstReportedDate": min(selected), "lastReportedDate": max(selected)},
        "summary": {"official": summary, "yearReportedTokens": sum(selected.values()),
                    "yearActiveDays": sum(value > 0 for value in selected.values()),
                    "allReturnedBucketsTokens": all_total,
                    "returnedBucketsMatchLifetime": None if lifetime is None else all_total == lifetime,
                    "comparisonNote": "Lifetime and returned daily buckets may have different coverage; a mismatch does not invalidate returned dates."},
        "days": [{"date": key, "tokens": value} for key, value in selected.items()],
    }


def validate_refresh(data, output_dir):
    """Reject stale or truncated responses before replacing a published year."""
    previous_path = output_dir / "codex-activity.json"
    if not previous_path.exists():
        return
    previous = json.loads(previous_path.read_text(encoding="utf-8"))
    if previous.get("year") != data["year"]:
        return
    if data["coverage"]["lastReportedDate"] < previous["coverage"]["lastReportedDate"]:
        raise ValueError("Usage response is older than the published data; keeping existing artifacts")
    old_days = {row["date"] for row in previous["days"]}
    new_days = {row["date"] for row in data["days"]}
    if not old_days.issubset(new_days):
        raise ValueError("Usage response omits previously reported dates; keeping existing artifacts")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--usage-json", type=Path, help="Read an already captured summary and daily buckets")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "assets")
    parser.add_argument("--year", type=int, default=datetime.now(ZoneInfo("Asia/Shanghai")).year)
    args = parser.parse_args()
    usage = json.loads(args.usage_json.read_text()) if args.usage_json else read_official_usage()
    data = normalize_usage(usage, args.year)
    validate_refresh(data, args.output_dir)
    summary = data["summary"]
    last = data["coverage"]["lastReportedDate"]
    svg = render_activity_card(
        title="Codex token activity", year=args.year,
        days={row["date"]: row["tokens"] for row in data["days"]}, coverage_end=last,
        subtitle=f"{compact(summary['yearReportedTokens'])} reported tokens · {summary['yearActiveDays']} active days",
        footer=f"Data through {last}",
    )
    # Validate and render everything before staging replacements. No raw response is saved.
    contents = {"codex-activity.json": json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                "codex-heatmap.svg": svg}
    args.output_dir.mkdir(parents=True, exist_ok=True)
    staged = []
    try:
        for name, content in contents.items():
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=args.output_dir,
                                             prefix=".activity-", delete=False) as output:
                staged.append((Path(output.name), args.output_dir / name))
                output.write(content)
        for temporary, target in staged:
            temporary.replace(target)
    finally:
        for temporary, _ in staged:
            temporary.unlink(missing_ok=True)
    print(f"Updated {args.year}: {summary['yearReportedTokens']:,} reported tokens; latest date {last}")


if __name__ == "__main__":
    main()
