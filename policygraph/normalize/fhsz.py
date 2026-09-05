import geopandas as gpd
import pandas as pd

from policygraph import NORMALIZED

HAZ = {"Moderate": "moderate", "High": "high", "Very High": "very_high"}  # LRA also carries NonWildland, dropped
HAZ_COL = "FHSZ_Description"


def overlap(zcta: gpd.GeoDataFrame, fhsz: gpd.GeoDataFrame) -> pd.DataFrame:
    fhsz = fhsz.to_crs(zcta.crs).assign(haz=lambda d: d[HAZ_COL].map(HAZ)).dropna(subset=["haz"])[["haz", "geometry"]]
    inter = gpd.overlay(zcta, fhsz, how="intersection", keep_geom_type=True)
    inter["area"] = inter.area
    share = inter.groupby(["zip", "haz"])["area"].sum().unstack(fill_value=0).reindex(zcta.zip, fill_value=0)
    return share.div(zcta.set_index("zip").area, axis=0).reindex(columns=HAZ.values(), fill_value=0).reset_index()


def run(spec: dict, files: list[dict]) -> None:
    zcta = gpd.read_parquet(NORMALIZED / "zcta.parquet")
    # ArcGIS GeoJSON omits the crs member; fetch requested outSR=3310
    fhsz = gpd.GeoDataFrame(pd.concat(gpd.read_file(f["path"]).set_crs(3310, allow_override=True) for f in files))
    overlap(zcta, fhsz).to_parquet(NORMALIZED / "hazard_share.parquet", index=False)
