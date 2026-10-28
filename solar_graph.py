#!/usr/bin/env python3
"""
Yearly sunlight graph for any place in the world.

Shows, for every day of a calendar year (in local time, with daylight saving
when it applies):
  - Day, civil, nautical and astronomical twilight, and night
  - Solar noon (red line) and solar midnight (yellow line)
  - A detailed strip of one chosen day, with times and totals

Works at polar latitudes (midnight sun / polar night), because the Sun's
elevation is computed minute by minute instead of using sunrise/sunset
formulas.

Texts follow the system language by default, or the language given with
--lang. Supported: en, pt (European Portuguese).

Requirements:
    pip install numpy matplotlib geopy timezonefinder
    Windows: pip install tzdata

Examples:
    python solar_graph.py "Oslo, Norway"
    python solar_graph.py "Reykjavik, Iceland" --year 2026 --day 10-25
    python solar_graph.py "Lisboa, Portugal" --lang pt --output lisboa.png
    python solar_graph.py --lat 69.65 --lon 18.96 --name Tromsø --tz Europe/Oslo
"""

import argparse
import ctypes
import datetime as dt
import locale
import os
import sys
from zoneinfo import ZoneInfo

import numpy as np
import matplotlib.pyplot as plt
from matplotlib.colors import ListedColormap, BoundaryNorm
from matplotlib.gridspec import GridSpec

# ----------------------------------------------------------------------------
# Phases (index = phase number, from night to day) and their colours
# ----------------------------------------------------------------------------
PHASE_COLORS = ["#2e424d", "#57676f", "#6b8d98", "#93bccb", "#b0d9e6"]
LIMITS = [-18.0, -12.0, -6.0, -0.833]   # lower elevation limits; -0.833° = refraction + semi-diameter
NOON_COLOR = "#e8191c"
MIDNIGHT_COLOR = "#f2d50f"

# ----------------------------------------------------------------------------
# Translations
# ----------------------------------------------------------------------------
TEXTS = {
    "en": {
        "phases": ["Night", "Astronomical twilight", "Nautical twilight",
                   "Civil twilight", "Day"],
        "months": ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
        "title": "Solar graph {year} — {name}",
        "zone": "time zone",
        "total": "Total",
        "noon_midnight": "Solar noon / midnight:",
        "midnight_sun": "{n} days with 24 h sun",
        "polar_night": "{n} days without sunrise",
        "not_found": "Location not found: {place!r}",
        "saved": "Graph saved to {path}",
    },
    "pt": {
        "phases": ["Noite", "Crepúsculo astronómico", "Crepúsculo náutico",
                   "Crepúsculo civil", "Dia"],
        "months": ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun",
                   "Jul", "Ago", "Set", "Out", "Nov", "Dez"],
        "title": "Gráfico solar {year} — {name}",
        "zone": "fuso",
        "total": "Total",
        "noon_midnight": "Meio-dia / meia-noite solar:",
        "midnight_sun": "{n} dias com sol 24 h",
        "polar_night": "{n} dias sem nascer do sol",
        "not_found": "Localização não encontrada: {place!r}",
        "saved": "Gráfico guardado em {path}",
    },
}
LANGUAGES = list(TEXTS)

T = TEXTS["en"]        # active texts (set in main)
LANG = "en"


def normalise_language(code):
    """'pt_PT.UTF-8', 'pt-BR', 'Portuguese_Portugal' ... → 'pt' (or None)."""
    if not code:
        return None
    code = code.strip().lower().replace("-", "_")
    for name, c in {"english": "en", "portuguese": "pt"}.items():   # Windows style
        if code.startswith(name):
            return c
    c = code.split("_")[0].split(".")[0]
    return c if c in TEXTS else None


def system_language():
    """Language of the operating system / user session (English if not supported)."""
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        val = os.environ.get(var)
        if val and val not in ("C", "POSIX", "C.UTF-8"):
            for part in val.split(":"):
                c = normalise_language(part)
                if c:
                    return c
    if sys.platform == "win32":
        try:
            lcid = ctypes.windll.kernel32.GetUserDefaultUILanguage()
            c = normalise_language(locale.windows_locale.get(lcid))
            if c:
                return c
        except Exception:
            pass
    try:
        c = normalise_language(locale.getlocale()[0])
        if c:
            return c
    except Exception:
        pass
    return "en"


# ----------------------------------------------------------------------------
# Location
# ----------------------------------------------------------------------------
def geocode(place):
    """Turns 'City, Country' into (name, lat, lon) using OpenStreetMap."""
    from geopy.geocoders import Nominatim
    geo = Nominatim(user_agent="solar_graph_python")
    r = geo.geocode(place, language=LANG, timeout=15)
    if r is None:
        raise SystemExit(T["not_found"].format(place=place))
    return r.address.split(",")[0].strip(), r.latitude, r.longitude


