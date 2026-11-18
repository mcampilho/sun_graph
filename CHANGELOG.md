# Changelog

## 1.0.0 - 2026-11-18

### Added
- `SECURITY.md`.
- `solar_time_map.py --mode zones`: plain time-zone map with daylight-saving hatching,
  country, island, ocean and sea names, and the offsets of the 15° strips.
- `--island-join`: islands with the same UTC offset share one outline.
- `solar_graph.py --mark`, `--dst` and `--shift` to compare clock times.
- Tests (`pytest`), GitHub Actions CI (`ruff` and tests on Linux and Windows) and `pyproject.toml`.

### Changed
- Python 3.10 or newer is required.
- No `global` statements: the active language, reference city and textures are held by an
  `Active` class or passed as arguments, and the segment speeds are cached with `functools.lru_cache`.
- `except Exception` replaced by the specific errors in all three scripts.
- Docstrings on every function and type hints on the calculation and helper functions.
- The long `draw` and `compose` functions were split into smaller ones (output unchanged).

### Removed
- `earth_moon_sun_old.py` (the earlier, simpler animation).

## Initial version
- `solar_graph.py`, `solar_time_map.py` and `earth_moon_sun.py`.
