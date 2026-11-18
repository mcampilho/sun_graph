import math

import numpy as np
import pytest

pytest.importorskip("PIL")

import earth_moon_sun as ems  # noqa: E402


def test_parse_city_coordinates_and_known_names():
    assert ems.parse_city("38.7,-9.1,Casa") == ("Casa", 38.7, -9.1)
    assert ems.parse_city("10,20")[1:] == (10.0, 20.0)
    assert ems.parse_city("São Paulo")[0] == "São Paulo"       # accents are ignored
    assert ems.parse_city("LISBOA") == ems.CITIES["lisboa"]


def test_parse_city_unknown_without_geopy(monkeypatch):
    import builtins
    real_import = builtins.__import__

    def no_geopy(name, *args, **kw):
        if name.startswith("geopy"):
            raise ImportError(name)
        return real_import(name, *args, **kw)

    monkeypatch.setattr(builtins, "__import__", no_geopy)
    with pytest.raises(SystemExit):
        ems.parse_city("Nowhere At All")


def test_solar_longitude_at_the_solstices():
    # the animation starts at the June solstice
    assert ems.solar_longitude(0.0) == pytest.approx(90, abs=1)
    t = ems.time_of_longitude(180, 0.0)       # September equinox
    assert 90 < t < 95
    assert ems.solar_longitude(t) == pytest.approx(180, abs=1e-3)


def test_sun_direction_is_a_unit_vector_in_the_ecliptic():
    for t in (0, 50, 200):
        s = ems.sun_dir(t)
        assert np.linalg.norm(s) == pytest.approx(1)
        assert s[2] == 0


def test_moon_state_keeps_its_distance_and_faces_the_earth():
    rel, axes, elong = ems.moon_state(12.3, 30.0)
    assert np.linalg.norm(rel) == pytest.approx(30.0)
    assert axes[0] @ rel < 0                       # the near side looks at the Earth
    assert 0 <= elong < 2 * math.pi


def test_moon_phase_names_cover_the_whole_cycle():
    ems.Active.T = ems.TEXTS["en"]
    names = {ems.phase_name(math.radians(a)) for a in range(0, 360, 45)}
    assert len(names) == 8


def test_day_length_follows_the_seasons():
    lisbon = math.radians(38.7)
    june, december = ems.day_length(0.0, lisbon), ems.day_length(ems.YEAR / 2, lisbon)
    assert june > 14 > 10 > december
    assert ems.day_length(0.0, math.radians(89)) == pytest.approx(24)      # midnight sun


def test_hit_sphere():
    o = np.zeros(3)
    d = np.array([[1.0, 0, 0], [0, 1.0, 0]], np.float32)
    t, b, closest = ems.hit_sphere(o, d, np.array([10.0, 0, 0]), 2.0)
    assert t[0] == pytest.approx(8.0) and np.isinf(t[1])