def find_timezone(lat, lon):
    from timezonefinder import TimezoneFinder
    tz = TimezoneFinder().timezone_at(lat=lat, lng=lon)
    if tz is None:  # ocean / Antarctica: approximate zone from the longitude
        h = int(round(-lon / 15))
        tz = "UTC" if h == 0 else f"Etc/GMT{h:+d}"
    return tz


# ----------------------------------------------------------------------------
# Astronomy (NOAA algorithms, ~1 minute accuracy)
# ----------------------------------------------------------------------------
def sun_position(jd):
    """Returns (declination [rad], equation of time [min]) for Julian days."""
    T = (jd - 2451545.0) / 36525.0
    L0 = np.radians((280.46646 + T * (36000.76983 + 0.0003032 * T)) % 360)
    M = np.radians(357.52911 + T * (35999.05029 - 0.0001537 * T))
    e = 0.016708634 - T * (0.000042037 + 0.0000001267 * T)
    C = (np.sin(M) * (1.914602 - T * (0.004817 + 0.000014 * T))
         + np.sin(2 * M) * (0.019993 - 0.000101 * T)
         + np.sin(3 * M) * 0.000289)
    omega = np.radians(125.04 - 1934.136 * T)
    lam = np.radians(np.degrees(L0) + C - 0.00569 - 0.00478 * np.sin(omega))
    eps0 = 23 + (26 + (21.448 - T * (46.815 + T * (0.00059 - T * 0.001813))) / 60) / 60
    eps = np.radians(eps0 + 0.00256 * np.cos(omega))
    decl = np.arcsin(np.sin(eps) * np.sin(lam))
    y = np.tan(eps / 2) ** 2
    eot = 4 * np.degrees(
        y * np.sin(2 * L0) - 2 * e * np.sin(M)
        + 4 * e * y * np.sin(M) * np.cos(2 * L0)
        - 0.5 * y * y * np.sin(4 * L0) - 1.25 * e * e * np.sin(2 * M))
    return decl, eot


def sun_elevation(unix_s, lat, lon):
    """Sun elevation (degrees) for UTC instants given in Unix seconds."""
    jd = unix_s / 86400.0 + 2440587.5
    decl, eot = sun_position(jd)
    utc_min = (unix_s % 86400) / 60.0
    ha = np.radians((utc_min + eot + 4 * lon) / 4.0 - 180.0)
    phi = np.radians(lat)
    cz = np.sin(phi) * np.sin(decl) + np.cos(phi) * np.cos(decl) * np.cos(ha)
    return 90.0 - np.degrees(np.arccos(np.clip(cz, -1, 1)))


# ----------------------------------------------------------------------------
# Yearly grid (days x minutes, in local time)
# ----------------------------------------------------------------------------
def local_offsets(dates, tz):
    """UTC offset (minutes) of every local minute of every day, daylight saving included."""
    off = np.empty((len(dates), 1440))
    for i, d in enumerate(dates):
        a = dt.datetime(d.year, d.month, d.day, 0, 0, tzinfo=tz).utcoffset()
        b = dt.datetime(d.year, d.month, d.day, 23, 59, tzinfo=tz).utcoffset()
        if a == b:
            off[i] = a.total_seconds() / 60
        else:  # day the clocks change: resolve minute by minute
            base = dt.datetime(d.year, d.month, d.day, tzinfo=tz)
            for m in range(1440):
                t = (base + dt.timedelta(minutes=m)).replace(tzinfo=tz)
                off[i, m] = t.utcoffset().total_seconds() / 60
    return off


def compute(lat, lon, tz, year):
    dates = [dt.date(year, 1, 1) + dt.timedelta(days=k)
             for k in range((dt.date(year + 1, 1, 1) - dt.date(year, 1, 1)).days)]
    utc_midnight = np.array([dt.datetime(d.year, d.month, d.day,
                                         tzinfo=dt.timezone.utc).timestamp()
                             for d in dates])
    minutes = np.arange(1440)
    off = local_offsets(dates, tz)
    # evaluate the centre of each minute (rounds times to the nearest minute)
    unix = utc_midnight[:, None] + (minutes[None, :] + 0.5 - off) * 60.0
    elev = sun_elevation(unix, lat, lon)
    phase = np.digitize(elev, LIMITS)            # 0 = night ... 4 = day

    # Solar noon in local time (minutes): 720 - 4*lon - EoT + offset
    _, eot = sun_position(utc_midnight / 86400.0 + 2440587.5 + 0.5 - lon / 360)
    solar_utc = 720 - 4 * lon - eot             # solar noon in UTC minutes
    idx = np.arange(len(dates))
    # use the offset in force at that very instant (matters on the days the
    # clocks change, which happens at night)
    m_noon = ((solar_utc + off[:, 720]) % 1440).astype(int)
    noon = (solar_utc + off[idx, m_noon]) % 1440
    m_mid = ((solar_utc - 720 + off[:, 0]) % 1440).astype(int)
    midnight = (solar_utc - 720 + off[idx, m_mid]) % 1440
    return dates, phase, elev, noon / 60, midnight / 60


