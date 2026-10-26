"""Validate pure-data Release models, merge the cloud catalog, publish outline previews.

Only this repository's GitHub Actions token is used, only against GitHub's API.
Nothing from a model package is imported, executed, or extracted to the filesystem.
"""
from __future__ import annotations

import argparse
import datetime as dt
import email.utils
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import stat
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile

from PIL import Image, ImageChops, ImageFilter, ImageOps

REPOSITORY = "PZ099/input-showcase"
MAX_ZIP, MAX_EXPANDED, MAX_FILE = 64 << 20, 128 << 20, 40 << 20
Image.MAX_IMAGE_PIXELS = 40_000_000
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9_-]{0,79}$")
HASH = re.compile(r"^[0-9a-fA-F]{64}$")
MODEL_ASSET = re.compile(r"^(mouse|controller)-.+\.zip$", re.I)
ACTIONS = {"lb", "rb", "lt", "rt", "ls", "rs"}


def request_bytes(request, limit, pace=None):
    """Bounded transient retries; Authorization is supplied only by the API caller."""
    for attempt in range(5):
        if pace is not None:
            pace()
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                data = response.read(limit + 1)
                require(len(data) <= limit, "Response exceeds declared limit")
                return data
        except urllib.error.HTTPError as error:
            body = error.read(8192).decode("utf-8", errors="replace").lower()
            limited = error.code == 429 or error.code == 403 and (error.headers.get("Retry-After") or "secondary rate limit" in body or "rate limit exceeded" in body)
            if attempt == 4 or not (limited or error.code in (500, 502, 503, 504)):
                raise
            delay = min(60, 5 * 2 ** attempt) if limited else 2 ** (attempt + 1)
            retry_after = error.headers.get("Retry-After")
            if retry_after:
                try:
                    delay = float(retry_after)
                except ValueError:
                    delay = (email.utils.parsedate_to_datetime(retry_after) - dt.datetime.now(dt.timezone.utc)).total_seconds()
            delay = max(1, min(300, delay))
            print(f"GitHub temporary HTTP {error.code}; retry {attempt + 1}/4 in {delay:.0f}s")
            time.sleep(delay)
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            if attempt == 4:
                raise
            time.sleep(2 ** (attempt + 1))


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def read_json(data):
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, f"Duplicate JSON key: {key}")
            result[key] = value
        return result
    return json.loads(data.decode("utf-8-sig"), object_pairs_hook=object_pairs,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError(f"Non-finite JSON: {value}")))


def safe_path(name):
    require(isinstance(name, str) and len(name) <= 240 and "\\" not in name and ":" not in name and "\x00" not in name, "Unsafe package path")
    path = PurePosixPath(name)
    require(not path.is_absolute() and name == path.as_posix() and all(part not in ("", ".", "..") for part in name.split("/")), "Package path escapes its root")
    require(path.suffix.lower() in (".json", ".png"), "Model packages may contain only JSON and PNG")
    return name


def text(value, name, limit=240):
    require(isinstance(value, str) and 0 < len(value) <= limit and value.strip() == value and not any(ord(c) < 32 for c in value), f"Invalid {name}")
    return value


def finite(value, depth=0):
    require(depth < 80, "Model data nesting exceeds limit")
    if isinstance(value, float):
        require(math.isfinite(value), "Non-finite model coordinate")
    elif isinstance(value, (dict, list)):
        require(len(value) < 500_000, "Model data collection exceeds limit")
        for child in value.values() if isinstance(value, dict) else value:
            finite(child, depth + 1)


def positive(value, name):
    require(type(value) in (float, int) and math.isfinite(value) and value > 0, f"Invalid {name}")


def png(data):
    require(data[:8] == b"\x89PNG\r\n\x1a\n", "Image is not PNG")
    with Image.open(io.BytesIO(data)) as source:
        require(source.format == "PNG" and 0 < source.width <= 8192 and 0 < source.height <= 8192 and source.width * source.height <= 40_000_000, "PNG dimensions exceed limit")
        source.load()
        return source.convert("RGBA")


