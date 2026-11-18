# Security policy

## Supported versions

Only the latest release (and the `master` branch) receives fixes.

## Reporting a vulnerability

Please do not open a public issue for a security problem. Use GitHub's private
reporting instead: the **Security** tab of the repository, then **Report a
vulnerability**. Describe what you found, how to reproduce it and which version
you used. You will get an answer as soon as possible.

## What the scripts do

- They download data files (time-zone boundaries, Natural Earth) over HTTPS from
  GitHub, and `solar_graph.py` and `earth_moon_sun.py` can look up a place on
  OpenStreetMap (Nominatim). The downloaded files are cached in `~/.cache/<script>`
  and are not checked against a hash.
- They write only the image or video file you ask for, and read no other
  personal data.
- On macOS, `solar_time_map.py` runs `defaults read -g AppleLanguages` to find the
  system language.
