import datetime as dt

import numpy as np
import pytest

pytest.importorskip("cartopy")
pytest.importorskip("rasterio")
pytest.importorskip("geopandas")

import solar_time_map as stm  # noqa: E402


@pytest.mark.parametrize("code, expected", [
    ("pt_PT.UTF-8", "pt"),
    ("Portuguese_Portugal", "pt"),
    ("Chinese_China", "zh"),
    ("ar-EG", "ar"),
    ("xx_YY", None),
    (None, None),
])
def test_normalise_language(code, expected):
    assert stm.normalise_language(code) == expected


def test_all_languages_have_the_same_keys():
    base = set(stm.TEXTS["en"])
    for lang, texts in stm.TEXTS.items():
        assert set(texts) == base, lang


@pytest.mark.parametrize("tzid, offset, dst", [
    ("Europe/Lisbon", 0, True),
    ("Asia/Kolkata", 5.5, False),
    ("Asia/Kathmandu", 5.75, False),
    ("Pacific/Chatham", 12.75, True),
    ("Australia/Sydney", 10, True),       # southern hemisphere: standard time is the winter one
    ("Etc/GMT+2", -2, False),             # POSIX sign: GMT+2 = UTC−2
])
def test_utc_offset_standard_time(tzid, offset, dst):
    assert stm.utc_offset(tzid) == (offset, dst)


def test_utc_offset_on_a_date():
    assert stm.utc_offset("Europe/Lisbon", dt.date(2026, 7, 1)) == (1, True)
    assert stm.utc_offset("Europe/Lisbon", dt.date(2026, 1, 15)) == (0, False)
    assert stm.utc_offset("Australia/Sydney", dt.date(2026, 1, 15)) == (11, True)


def test_utc_offset_unknown_zone():
    offset, dst = stm.utc_offset("Nowhere/Land")
    assert np.isnan(offset) and dst is False


@pytest.mark.parametrize("hours, text", [
    (0, "0"), (1, "+1"), (-5, "−5"), (5.5, "+5½"), (-9.5, "−9½"), (5.75, "+5¾"),
    (12.75, "+12¾"), (0.5, "+½"),
])
def test_format_offset(hours, text):
    assert stm.format_offset(hours) == text


def test_join_islands_fills_gaps_between_equal_offsets_only():
    area = np.full((11, 20), np.nan, dtype="float32")
    area[:, 5] = 1.0        # two coasts of offset 1, four cells apart
    area[:, 10] = 1.0
    nearest = np.full_like(area, 1.0)
    joined = stm.join_islands(area, nearest, radius=3, res=1)
    assert (joined[3:8, 6:10] == 1).all()          # the gap is closed
    assert np.isnan(joined[:, :2]).all()           # far sea stays empty

    # the sea next to a different civil zone is not taken
    other = np.full_like(area, 2.0)
    assert np.isnan(stm.join_islands(area, other, radius=3, res=1)[3:8, 6:10]).all()

    # radius 0 is handled by the caller, a tiny radius changes nothing
    assert np.isnan(stm.join_islands(area, nearest, radius=0.4, res=1)[5, 7])


def test_join_islands_wraps_around_the_antimeridian():
    area = np.full((9, 24), np.nan, dtype="float32")
    area[:, 1] = 7.0
    area[:, -2] = 7.0       # on both sides of 180°
    nearest = np.full_like(area, 7.0)
    joined = stm.join_islands(area, nearest, radius=3, res=1)
    assert not np.isnan(joined[4, 0]) and not np.isnan(joined[4, -1])


def test_solar_difference_and_wrap():
    offset = np.zeros((2, 4))
    is_land = np.ones((2, 4), dtype=bool)
    antarctica = np.zeros((2, 4), dtype=bool)
    antarctica[1] = True
    diff = stm.solar_difference(offset, is_land, antarctica, res=90)
    # longitudes −135, −45, 45, 135 with offset 0: lon / 15
    assert diff[0] == pytest.approx([-9, -3, 3, 9])
    assert np.isnan(diff[1]).all()
    # a single cell at −179.5° with offset +14 (Kiribati): −11.97 − 14 = −25.97, wrapped into ±12
    kiribati = stm.solar_difference(np.full((1, 1), 14.0), np.ones((1, 1), bool), np.zeros((1, 1), bool), res=1)
    assert kiribati[0, 0] == pytest.approx(-179.5 / 15 - 14 + 24)


def test_zone_colours_shape_and_transparency():
    offset = np.array([[0.0, 0.0, 5.5, 5.75, np.nan]])
    is_land = np.array([[True, False, True, True, False]])
    antarctica = np.zeros((1, 5), dtype=bool)
    img = stm.zone_colours(offset, is_land, antarctica)
    assert img.shape == (1, 5, 4)
    assert img[0, 4, 3] == 0                       # no zone: transparent
    assert (img[0, :4, 3] == 1).all()
    assert img[0, 1, :3].sum() > img[0, 0, :3].sum()   # the same offset is paler at sea
    assert not np.allclose(img[0, 2, :3], img[0, 3, :3])   # half and quarter hours have colours of their own


def test_labeller_rejects_overlaps():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots()
    labels = stm.Labeller(fig, ax)
    assert labels.text(0.5, 0.5, "hello", transform=ax.transAxes) is not None
    assert labels.text(0.5, 0.5, "hello", transform=ax.transAxes) is None    # same place
    assert labels.text(5, 5, "outside", transform=ax.transAxes) is None      # off the axes
    plt.close(fig)