def validate_package(blob, asset, renderer_version=1):
    """Returns inert parsed data and bytes, with no archive extraction or code execution."""
    require(0 < len(blob) <= MAX_ZIP and len(blob) == asset["size"], "ZIP byte count mismatch")
    digest = asset.get("digest")
    if digest:
        require(digest.lower() == "sha256:" + sha(blob), "GitHub asset digest mismatch")
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        infos = archive.infolist()
        require(1 < len(infos) <= 256 and sum(info.file_size for info in infos) <= MAX_EXPANDED, "ZIP limits exceeded")
        seen, members = set(), {}
        for info in infos:
            name = safe_path(info.filename)
            require(name.casefold() not in seen and not info.is_dir() and not info.flag_bits & 1, "Duplicate, directory, or encrypted ZIP entry")
            seen.add(name.casefold())
            mode = (info.external_attr >> 16) & 0o170000
            require(mode in (0, stat.S_IFREG) and info.file_size <= MAX_FILE, "Link/special file or oversized member")
            members[name] = archive.read(info)
    require("model.json" in members and len(members["model.json"]) <= 8 << 20, "Missing or oversized model.json")
    model = read_json(members["model.json"])
    finite(model)
    require(model.get("schemaVersion") == 1, "Unsupported model schema")
    require(type(model.get("minimumRendererVersion")) is int and 1 <= model["minimumRendererVersion"] <= renderer_version, "Model requires an unsupported renderer")
    kind, identity, revision = model.get("kind"), model.get("id"), model.get("revision")
    require(kind in ("mouse", "controller") and isinstance(identity, str) and IDENTIFIER.fullmatch(identity) and isinstance(revision, str) and IDENTIFIER.fullmatch(revision), "Invalid model identity/revision")
    require(asset["name"] == f"{kind}-{identity}-{revision}.zip", "Asset filename must be <mouse|controller>-<id>-<revision>.zip")
    metadata = model.get("metadata", {})
    for key in ("name", "brand", "familyKey", "familyName", "versionName"):
        text(metadata.get(key), "metadata." + key, 120 if key == "brand" else 240)
    require(metadata["familyKey"].startswith(kind + ":"), "Family key belongs to another device type")
    inventory = model.get("files")
    require(isinstance(inventory, list) and len(inventory) == len(members) - 1, "Model file inventory mismatch")
    listed = set()
    for item in inventory:
        name = safe_path(item["path"])
        require(name != "model.json" and name not in listed and name in members, "Invalid file inventory entry")
        listed.add(name)
        require(type(item.get("bytes")) is int and len(members[name]) == item["bytes"] and isinstance(item.get("sha256"), str) and HASH.fullmatch(item["sha256"]) and sha(members[name]) == item["sha256"].lower(), "Model file hash/size mismatch: " + name)
    require(set(members) == listed | {"model.json"}, "Unlisted package file")
    images = model.get("images")
    require(isinstance(images, dict), "Missing image descriptors")
    for name, data in members.items():
        if name.endswith(".json"):
            read_json(data)
        else:
            png(data).close()
    for image in images.values():
        if image is None:
            continue
        path = safe_path(image["path"])
        require(path in listed and path.endswith(".png") and image["bytes"] == len(members[path]) and image["sha256"].lower() == sha(members[path]), "Image descriptor hash mismatch")
        with png(members[path]) as source:
            require((source.width, source.height) == (image["width"], image["height"]), "Image descriptor dimensions mismatch")
    section = model.get(kind, {})
    profile = section.get("profile", {})
    require(profile.get("Id") == identity, "Profile identity mismatch")
    if kind == "mouse":
        require(images.get("outline") is not None, "Missing mouse outline source")
        for reference in (section.get("outline"), section.get("realistic")):
            if reference is None:
                continue
            require(reference.get("id") == identity, "Mouse reference identity mismatch")
            positive(reference.get("width"), "mouse width"); positive(reference.get("height"), "mouse height")
            require(len(reference.get("wheel", [])) == 4 and len(reference.get("wheelContour") or []) >= 3 and len(reference.get("sidePolygons", [])) == 2, "Incomplete exact mouse controls")
            for key in ("outline", "left", "right"):
                require(len(reference.get(key, [])) >= 3, "Missing mouse polygon: " + key)
        require(section.get("outline") is not None and (section.get("realistic") is None or images.get("realistic") is not None), "Mouse source/reference mismatch")
    else:
        require(images.get("front") is not None or images.get("frontRealistic") is not None, "Missing controller front")
        metrics = section.get("buttonMetrics", {})
        require(metrics.get("Id") == identity, "Controller metric identity mismatch")
        for key in ("FaceX", "FaceY", "MenuWidth", "MenuHeight"):
            positive(metrics.get(key), "metrics." + key)
        for key in ("Positions", "BackPhysicalSurfaces", "Extras", "RearExtras", "FrontExtras"):
            require(isinstance(profile.get(key), list), "Missing controller list: " + key)
        for key in ("LS", "RS", "Dpad", "Face", "Back", "Start"):
            require(isinstance(profile.get(key), dict) and all(type(profile[key].get(axis)) in (int, float) for axis in ("x", "y")), "Missing controller center: " + key)
        require(len(section.get("frontShoulders", [])) == 2 and isinstance(section.get("rearTriggers"), list), "Missing shoulder/trigger traces")
        back = section.get("backGeometry", {})
        require(back.get("id") == identity and back.get("sourceKind") in ("photo", "schematic", "official-native-vector", "none") and len(back.get("backs", [])) == len(profile["Positions"]) == len(back.get("labelCenters", [])), "Rear calibration count/source mismatch")
        feedback = section.get("feedback", {})
        for key in ("bumperActions", "rearTriggerActions", "frontSecondaryActions"):
            require(isinstance(feedback.get(key), list) and len(feedback[key]) == 2 and all(action in ACTIONS for action in feedback[key]), "Invalid physical control action")
        styles = section.get("effectiveStyles", {})
        require(styles.get("dpadKind") in ("cross", "disc", "diamond", "separated") and len(styles.get("faceLabels", [])) == 4 and len(styles.get("menuLabels", [])) == 2 and isinstance(section.get("paths"), dict), "Missing generic controller styles/paths")
    return {"model": model, "members": members, "package": {"url": asset["browser_download_url"], "sha256": sha(blob), "bytes": len(blob), "expandedBytes": sum(map(len, members.values())), "fileCount": len(members)}}


