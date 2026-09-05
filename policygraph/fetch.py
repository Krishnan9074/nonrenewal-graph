import json
import os
from dataclasses import asdict, dataclass

import httpx

from policygraph import CONFIG, RAW
from policygraph.util import dump_yaml, load_yaml, sha256

MANIFEST = RAW / "manifest.yaml"
EXT = {"xlsx": "xlsx", "pdf": "pdf", "shapefile_zip": "zip", "json": "json", "arcgis_geojson": "geojson"}
PAGE = 2000
UA = {"User-Agent": "policygraph/0.1 (+httpx)"}  # insurance.ca.gov rejects the default httpx agent


@dataclass(frozen=True)
class Fetched:
    source: str
    url: str
    path: str
    sha: str


def download(url: str) -> bytes:
    with httpx.Client(timeout=300, follow_redirects=True, headers=UA) as c:
        r = c.get(url)
        r.raise_for_status()
        return r.content


def download_arcgis(layer: str) -> bytes:
    feats: list[dict] = []
    with httpx.Client(timeout=300, headers=UA) as c:
        while True:
            params = {"where": "1=1", "outFields": "*", "outSR": 3310, "resultOffset": len(feats), "resultRecordCount": PAGE}
            r = c.get(f"{layer}/query", params=params | {"f": "geojson"})
            r.raise_for_status()
            page = r.json()["features"]
            feats += page
            if len(page) < PAGE:
                return json.dumps({"type": "FeatureCollection", "features": feats}).encode()


def expand(url: str) -> str:
    out = os.path.expandvars(url)
    if "${" in out:
        raise ValueError(f"unset env var in {url}")
    return out


def fetch_one(source: str, url: str, kind: str) -> Fetched:
    body = download_arcgis(url) if kind == "arcgis_geojson" else download(expand(url))
    sha = sha256(body)
    path = RAW / source / f"{sha}.{EXT[kind]}"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(body)
    return Fetched(source, url, str(path), sha)


def run() -> None:
    cfg = load_yaml(CONFIG / "sources.yaml")["sources"]
    prior = load_yaml(MANIFEST) if MANIFEST.exists() else {}
    manifest: dict[str, list[dict]] = {}
    for name, spec in cfg.items():
        urls = spec.get("urls") or ([spec["url"]] if spec.get("url") else [])
        if not urls:
            print(f"skip {name}: url not set")
            continue
        manifest[name] = [asdict(fetch_one(name, u, spec["type"])) for u in urls]
        old = {e["url"]: e["sha"] for e in prior.get(name, [])}
        for e in manifest[name]:
            print(f"{'changed' if old.get(e['url']) not in (None, e['sha']) else 'ok':7} {name} {e['sha'][:12]}")
    RAW.mkdir(parents=True, exist_ok=True)
    dump_yaml(MANIFEST, manifest)