# ----------------------------------------------------------------------------
# Text for one day
# ----------------------------------------------------------------------------
def hhmm(m):
    m = int(round(m)) % 1440 if m < 1440 else 0
    return f"{m // 60:02d}:{m % 60:02d}"


def intervals(row, k):
    """[start, end] intervals (minutes) in which the phase of one day is k."""
    inside = np.concatenate(([False], row == k, [False]))
    d = np.diff(inside.astype(int))
    start, end = np.where(d == 1)[0], np.where(d == -1)[0]
    return list(zip(start, end))


# ----------------------------------------------------------------------------
# Graph
# ----------------------------------------------------------------------------
def plot_with_breaks(ax, x, y, color):
    """Draws the line, breaking it where it jumps (clock change or wrap at 24 h)."""
    y = y.copy()
    jumps = np.where(np.abs(np.diff(y)) > 0.4)[0]
    for s in jumps[::-1]:
        x = np.insert(x, s + 1, np.nan)
        y = np.insert(y, s + 1, np.nan)
    ax.plot(x, y, color=color, lw=1.4)


def draw(name, lat, lon, tz_name, year, day, output, show):
    tz = ZoneInfo(tz_name)
    dates, phase, elev, noon, midnight = compute(lat, lon, tz, year)
    n = len(dates)
    cmap = ListedColormap(PHASE_COLORS)
    norm = BoundaryNorm(np.arange(-0.5, 5.5), cmap.N)

    fig = plt.figure(figsize=(13, 7.6), facecolor="white")
    gs = GridSpec(3, 1, height_ratios=[6, 0.75, 1.9], hspace=0.28,
                  left=0.045, right=0.99, top=0.93, bottom=0.02)

    # --- Yearly graph -------------------------------------------------------
    ax = fig.add_subplot(gs[0])
    ax.imshow(phase.T, origin="lower", aspect="auto", cmap=cmap, norm=norm,
              extent=[0, n, 0, 24], interpolation="nearest")
    x = np.arange(n) + 0.5
    plot_with_breaks(ax, x, noon, NOON_COLOR)
    plot_with_breaks(ax, x, midnight, MIDNIGHT_COLOR)

    i_day = (day - dates[0]).days
    ax.axvline(i_day, color="white", lw=0.9)
    ax.axvline(i_day + 1, color="white", lw=0.9)

    months = T["months"]
    starts = [(dt.date(year, m, 1) - dates[0]).days for m in range(1, 13)]
    ax.set_xticks(starts)
    ax.set_xticklabels(months, ha="left", color="#555")
    ax.set_yticks(range(0, 24, 2))
    ax.set_yticklabels([f"{h:02d}" for h in range(0, 24, 2)], color="#555")
    ax.set_ylim(0, 24)
    ax.set_xlim(0, n)
    ax.tick_params(length=0)
    for s in ax.spines.values():
        s.set_visible(False)
    coords = f"{abs(lat):.2f}°{'N' if lat >= 0 else 'S'}, {abs(lon):.2f}°{'E' if lon >= 0 else 'W'}"
    fig.suptitle(T["title"].format(year=year, name=name), x=0.045, ha="left",
                 fontsize=15, fontweight="bold", color="#333")
    fig.text(0.99, 0.955, f"{coords} · {T['zone']} {tz_name}", ha="right",
             fontsize=9, color="#777")

    # --- Strip of the chosen day ---------------------------------------------
    axd = fig.add_subplot(gs[1])
    axd.imshow(phase[i_day][None, :], aspect="auto", cmap=cmap, norm=norm,
               extent=[0, 24, 0, 1], interpolation="nearest")
    axd.set_xlim(0, 24)
    axd.set_xticks(range(0, 24, 2))
    axd.set_xticklabels([f"{h:02d}" for h in range(0, 24, 2)], color="#555",
                        fontsize=8)
    axd.xaxis.tick_top()
    axd.set_yticks([])
    for s in axd.spines.values():
        s.set_visible(False)
    axd.text(-0.15, 0.5, day.strftime("%d\n") + months[day.month - 1],
             transform=axd.transData, ha="right", va="center",
             fontsize=11, color="white", fontweight="bold",
             bbox=dict(boxstyle="square,pad=0.45", fc="#e8175d", ec="none"))

    # --- Legend with times ----------------------------------------------------
    axl = fig.add_subplot(gs[2])
    axl.axis("off")
    row = phase[i_day]
    width = 1 / 6
    for k in range(5):
        color = PHASE_COLORS[k]
        xk = k * width
        axl.add_patch(plt.Rectangle((xk, 0.82), 0.012, 0.12, color=color,
                                    transform=axl.transAxes))
        axl.text(xk + 0.018, 0.88, T["phases"][k] + ":", fontsize=9, fontweight="bold",
                 va="center", color="#333", transform=axl.transAxes)
        txt = "\n".join(f"{hhmm(a)} - {hhmm(b)}" for a, b in intervals(row, k)) or "—"
        axl.text(xk + 0.018, 0.72, txt, fontsize=8.5, va="top",
                 color="#333", transform=axl.transAxes)
        tot = int((row == k).sum())
        axl.text(xk + 0.018, 0.05, f"{T['total']}:  {tot // 60:02d}:{tot % 60:02d}",
                 fontsize=8.5, fontweight="bold", color="#333",
                 transform=axl.transAxes)
    xk = 5 * width
    axl.text(xk, 0.88, T["noon_midnight"], fontsize=9,
             fontweight="bold", va="center", color="#333", transform=axl.transAxes)
    for j, (color, val) in enumerate([(NOON_COLOR, noon[i_day]),
                                      (MIDNIGHT_COLOR, midnight[i_day])]):
        yy = 0.66 - j * 0.17
        axl.plot([xk, xk + 0.02], [yy, yy], color=color, lw=1.6,
                 transform=axl.transAxes)
        axl.text(xk + 0.026, yy, hhmm(val * 60), fontsize=8.5, va="center",
                 color="#333", transform=axl.transAxes)

    # Midnight sun / polar night note
    never_sets = np.all(phase == 4, axis=1).sum()
    never_rises = np.all(phase < 4, axis=1).sum()
    extra = []
    if never_sets:
        extra.append(T["midnight_sun"].format(n=never_sets))
    if never_rises:
        extra.append(T["polar_night"].format(n=never_rises))
    if extra:
        fig.text(0.99, 0.935, " · ".join(extra), ha="right", fontsize=9,
                 color="#777")

    if output:
        fig.savefig(output, dpi=130)
        print(T["saved"].format(path=output))
    if show or not output:
        plt.show()