def preview_descriptor(data, asset):
    """Validate the already-published PNG itself; never infer its aspect ratio."""
    require(0 < len(data) <= 8 << 20 and len(data) == asset["size"], "Preview byte count mismatch")
    if asset.get("digest"):
        require(asset["digest"].lower() == "sha256:" + sha(data), "Preview GitHub asset digest mismatch")
    with png(data) as image:
        width, height = image.size
        require(width <= 2048 and height <= 2048, "Preview exceeds client image limits")
    return {"url": asset["browser_download_url"], "sha256": sha(data), "bytes": len(data), "width": width, "height": height}


def client_version(value):
    require(isinstance(value, str) and re.fullmatch(r"[0-9]+(?:\.[0-9]+){2,3}", value), "Invalid minimum client version")
    parts = tuple(map(int, value.split(".")))
    return parts + (0,) * (4 - len(parts))


def outline_preview(validated, rear=False):
    model, members = validated["model"], validated["members"]
    roles = ("rearRealistic", "rear") if rear else ("realistic", "outline") if model["kind"] == "mouse" else ("frontRealistic", "front")
    descriptor = next((model["images"].get(role) for role in roles if model["images"].get(role)), None)
    if descriptor is None:
        return None
    with png(members[descriptor["path"]]) as source:
        alpha = source.getchannel("A")
        require(alpha.getextrema()[0] < 32, "Source needs a transparent cutout; an opaque photograph cannot become a model preview")
        bbox = alpha.point(lambda value: 255 if value >= 32 else 0).getbbox()
        require(bbox is not None, "Empty source image")
        source = source.crop(bbox)
        if rear and model.get("controller", {}).get("effectiveStyles", {}).get("rearMirror", True):
            source = ImageOps.mirror(source)
        source.thumbnail((238, 174), Image.Resampling.LANCZOS)
        alpha = source.getchannel("A")
        shell = ImageChops.subtract(alpha.filter(ImageFilter.MaxFilter(3)), alpha.filter(ImageFilter.MinFilter(3)))
        # Decode pixels only. Remove photographic color, retaining shell and soft internal seams.
        seams = ImageOps.grayscale(source).filter(ImageFilter.FIND_EDGES).point(lambda value: max(0, min(90, (value - 24) * 2)))
        seams = ImageChops.multiply(seams, alpha)
        opacity = ImageChops.lighter(shell, ImageChops.lighter(seams, alpha.point(lambda value: value // 22)))
        lines = Image.new("RGBA", source.size, (164, 191, 217, 0)); lines.putalpha(opacity)
        result = Image.new("RGBA", (256, 192)); result.alpha_composite(lines, ((256 - lines.width) // 2, (192 - lines.height) // 2))
        stream = io.BytesIO(); result.save(stream, format="PNG", optimize=True)
        return stream.getvalue()



# These revisions changed measured control caps, not their underlying source images.
CAP_ONLY_CONTROLLERS = {"ds4", "ds5", "dse", "horiocta", "horioctapro", "probfg", "raiju3pro", "reflexpro", "revolution5pro"}


def rear_source(model):
    images = model.get("images", {})
    return images.get("rearRealistic") or images.get("rear")


def rear_web_descriptor(validated, descriptor):
    source = rear_source(validated["model"])
    require(source is not None, "Rear preview requires an actual rear source")
    return dict(descriptor, sourceSha256=source["sha256"], sourceWidth=source["width"],
                sourceHeight=source["height"], rearMirror=validated["model"].get("controller", {}).get("effectiveStyles", {}).get("rearMirror", True))


def provided_rear_preview(data, asset, validated):
    descriptor = preview_descriptor(data, asset)
    expected = outline_preview(validated, True)
    require(expected is not None, "Provided rear preview has no rear source")
    with png(data) as actual, png(expected) as reference:
        require(actual.size == reference.size and actual.tobytes() == reference.tobytes(),
                "Provided rear preview does not match the model rear source")
    return rear_web_descriptor(validated, descriptor)


def retained_rear_preview(validated, previous, website_item, renderer_version):
    model = validated["model"]
    if model["id"] not in CAP_ONLY_CONTROLLERS or not previous or not website_item.get("rear"):
        return None
    if website_item.get("cloudRevision") != previous["revision"]:
        return None
    # Verify the immutable old package before retaining any of its website artwork.
    spec = previous["package"]
    url = urllib.parse.urlsplit(spec["url"])
    prefix = f"/{REPOSITORY}/releases/download/"
    require(url.scheme == "https" and url.hostname == "github.com" and url.path.startswith(prefix) and not url.query and not url.fragment,
            "Previous package URL is outside this repository")
    tag, name = urllib.parse.unquote(url.path[len(prefix):]).split("/", 1)
    asset = {"name": name, "size": spec["bytes"], "digest": "sha256:" + spec["sha256"], "browser_download_url": spec["url"]}
    old = validate_package(fetch_asset(asset, REPOSITORY, tag), asset, renderer_version)
    before, after = rear_source(old["model"]), rear_source(model)
    if not before or not after or any(before.get(key) != after.get(key) for key in ("sha256", "bytes", "width", "height")):
        return None
    old_mirror = old["model"].get("controller", {}).get("effectiveStyles", {}).get("rearMirror", True)
    new_mirror = model.get("controller", {}).get("effectiveStyles", {}).get("rearMirror", True)
    if old_mirror != new_mirror:
        return None
    descriptor = {"url": website_item["rear"], "width": website_item.get("rearWidth"), "height": website_item.get("rearHeight"),
                  "retainedFromRevision": previous["revision"]}
    return rear_web_descriptor(validated, descriptor)


def merge_catalog(existing, updates):
    require(existing.get("schemaVersion") == 1 and isinstance(existing.get("models"), list), "Unsupported existing catalog")
    merged = {(entry["kind"], entry["id"]): entry for entry in existing["models"]}
    require(len(merged) == len(existing["models"]), "Existing catalog contains duplicate models")
    for entry in updates:
        key = entry["kind"], entry["id"]
        old = merged.get(key)
        require(not old or old["revision"] != entry["revision"] or old["package"]["sha256"] == entry["package"]["sha256"], "Revision is immutable: change revision when model package changes")
        merged[key] = entry
    result = dict(existing)
    required_client = "1.0.12"  # Current published calibration/display baseline; never lower an existing minimum.
    current_client = existing.get("minimumClientVersion", "1.0.0")
    result["minimumClientVersion"] = max((current_client, required_client), key=client_version)
    result["models"] = sorted(merged.values(), key=lambda item: (item["kind"], item["brand"], item["name"], item["id"]))
    result["counts"] = {"mouse": sum(e["kind"] == "mouse" for e in result["models"]), "controller": sum(e["kind"] == "controller" for e in result["models"]), "total": len(result["models"])}
    result["revision"] = sha(canonical(result["models"]))[:20]
    if result["revision"] != existing.get("revision"):
        result["generatedAt"] = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    return result


def merge_website(existing, catalog, previews):
    result = dict(existing)
    by_id = {(item["kind"], item["id"]): dict(item) for item in existing.get("models", [])}
    for entry in catalog["models"]:
        key = entry["kind"], entry["id"]
        item = by_id.setdefault(key, {"id": entry["id"], "kind": entry["kind"], "outline": entry["preview"]["url"], "width": entry["preview"].get("width"), "height": entry["preview"].get("height"), "atlas": None, "atlasThumb": None})
        previous_revision = item.get("cloudRevision")
        changed_revision = previous_revision != entry["revision"] and (previous_revision is not None or entry["minimumRendererVersion"] >= 2)
        available = previews.get(key, {})
        if changed_revision:
            # An atlas or rear image from another calibrated revision must never
            # appear to document the new model. First-time legacy migration below
            # deliberately preserves its existing, reviewed visual assets.
            front = available.get("front") or entry.get("preview")
            require(front and type(front.get("width")) is int and type(front.get("height")) is int, "Updated preview is missing verified PNG dimensions")
            item.update(outline=front["url"], width=front["width"], height=front["height"])
            rear = available.get("rear")
            item.update(rear=rear.get("url") if rear else None, rearWidth=rear.get("width") if rear else None, rearHeight=rear.get("height") if rear else None)
            if item.get("atlas"):
                item["previousAtlas"] = {"url": item["atlas"], "thumb": item.get("atlasThumb"), "revision": previous_revision, "width": item.get("atlasWidth"), "height": item.get("atlasHeight")}
            for field in list(item):
                if field.startswith("atlas"):
                    del item[field]
            item.update(atlas=None, atlasThumb=None)
        if available.get("front") and not changed_revision:
            front = available["front"]
            require(type(front.get("width")) is int and type(front.get("height")) is int, "Preview is missing verified PNG dimensions")
            item.update(outline=front["url"], width=front["width"], height=front["height"])
        # Normalize every old and new member, since legacy site family keys had another format.
        for field in ("name", "brand", "familyKey", "familyName"):
            item[field] = entry[field]
        for field in ("frontSchematic", "rearSchematic"):
            value = entry.get("web", {}).get(field)
            if type(value) is bool:
                item[field] = value
        item["versionLabel"] = entry["versionName"]
        item["cloudRevision"] = entry["revision"]
        if available.get("rear") and not item.get("rear"):
            item.update(rear=available["rear"]["url"], rearWidth=available["rear"]["width"], rearHeight=available["rear"]["height"])
        item["atlasAvailable"] = bool(item.get("atlas"))
        if item["atlasAvailable"]:
            item.pop("atlasUnavailableReason", None)
        else:
            item["atlasUnavailableReason"] = "此版本尚未提供图集"
        if entry["kind"] == "controller" and not item.get("rear"):
            item["rearUnavailableReason"] = "此版本尚未提供背面图"
        else:
            item.pop("rearUnavailableReason", None)
    result["models"] = sorted(by_id.values(), key=lambda item: (item["kind"], item.get("brand", ""), item["name"], item["id"]))
    result["totalModels"] = len(result["models"])
    result["atlasCount"] = sum(bool(item.get("atlas")) for item in result["models"] + result.get("keyboards", []))
    return result


class GitHub:
    def __init__(self, repository):
        require(repository.lower() == REPOSITORY.lower(), "Publisher is restricted to " + REPOSITORY)
        self.repository, self.token = repository, os.environ.get("GITHUB_TOKEN")
        self.next_upload_at = 0.0
        require(self.token, "GITHUB_TOKEN is required only in the publishing workflow")

    def pace_upload(self):
        delay = self.next_upload_at - time.monotonic()
        if delay > 0:
            time.sleep(delay)
        self.next_upload_at = time.monotonic() + 1.1  # At most 55 write attempts/minute.

    def api(self, url, data=None):
        parsed = urllib.parse.urlsplit(url)
        require(parsed.scheme == "https" and parsed.hostname in ("api.github.com", "uploads.github.com"), "Unexpected GitHub API host")
        headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "INPUT-model-publisher", "Authorization": "Bearer " + self.token}
        if data is not None:
            headers["Content-Type"] = "image/png"
        request = urllib.request.Request(url, data=data, headers=headers)
        return read_json(request_bytes(request, 16 << 20, self.pace_upload if data is not None else None))

    def release(self, tag):
        release = self.api(f"https://api.github.com/repos/{self.repository}/releases/tags/{urllib.parse.quote(tag, safe='')}")
        require(release["tag_name"] == tag and not release["draft"], "Release must be published")
        assets = []
        for page in range(1, 101):
            batch = self.api(f"https://api.github.com/repos/{self.repository}/releases/{release['id']}/assets?per_page=100&page={page}")
            assets.extend(batch)
            if len(batch) < 100:
                break
        release["assets"] = assets
        return release

    def upload_preview(self, release, name, data):
        def descriptor(asset):
            require(asset["size"] == len(data), "Existing preview asset size differs")
            if asset.get("digest"):
                require(asset["digest"].lower() == "sha256:" + sha(data), "Existing preview digest differs")
            else:
                url = urllib.parse.urlsplit(asset["browser_download_url"])
                require(url.scheme == "https" and url.hostname == "github.com" and urllib.parse.unquote(url.path).startswith(f"/{self.repository}/releases/download/"), "Preview URL is outside this repository")
                require(sha(request_bytes(asset["browser_download_url"], len(data))) == sha(data), "Existing preview bytes differ")
            return preview_descriptor(data, asset)
        old = next((asset for asset in release["assets"] if asset["name"] == name), None)
        if old:
            return descriptor(old)
        upload_url = release["upload_url"].split("{")[0] + "?" + urllib.parse.urlencode({"name": name})
        try:
            asset = self.api(upload_url, data)
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, ConnectionError, OSError):
            # A successful upload can lose its response. Recover its immutable name
            # rather than deleting/replacing an asset or creating a second copy.
            refreshed = self.release(release["tag_name"])
            recovered = next((asset for asset in refreshed["assets"] if asset["name"] == name), None)
            if recovered is None:
                raise
            release["assets"] = refreshed["assets"]
            return descriptor(recovered)
        require(asset["size"] == len(data), "Preview upload did not complete")
        release["assets"].append(asset)
        return descriptor(asset)


def fetch_asset(asset, repository, tag):
    url = urllib.parse.urlsplit(asset["browser_download_url"])
    expected = f"/{repository}/releases/download/{tag}/{asset['name']}"
    require(url.scheme == "https" and url.hostname == "github.com" and urllib.parse.unquote(url.path) == expected and not url.query, "Asset download URL is outside this release")
    require(0 < asset["size"] <= MAX_ZIP, "Asset size exceeds model limits")
    # Public downloads carry no GitHub token, including after CDN redirects.
    data = request_bytes(asset["browser_download_url"], asset["size"])
    require(len(data) == asset["size"], "Asset download size mismatch")
    return data


def atomic_write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".publishing.tmp")
    temp.write_bytes(data)
    temp.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY", REPOSITORY))
    parser.add_argument("--tag", required=True)
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--renderer-version", type=int, default=2)
    args = parser.parse_args()
    require(re.fullmatch(r"models-[A-Za-z0-9_.-]{1,100}", args.tag), "Release tag must start with models-")
    github = GitHub(args.repository)
    release = github.release(args.tag)
    assets = [asset for asset in release["assets"] if MODEL_ASSET.fullmatch(asset["name"])]
    require(assets, "No model ZIP assets. Use <mouse|controller>-<id>-<revision>.zip filenames")
    existing = read_json((args.root / "cloud/catalog.json").read_bytes())
    site_path = args.root / "dist/models.json"
    site = read_json(site_path.read_bytes()) if site_path.exists() else {"models": []}
    previous_entries = {(entry["kind"], entry["id"]): entry for entry in existing["models"]}
    website_entries = {(entry["kind"], entry["id"]): entry for entry in site.get("models", [])}
    pending, seen = [], set()
    # Validate the complete batch and any provided preview before remote writes.
    # Exact reviewed previews are immutable Release assets; reuse rather than redraw.
    for asset in assets:
        validated = validate_package(fetch_asset(asset, args.repository, args.tag), asset, args.renderer_version)
        model = validated["model"]; key = model["kind"], model["id"]
        require(key not in seen, "Release contains two versions of the same model identity")
        seen.add(key)
        entry = {"id": model["id"], "kind": model["kind"], "revision": model["revision"], "minimumRendererVersion": model["minimumRendererVersion"], "package": validated["package"]}
        entry.update({key: model["metadata"][key] for key in ("name", "brand", "familyKey", "familyName", "versionName")})
        entry["contentSha256"] = sha(canonical(model))
        if model["kind"] == "controller":
            art = model["controller"].get("artwork", {})
            web = {}
            for field in ("frontSchematic", "rearSchematic"):
                if type(art.get(field)) is bool:
                    web[field] = art[field]
            rear_kind = model["controller"].get("effectiveStyles", {}).get("rearSourceKind")
            if "rearSchematic" not in web and rear_kind in ("photo", "schematic", "official-native-vector"):
                web["rearSchematic"] = rear_kind != "photo"
            if web:
                entry["web"] = web
        preview_name = f"preview-{model['kind']}-{model['id']}-{model['revision']}.png"
        rear_name = f"preview-{model['kind']}-{model['id']}-{model['revision']}-rear.png"
        rear_assets = [item for item in release["assets"] if item["name"] == rear_name]
        require(len(rear_assets) <= 1, "Duplicate canonical rear preview asset")
        rear_descriptor = None
        if rear_assets:
            require(model["kind"] == "controller", "Only controllers may provide rear previews")
            rear_asset = rear_assets[0]
            rear_descriptor = provided_rear_preview(fetch_asset(rear_asset, args.repository, args.tag), rear_asset, validated)
        elif model["kind"] == "controller":
            rear_descriptor = retained_rear_preview(validated, previous_entries.get(key), website_entries.get(key, {}), args.renderer_version)
        if rear_descriptor:
            entry.setdefault("web", {})["rear"] = rear_descriptor
        provided = [item for item in release["assets"] if item["name"] == preview_name]
        require(len(provided) <= 1, "Duplicate canonical preview asset")
        if provided:
            asset_preview = provided[0]
            require(0 < asset_preview["size"] <= 8 << 20, "Provided preview exceeds limits")
            descriptor = preview_descriptor(fetch_asset(asset_preview, args.repository, args.tag), asset_preview)
            pending.append((entry, descriptor, None, None))
        else:
            # Older Releases and future ZIP-only updates retain automatic previews.
            pending.append((entry, None, outline_preview(validated), outline_preview(validated, True) if model["kind"] == "controller" else None))
        print("Validated", model["kind"], model["id"], model["revision"])
    # Reject immutable-revision collisions before uploading any preview.
    old = {(entry["kind"], entry["id"]): entry for entry in existing["models"]}
    for entry, _, _, _ in pending:
        previous = old.get((entry["kind"], entry["id"]))
        require(not previous or previous["revision"] != entry["revision"] or previous["package"]["sha256"] == entry["package"]["sha256"], "Changed package reused an immutable revision")
    updates, previews = [], {}
    for entry, provided, front, rear in pending:
        previews[entry["kind"], entry["id"]] = {"front": provided} if provided else {}
        if entry.get("web", {}).get("rear"):
            previews[entry["kind"], entry["id"]]["rear"] = entry["web"]["rear"]
        for side, data in (("front", front), ("rear", rear)):
            if data is None:
                continue
            name = f"preview-{entry['kind']}-{entry['id']}-{entry['revision']}-{side}-{sha(data)[:16]}.png"
            descriptor = github.upload_preview(release, name, data)
            previews[entry["kind"], entry["id"]][side] = descriptor
            if side == "rear":
                entry.setdefault("web", {})["rear"] = descriptor
        entry["preview"] = previews[entry["kind"], entry["id"]]["front"]
        updates.append(entry)
    catalog = merge_catalog(existing, updates)
    website = merge_website(site, catalog, previews)
    encoded = canonical(catalog) + b"\n"
    atomic_write(args.root / "cloud/catalog.json", encoded)
    atomic_write(args.root / "cloud/catalog.sha256", (sha(encoded) + "  catalog.json\n").encode("ascii"))
    atomic_write(site_path, canonical(website) + b"\n")
    print(f"Validated and merged {len(updates)} model(s); total {len(catalog['models'])}; catalog {catalog['revision']}")


if __name__ == "__main__":
    main()
