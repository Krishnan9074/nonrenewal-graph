import geopandas as gpd
import pandas as pd
import pytest
from shapely.geometry import box

from policygraph.normalize import acs, cdi_fair_plan, cdi_nonrenewal, fhsz

FAIR_TEXT = """Policy Growth by Fiscal Year (Residential Line)
ZIP Code Year over Year Growth Number of Policies
Total 38% 621,234 40% 449,833 21% 320,572 12% 265,909 236,515
94549 91% 1,773 265% 927 76% 254 26% 144 114
94720 0% 1 0% 1 0% - 0% - -
9/30/2025 9/30/2024 9/30/2023 9/30/2022 9/30/2021
"""


def test_fair_plan_rows_and_missing():
    df = cdi_fair_plan.parse(FAIR_TEXT).set_index(["zip", "year"]).fair_policies
    assert df[("94549", 2025)] == 1773 and df[("94549", 2021)] == 114
    assert ("94720", 2023) not in df.index and df[("94720", 2025)] == 1


def test_fair_plan_bad_row_fails():
    with pytest.raises(ValueError):
        cdi_fair_plan.parse(FAIR_TEXT + "94500 1% 2\n")


def test_nonrenewal_split_release():
    raw = pd.DataFrame(
        [["Contra Costa", "94505", "2015", "881", "4357", "618", "80"]],
        columns=["County", "ZIP Code", "Year", "New", "Renewed", "Insured-Initiated Nonrenewed", "Insurer-Initiated Nonrenewed"],
    )
    row = cdi_nonrenewal.parse(raw, "2015-2021").iloc[0]
    assert row.nonrenewed == 698 and row.policies == 5936 and row.release == "2015-2021"


def test_nonrenewal_total_release_has_null_split():
    raw = pd.DataFrame(
        [["   ", "90000", "2020", "1", "3", "0"]], columns=["County", "ZIP Code", "Year", "New", "Renewed", "Non-Renewed"]
    )
    row = cdi_nonrenewal.parse(raw, "2020-2023").iloc[0]
    assert pd.isna(row.nonrenewed_insurer) and pd.isna(row.county) and row.nonrenewed == 0


def test_nonrenewal_missing_column_fails():
    with pytest.raises(ValueError):
        cdi_nonrenewal.parse(pd.DataFrame(columns=["ZIP Code", "Year"]), "x")


def test_acs_sentinel_to_nan():
    raw = pd.DataFrame(
        [["B25077_001E", "B25035_001E", "B19013_001E", "zip code tabulation area"], ["-666666666", "1980", "50000", "94563"]]
    )
    row = acs.parse(raw).iloc[0]
    assert pd.isna(row.median_home_value) and row.median_income == 50000 and row.zip == "94563"


def test_hazard_overlap_shares():
    zcta = gpd.GeoDataFrame({"zip": ["94563", "94509"]}, geometry=[box(0, 0, 10, 10), box(20, 0, 30, 10)], crs=3310)
    haz = gpd.GeoDataFrame(
        {"FHSZ_Description": ["Very High", "NonWildland"]}, geometry=[box(0, 0, 5, 10), box(5, 0, 10, 10)], crs=3310
    )
    out = fhsz.overlap(zcta, haz).set_index("zip")
    assert out.loc["94563"].very_high == pytest.approx(0.5) and out.loc["94563"].high == 0
    assert out.loc["94509"].tolist() == [0, 0, 0]


def test_fair_plan_layout_follows_footer():
    six = FAIR_TEXT.replace(
        "94549 91% 1,773 265% 927 76% 254 26% 144 114", "94549 5% 2,000 91% 1,773 265% 927 76% 254 26% 144 114"
    )
    six = six.replace("9/30/2025 9/30/2024", "9/30/2026 9/30/2025 9/30/2024")
    six = six.replace("94720 0% 1 0% 1 0% - 0% - -", "94720 0% 1 0% 1 0% 1 0% - 0% - -").replace(
        "Total 38%", "Total 1% 700,000 38%"
    )
    df = cdi_fair_plan.parse(six).set_index(["zip", "year"]).fair_policies
    assert df[("94549", 2026)] == 2000 and df[("94549", 2021)] == 114 and ("94720", 2022) not in df.index


def test_html_text_and_dates():
    from policygraph.normalize.documents import published_at
    from policygraph.normalize.html_text import to_text

    html = (
        '<nav>menu</nav><H1>Title</H1><div class="newsReleaseDate">For Release: May 13, 2025</div>'
        '<p>Body <a>x</a>.</p><div class="content_right_column">side</div>'
    )
    text = to_text(html)
    assert text == "Title\nFor Release: May 13, 2025\nBody x."
    assert str(published_at(text)) == "2025-05-13"
    assert (
        str(published_at("DATE: February 3 , 2020 \nRE:")) == "None"
        and str(published_at("DATE: February 3, 2020 \nRE:")) == "2020-02-03"
    )
    assert str(published_at("Headline\nDecember 20, 2025 - The Department")) == "2025-12-20"
    with pytest.raises(ValueError):
        to_text("<p>no markers</p>")
