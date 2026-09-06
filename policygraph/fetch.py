import json
import os
from dataclasses import asdict, dataclass

import httpx

from policygraph import CONFIG, RAW
from policygraph.util import dump_yaml, load_yaml, sha256

MANIFEST = RAW / "manifest.yaml"
HASHES = CONFIG / "source_hashes.yaml"  # url -> sha256 of the last fetched bytes, committed for review
EXT = {"xlsx": "xlsx", "pdf": "pdf", "shapefile_zip": "zip", "json": "json", "arcgis_geojson": "geojson", "html": "html"}
PAGE = 2000
UA = {"User-Agent": "policygraph/0.1 (+httpx)"}  # insurance.ca.gov rejects the default httpx agent


@dataclass(frozen=True)
class Fetched:
    source: str
    url: str
    path: str
    sha: str
    etag: str | None = None
    last_modified: str | None = None  # HTTP Last-Modified, or the ArcGIS layer's dataLastEditDate


def conditional(prior: Fetched | None) -> dict[str, str]:
    if prior is None:
        return {}
    return {k: v for k, v in (("If-None-Match", prior.etag), ("If-Modified-Since", prior.last_modified)) if v}


def download(url: str, prior: Fetched | None) -> tuple[bytes, str | None, str | None] | None:
    """None when the server answers 304 to the prior validators, i.e. the bytes on disk are still current."""
    with httpx.Client(timeout=300, follow_redirects=True, headers=UA | conditional(prior)) as c:
        r = c.get(url)
        if r.status_code == 304:
            return None
        r.raise_for_status()
        return r.content, r.headers.get("etag"), r.headers.get("last-modified")


def download_arcgis(layer: str, prior: Fetched | None) -> tuple[bytes, str | None, str | None] | None:
    feats: list[dict] = []
    with httpx.Client(timeout=300, headers=UA) as c:
        edited = str(c.get(layer, params={"f": "json"}).raise_for_status().json()["editingInfo"]["dataLastEditDate"])
        if prior is not None and prior.last_modified == edited:
            return None
        while True:
            params = {"where": "1=1", "outFields": "*", "outSR": 3310, "resultOffset": len(feats), "resultRecordCount": PAGE}
            r = c.get(f"{layer}/query", params=params | {"f": "geojson"})
            r.raise_for_status()
            page = r.json()["features"]
            feats += page
            if len(page) < PAGE:
                return json.dumps({"type": "FeatureCollection", "features": feats}).encode(), None, edited


def expand(url: str) -> str:
    out = os.path.expandvars(url)
    if "${" in out:
        raise ValueError(f"unset env var in {url}")
    return out


def fetch_one(source: str, url: str, kind: str, prior: Fetched | None, force: bool) -> tuple[Fetched, str]:
    if prior is not None and not os.path.exists(prior.path):
        prior = None
    if prior is not None and not force and not (prior.etag or prior.last_modified):
        return prior, "cached"  # no validator to ask the server about; FORCE=1 re-downloads
    got = (
        download_arcgis(url, None if force else prior)
        if kind == "arcgis_geojson"
        else download(expand(url), None if force else prior)
    )
    if got is None:
        return prior, "unchanged"
    body, etag, last_modified = got
    sha = sha256(body)
    path = RAW / source / f"{sha}.{EXT[kind]}"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    status = "new" if prior is None else "ok" if prior.sha == sha else "changed"
    return Fetched(source, url, str(path), sha, etag, last_modified), status


def run(force: bool = False) -> None:
    cfg = load_yaml(CONFIG / "sources.yaml")["sources"]
    prior = {e["url"]: Fetched(**e) for entries in (load_yaml(MANIFEST) if MANIFEST.exists() else {}).values() for e in entries}
    pinned = {h["url"]: h["sha"] for h in load_yaml(HASHES)} if HASHES.exists() else {}
    manifest: dict[str, list[dict]] = {}
    for name, spec in cfg.items():
        urls = spec.get("urls") or ([spec["url"]] if spec.get("url") else [])
        if not urls:
            print(f"skip {name}: url not set")
            continue
        manifest[name] = []
        for u in urls:
            fetched, status = fetch_one(name, u, spec["type"], prior.get(u), force)
            manifest[name].append(asdict(fetched))
            if pinned.get(u, fetched.sha) != fetched.sha:
                status = "changed"  # differs from the committed hash: review before the next normalize
            print(f"{status:9} {name} {fetched.sha[:12]}")
    RAW.mkdir(parents=True, exist_ok=True)
    dump_yaml(MANIFEST, manifest)
    dump_yaml(HASHES, [{"url": e["url"], "sha": e["sha"]} for entries in manifest.values() for e in entries])
