import geopandas as gpd

from policygraph import NORMALIZED

CA_ZIPS = ("90000", "96200")  # the cartographic file is national


def run(spec: dict, files: list[dict]) -> None:
    g = gpd.read_file(f"zip://{files[0]['path']}").rename(columns={"ZCTA5CE20": "zip"})
    g[g.zip.between(*CA_ZIPS)][["zip", "geometry"]].to_crs(3310).to_parquet(NORMALIZED / "zcta.parquet")
