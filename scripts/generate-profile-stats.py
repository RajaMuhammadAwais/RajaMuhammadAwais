#!/usr/bin/env python3
"""Generate profile statistics SVGs without a third-party PAT-backed service."""

from __future__ import annotations

import html
import json
import os
import sys
from collections import Counter
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

API_ROOT = "https://api.github.com"
USERNAME = os.environ.get("GITHUB_USERNAME", "RajaMuhammadAwais")
TOKEN = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")

if not TOKEN:
    print("::error::GITHUB_TOKEN or GH_TOKEN is required", file=sys.stderr)
    raise SystemExit(1)


def github_get(path: str) -> object:
    request = Request(
        f"{API_ROOT}{path}",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {TOKEN}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "profile-stats-generator",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except HTTPError as exc:
        print(f"::error::GitHub REST request failed with HTTP {exc.code}: {path}", file=sys.stderr)
        raise SystemExit(1) from exc
    except URLError as exc:
        print(f"::error::GitHub REST request failed: {exc.reason}", file=sys.stderr)
        raise SystemExit(1) from exc


def esc(value: object) -> str:
    return html.escape(str(value), quote=True)


def svg_header(width: int, height: int, title: str, description: str) -> list[str]:
    return [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-labelledby="title description">',
        f'<title id="title">{esc(title)}</title>',
        f'<desc id="description">{esc(description)}</desc>',
        f'<rect width="{width}" height="{height}" rx="8" fill="#1a1b27"/>',
    ]


def generate_stats_card(profile: dict, repos: list[dict]) -> str:
    username = profile["login"]
    name = profile.get("name") or username
    stars = sum(repo.get("stargazers_count", 0) for repo in repos)
    forks = sum(repo.get("forks_count", 0) for repo in repos)
    values = (
        ("Repositories", profile.get("public_repos", 0)),
        ("Followers", profile.get("followers", 0)),
        ("Stars", stars),
        ("Forks", forks),
    )
    parts = svg_header(
        576,
        170,
        f"GitHub statistics for {name}",
        f"{profile.get('public_repos', 0)} public repositories, {profile.get('followers', 0)} followers, {stars} stars, and {forks} forks.",
    )
    parts.extend(
        [
            f'<text x="25" y="34" fill="#70a5fd" font-family="Arial,Helvetica,sans-serif" font-size="19" font-weight="700">{esc(name)}</text>',
            f'<text x="25" y="56" fill="#8b949e" font-family="Arial,Helvetica,sans-serif" font-size="13">GitHub profile overview · @{esc(username)}</text>',
        ]
    )
    for index, (label, value) in enumerate(values):
        x = 25 + index * 138
        parts.append(f'<text x="{x}" y="100" fill="#f0f6fc" font-family="Arial,Helvetica,sans-serif" font-size="24" font-weight="700">{esc(value)}</text>')
        parts.append(f'<text x="{x}" y="122" fill="#8b949e" font-family="Arial,Helvetica,sans-serif" font-size="11">{esc(label)}</text>')
    parts.extend(
        [
            '<line x1="25" y1="140" x2="551" y2="140" stroke="#30363d"/>',
            '<text x="25" y="158" fill="#8b949e" font-family="Arial,Helvetica,sans-serif" font-size="10">Generated from GitHub public repository data</text>',
            "</svg>",
        ]
    )
    return "\n".join(parts) + "\n"


def generate_languages_card(language_totals: Counter[str]) -> str:
    top = language_totals.most_common(6)
    total = sum(language_totals.values()) or 1
    parts = svg_header(
        300,
        190,
        f"Most used programming languages for {USERNAME}",
        ", ".join(f"{language} {amount / total:.1%}" for language, amount in top) or "No language data available.",
    )
    parts.append('<text x="20" y="32" fill="#70a5fd" font-family="Arial,Helvetica,sans-serif" font-size="16" font-weight="700">Most Used Languages</text>')
    colors = ("#58a6ff", "#f1e05a", "#3572A5", "#89e051", "#dea584", "#563d7c")
    for index, (language, amount) in enumerate(top):
        y = 55 + index * 20
        percent = amount / total
        bar_width = max(4, round(percent * 170))
        parts.append(f'<text x="20" y="{y + 11}" fill="#f0f6fc" font-family="Arial,Helvetica,sans-serif" font-size="11">{esc(language)}</text>')
        parts.append(f'<rect x="95" y="{y}" width="170" height="11" rx="5" fill="#30363d"/>')
        parts.append(f'<rect x="95" y="{y}" width="{bar_width}" height="11" rx="5" fill="{colors[index]}"/>')
        parts.append(f'<text x="275" y="{y + 10}" text-anchor="end" fill="#8b949e" font-family="Arial,Helvetica,sans-serif" font-size="10">{percent:.0%}</text>')
    if not top:
        parts.append('<text x="20" y="70" fill="#8b949e" font-family="Arial,Helvetica,sans-serif" font-size="12">No language data available</text>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main() -> None:
    profile = github_get(f"/users/{USERNAME}")
    repos = github_get(f"/users/{USERNAME}/repos?{urlencode({'per_page': 100, 'type': 'owner', 'sort': 'updated'})}")
    if not isinstance(profile, dict) or not isinstance(repos, list):
        print("::error::Unexpected GitHub API response", file=sys.stderr)
        raise SystemExit(1)

    language_totals: Counter[str] = Counter()
    language_requests = 0
    for repo in repos:
        if repo.get("fork") or not repo.get("languages_url"):
            continue
        languages = github_get(repo["languages_url"].replace(API_ROOT, ""))
        if isinstance(languages, dict):
            language_totals.update({str(key): int(value) for key, value in languages.items()})
        language_requests += 1

    output_dir = Path(os.environ.get("OUTPUT_DIR", "stats"))
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "github-stats.svg").write_text(generate_stats_card(profile, repos), encoding="utf-8")
    (output_dir / "top-langs.svg").write_text(generate_languages_card(language_totals), encoding="utf-8")
    print(f"GitHub Stats Card generated: {(output_dir / 'github-stats.svg').stat().st_size} bytes")
    print(f"Top Languages Card generated: {(output_dir / 'top-langs.svg').stat().st_size} bytes from {language_requests} repositories")


if __name__ == "__main__":
    main()
