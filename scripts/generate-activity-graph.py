#!/usr/bin/env python3
"""Generate a contribution activity graph from GitHub's GraphQL API.

The public activity-graph Vercel deployment can be paused or rate-limited. This
script uses the workflow's ephemeral GITHUB_TOKEN instead, so the profile README
can serve a checked-in SVG without depending on that deployment.
"""

from __future__ import annotations

import html
import json
import os
import sys
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

GRAPHQL_ENDPOINT = "https://api.github.com/graphql"
QUERY = """
query ContributionCalendar($login: String!) {
  user(login: $login) {
    contributionsCollection {
      contributionCalendar {
        totalContributions
        weeks {
          contributionDays {
            date
            contributionCount
          }
        }
      }
    }
  }
}
"""

COLORS = ("#161b22", "#0e4429", "#006d32", "#26a641", "#39d353")
WIDTH = 1200
HEIGHT = 420
CELL = 14
GAP = 3
GRID_X = 76
GRID_Y = 118


def fail(message: str) -> None:
    print(f"::error::{message}", file=sys.stderr)
    raise SystemExit(1)


def fetch_calendar(username: str, token: str) -> dict:
    payload = json.dumps({"query": QUERY, "variables": {"login": username}}).encode()
    request = Request(
        GRAPHQL_ENDPOINT,
        data=payload,
        method="POST",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "profile-stats-generator",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            result = json.load(response)
    except HTTPError as exc:
        fail(f"GitHub GraphQL request failed with HTTP {exc.code}")
    except URLError as exc:
        fail(f"GitHub GraphQL request failed: {exc.reason}")

    if result.get("errors"):
        messages = "; ".join(error.get("message", "Unknown GraphQL error") for error in result["errors"])
        fail(f"GitHub GraphQL returned errors: {messages}")

    user = result.get("data", {}).get("user")
    if not user:
        fail(f"GitHub user not found: {username}")
    return user["contributionsCollection"]["contributionCalendar"]


def level_for_count(count: int, maximum: int) -> int:
    if count <= 0 or maximum <= 0:
        return 0
    if count >= maximum * 0.75:
        return 4
    if count >= maximum * 0.5:
        return 3
    if count >= maximum * 0.25:
        return 2
    return 1


def generate_svg(username: str, calendar: dict) -> str:
    days = [
        day
        for week in calendar["weeks"]
        for day in week["contributionDays"]
    ]
    maximum = max((day["contributionCount"] for day in days), default=0)
    safe_username = html.escape(username, quote=True)
    total = calendar["totalContributions"]
    columns = len(calendar["weeks"])
    grid_width = max(1, columns * (CELL + GAP) - GAP)

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-labelledby="title description">',
        "<title id=\"title\">GitHub contribution activity for " + safe_username + "</title>",
        f'<desc id="description">{total} contributions in the last year for {safe_username}.</desc>',
        '<rect width="1200" height="420" rx="12" fill="#0d1117"/>',
        '<text x="40" y="48" fill="#f0f6fc" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="24" font-weight="700">Contribution activity</text>',
        f'<text x="40" y="76" fill="#8b949e" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="15">{total} contributions in the last year</text>',
    ]

    weekday_labels = (("Sun", 0), ("Mon", 1), ("Wed", 3), ("Fri", 5))
    for label, row in weekday_labels:
        y = GRID_Y + row * (CELL + GAP) + CELL - 1
        parts.append(f'<text x="{GRID_X - 14}" y="{y}" text-anchor="end" fill="#8b949e" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="11">{label}</text>')

    seen_months: set[tuple[int, int]] = set()
    for column, week in enumerate(calendar["weeks"]):
        x = GRID_X + column * (CELL + GAP)
        for day in week["contributionDays"]:
            day_date = date.fromisoformat(day["date"])
            row = (day_date.weekday() + 1) % 7
            y = GRID_Y + row * (CELL + GAP)
            level = level_for_count(day["contributionCount"], maximum)
            label = f"{day['contributionCount']} contributions on {day['date']}"
            parts.append(f'<rect x="{x}" y="{y}" width="{CELL}" height="{CELL}" rx="3" fill="{COLORS[level]}"><title>{html.escape(label)}</title></rect>')
            month_key = (day_date.year, day_date.month)
            if day_date.day <= 7 and month_key not in seen_months:
                parts.append(f'<text x="{x}" y="{GRID_Y - 14}" fill="#8b949e" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="11">{day_date.strftime("%b")}</text>')
                seen_months.add(month_key)

    legend_x = GRID_X + grid_width - 180
    legend_y = 300
    parts.append(f'<text x="{legend_x - 42}" y="{legend_y + 11}" fill="#8b949e" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="11">Less</text>')
    for index, color in enumerate(COLORS):
        x = legend_x + index * (CELL + GAP)
        parts.append(f'<rect x="{x}" y="{legend_y}" width="{CELL}" height="{CELL}" rx="3" fill="{color}"/>')
    parts.append(f'<text x="{legend_x + 5 * (CELL + GAP) + 8}" y="{legend_y + 11}" fill="#8b949e" font-family="-apple-system,BlinkMacSystemFont,Segoe UI,sans-serif" font-size="11">More</text>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main() -> None:
    username = os.environ.get("GITHUB_USERNAME", "RajaMuhammadAwais")
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    output = Path(os.environ.get("OUTPUT_PATH", "stats/activity-graph.svg"))
    if not token:
        fail("GITHUB_TOKEN or GH_TOKEN is required")

    calendar = fetch_calendar(username, token)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(generate_svg(username, calendar), encoding="utf-8")
    print(f"Activity Graph generated: {output.stat().st_size} bytes")


if __name__ == "__main__":
    main()
