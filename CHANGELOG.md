# Changelog

## Unreleased

### Added
- `solar_time_map.py --mode zones`: plain time-zone map with daylight-saving hatching,
  country, island, ocean and sea names, and the offsets of the 15° strips.
- `--island-join`: islands with the same UTC offset share one outline.
- `solar_graph.py --mark`, `--dst` and `--shift` to compare clock times.
- Tests (`pytest`), GitHub Actions CI (`ruff` and tests on Linux and Windows) and `pyproject.toml`.

### Changed
- Python 3.10 or newer is required.
- `except Exception` replaced by the specific errors in all three scripts.
- The long `draw` and `compose` functions were split into smaller ones (output unchanged).

### Removed
- `earth_moon_sun_old.py` (the earlier, simpler animation).

## Initial version
- `solar_graph.py`, `solar_time_map.py` and `earth_moon_sun.py`.
