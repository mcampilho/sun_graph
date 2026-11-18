import argparse
import datetime as dt
from zoneinfo import ZoneInfo

import numpy as np
import pytest

import solar_graph as sg

DAY = 4   # phase index of full daylight (see LIMITS)


@pytest.mark.parametrize("code, expected", [
    ("pt_PT.UTF-8", "pt"),
    ("pt-BR", "pt"),
    ("Portuguese_Portugal", "pt"),
    ("English_United States", "en"),
    ("fr_FR", None),       # not a language of solar_graph
    ("", None),
    (None, None),
])
def test_normalise_language(code, expected):
    assert sg.normalise_language(code) == expected


@pytest.mark.parametrize("text, expected", [("8:30", 8.5), ("08:30", 8.5), ("17", 17.0), ("0:00", 0.0)])
def test_parse_time(text, expected):
    assert sg.parse_time(text) == expected


@pytest.mark.parametrize("text", ["25:00", "8:75", "abc", "8:x"])
def test_parse_time_rejects_invalid(text):
    with pytest.raises(argparse.ArgumentTypeError):
        sg.parse_time(text)


def test_hhmm():
    assert sg.hhmm(0) == "00:00"
    assert sg.hhmm(8.5 * 60) == "08:30"
    assert sg.hhmm(1440) == "00:00"


def test_intervals():
    row = np.array([0, 1, 1, 0, 1, 0])
    assert sg.intervals(row, 1) == [(1, 3), (4, 5)]
    assert sg.intervals(row, 2) == []


def test_sun_is_overhead_at_the_equator_on_the_equinox():
    # 20 March 2026 is about 14:46 UTC; the Sun crosses the equator then
    noon = dt.datetime(2026, 3, 20, 12, 0, tzinfo=dt.timezone.utc).timestamp()
    assert sg.sun_elevation(np.array([noon]), 0.0, 0.0)[0] > 85
    # and it is below the horizon twelve hours later
    assert sg.sun_elevation(np.array([noon + 12 * 3600]), 0.0, 0.0)[0] < -80


def test_solstice_declination_is_23_degrees():
    jd = dt.datetime(2026, 6, 21, 12, tzinfo=dt.timezone.utc).timestamp() / 86400 + 2440587.5
    decl, eot = sg.sun_position(jd)
    assert np.degrees(decl) == pytest.approx(23.44, abs=0.05)
    assert abs(eot) < 3   # equation of time is small near the June solstice


def dates_of(year):
    return [dt.date(year, 1, 1) + dt.timedelta(days=k) for k in range(365)]


def test_simulated_dst_north_follows_the_european_rule():
    dates = dates_of(2026)
    sim = sg.simulated_dst(dates, np.zeros(365), lat=40.0)
    assert not sim[0].any()                    # 1 January
    assert sim[200].all()                      # mid July
    assert not sim[dates.index(dt.date(2026, 3, 28))].any()
    assert sim[dates.index(dt.date(2026, 3, 30))].all()
    assert sim[dates.index(dt.date(2026, 10, 24))].all()
    assert not sim[dates.index(dt.date(2026, 10, 26))].any()


def test_simulated_dst_south_is_summer_in_january():
    dates = dates_of(2026)
    sim = sg.simulated_dst(dates, np.zeros(365), lat=-30.0)
    assert sim[0].all()
    assert not sim[200].any()


def test_local_offsets_legal_off_and_shift():
    dates = dates_of(2026)
    lisbon = ZoneInfo("Europe/Lisbon")
    legal, has_dst = sg.local_offsets(dates, lisbon, 38.7)
    assert has_dst
    assert legal[0, 0] == 0 and legal[200, 720] == 60
    off, _ = sg.local_offsets(dates, lisbon, 38.7, dst="off")
    assert (off == 0).all()
    shifted, _ = sg.local_offsets(dates, lisbon, 38.7, dst="off", shift=1)
    assert (shifted == 60).all()


def test_local_offsets_simulates_dst_only_where_there_is_none():
    dates = dates_of(2026)
    reykjavik, has_dst = sg.local_offsets(dates, ZoneInfo("Atlantic/Reykjavik"), 64.1, dst="on")
    assert not has_dst and reykjavik[200, 720] == 60 and reykjavik[0, 0] == 0
    lisbon, has_dst = sg.local_offsets(dates, ZoneInfo("Europe/Lisbon"), 38.7, dst="on")
    assert has_dst and lisbon[0, 0] == 0    # keeps its own rules


def test_midnight_sun_and_polar_night_in_tromso():
    dates, phase, elev, noon, midnight, _ = sg.compute(69.65, 18.96, ZoneInfo("Europe/Oslo"), 2026)
    june = dates.index(dt.date(2026, 6, 21))
    december = dates.index(dt.date(2026, 12, 21))
    assert (phase[june] == DAY).all()          # the Sun never sets
    assert not (phase[december] == DAY).any()  # and it never rises
    assert noon.shape == (len(dates),)


def test_solar_noon_in_lisbon_is_after_noon_clock_time():
    _, _, _, noon, _, _ = sg.compute(38.72, -9.14, ZoneInfo("Europe/Lisbon"), 2026, dst="off")
    # 9.14° west of Greenwich is 37 min late, plus about 3 min from the equation of time in January
    assert 12.55 < noon[0] < 12.8