# ----------------------------------------------------------------------------
def main():
    global T, LANG
    p = argparse.ArgumentParser(description="Yearly sunlight graph.")
    p.add_argument("place", nargs="?", help='city and country, e.g. "Oslo, Norway"')
    p.add_argument("--year", type=int, default=dt.date.today().year)
    p.add_argument("--day", help="highlighted day, MM-DD (default: today)")
    p.add_argument("--lat", type=float, help="latitude (skips geocoding)")
    p.add_argument("--lon", type=float, help="longitude")
    p.add_argument("--name", help="name shown in the title")
    p.add_argument("--tz", help="IANA time zone, e.g. Europe/Lisbon (default: automatic)")
    p.add_argument("--lang", "-l", metavar="LANG",
                   help="language of the texts: " + ", ".join(LANGUAGES) +
                        " (default: system language, falling back to English)")
    p.add_argument("--output", "-o", help="image file (png, pdf, svg)")
    p.add_argument("--show", action="store_true", help="also open a window")
    a = p.parse_args()

    if a.lang:
        LANG = normalise_language(a.lang)
        if LANG is None:
            p.error(f"unsupported language '{a.lang}'. Choose from: {', '.join(LANGUAGES)}")
    else:
        LANG = system_language()
    T = TEXTS[LANG]

    if a.lat is not None and a.lon is not None:
        name, lat, lon = a.name or a.place or f"{a.lat:.3f}, {a.lon:.3f}", a.lat, a.lon
    elif a.place:
        name, lat, lon = geocode(a.place)
        name = a.name or name
    else:
        p.error("give a place or --lat and --lon")
    tz = a.tz or find_timezone(lat, lon)

    if a.day:
        m, d = map(int, a.day.split("-"))
        day = dt.date(a.year, m, d)
    else:
        today = dt.date.today()
        day = today.replace(year=a.year) if not (today.month == 2 and today.day == 29) else dt.date(a.year, 2, 28)

    print(f"{name}: lat {lat:.4f}, lon {lon:.4f}, {T['zone']} {tz}")
    draw(name, lat, lon, tz, a.year, day, a.output, a.show)


if __name__ == "__main__":
    main()
