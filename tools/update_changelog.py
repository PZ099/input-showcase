"""Render the three latest released versions into the static homepage."""

import argparse
import html
import json
import re
from pathlib import Path

LIMIT = 3
START = "<!-- CHANGELOG:START -->"
END = "<!-- CHANGELOG:END -->"
RELEASE_BASE = "https://github.com/PZ099/input-showcase/releases/tag/v"


def latest_releases(data):
    releases = []
    seen = set()
    for release in data["releases"]:
        if release.get("status") != "released":
            continue
        version = release["version"]
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            raise ValueError("Expected a released version in x.y.z format")
        if version in seen:
            raise ValueError("Duplicate released version: " + version)
        seen.add(version)
        if release["url"] != RELEASE_BASE + version:
            raise ValueError("Release link does not match its version")
        if not release["title"].strip() or not release["changes"]:
            raise ValueError("Release title and changes are required")
        if not all(isinstance(item, str) and item.strip() for item in release["changes"]):
            raise ValueError("Every release change must be nonempty text")
        releases.append(release)
    releases.sort(key=lambda item: tuple(map(int, item["version"].split("."))), reverse=True)
    if not releases:
        raise ValueError("At least one released version is required")
    return releases[:LIMIT]


def render_changelog(releases):
    esc = html.escape
    cards = []
    for index, release in enumerate(releases):
        newest = ' class="release-card is-latest"' if index == 0 else ' class="release-card"'
        badge = '<span class="release-latest">最新</span>' if index == 0 else ""
        changes = "".join("<li>" + esc(item) + "</li>" for item in release["changes"])
        cards.append(
            f'        <article{newest} aria-labelledby="release-{esc(release["version"])}">\n'
            f'          <div class="release-version"><h3 id="release-{esc(release["version"])}">{esc(release["version"])}</h3>{badge}</div>\n'
            f'          <p class="release-title">{esc(release["title"])}</p>\n'
            f'          <ul class="release-changes">{changes}</ul>\n'
            f'          <a class="release-link" href="{esc(release["url"], quote=True)}" target="_blank" rel="noopener" aria-label="查看 INPUT {esc(release["version"])} 发布详情">发布详情 <span aria-hidden="true">↗</span></a>\n'
            '        </article>'
        )
    return (
        START + '\n'
        '    <section id="changelog" class="section-width changelog-section reveal" aria-labelledby="changelog-title">\n'
        '      <div class="section-heading"><h2 id="changelog-title">更新日志</h2><p class="changelog-note">最近三个版本</p></div>\n'
        '      <div class="release-grid">\n' + "\n".join(cards) + '\n'
        '      </div>\n'
        '    </section>\n'
        '    ' + END
    )


def update_changelog(site_dir, data_path=None):
    site_dir = Path(site_dir)
    data_path = Path(data_path) if data_path else site_dir / "changelog.json"
    data = json.loads(data_path.read_text(encoding="utf-8-sig"))
    releases = latest_releases(data)
    target = site_dir / "index.html"
    source = target.read_text(encoding="utf-8-sig")
    if source.count(START) != 1 or source.count(END) != 1:
        raise ValueError("Homepage must contain exactly one changelog marker pair")
    before, rest = source.split(START, 1)
    _, after = rest.split(END, 1)
    target.write_text(before + render_changelog(releases) + after, encoding="utf-8")
    # Publish only the same three released entries visible in the HTML.
    (site_dir / "changelog.json").write_text(
        json.dumps({"releases": releases}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return [item["version"] for item in releases]


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site", default=str(Path(__file__).resolve().parents[1] / "dist"))
    parser.add_argument("--data", help="Optional release data file")
    args = parser.parse_args()
    print("Changelog: " + ", ".join(update_changelog(args.site, args.data)))
