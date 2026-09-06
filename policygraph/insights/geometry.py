import json
from pathlib import Path

import duckdb
import geopandas as gpd

from policygraph import CONFIG, NORMALIZED
from policygraph.util import load_yaml

ZIPS = "SELECT substr(entity_id, 5) AS zip FROM entities WHERE json_extract_string(attrs,'$.county') = ?"
TOLERANCE_M = 30  # the cartographic ZCTA file is already generalized; this halves the GeoJSON for the app


def county_geojson(con: duckdb.DuckDBPyConnection, zcta: gpd.GeoDataFrame, places: dict[str, str], county: str) -> dict:
    zips = set(con.execute(ZIPS, [county]).df().zip)
    g = zcta[zcta.zip.isin(zips)].copy()
    g["geometry"] = g.geometry.simplify(TOLERANCE_M)
    g["place"] = g.zip.map(places).fillna(g.zip)
    return json.loads(g.to_crs(4326).to_json())


def write(con: duckdb.DuckDBPyConnection, out: Path, county: str = "Contra Costa") -> None:
    zcta = gpd.read_parquet(NORMALIZED / "zcta.parquet")
    out.write_text(json.dumps(county_geojson(con, zcta, load_yaml(CONFIG / "places.yaml"), county)))
