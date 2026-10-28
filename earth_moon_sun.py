#!/usr/bin/env python3
"""
Earth · Moon · Sun — animated model of sunlight on the Earth and the Moon.

The animation has three acts, joined by smooth camera moves and a time
scale that speeds up and slows down smoothly:

  1. Earth's rotation over 24 hours (June solstice), with the Sun lighting one
     side: terminator, 23.4° axial tilt, polar day/night, city lights on the
     night side, equator/tropics/polar circles, the point where the Sun is
     overhead, and a reference city (default Lisboa) with a chart of the Sun's
     elevation through the day.
  2. The Moon: one synodic month (29.5 days). The Moon orbits the Earth and
     keeps the same face towards it. An inset shows the Moon as seen from
     Earth (phase, earthshine; mirrored for the southern hemisphere). Time
     slows down for a solar eclipse (the Moon's shadow crosses Africa); a
     lunar eclipse happens at full moon. Then: "why isn't there an eclipse
     every month?" — the tilted lunar orbit (exaggerated to 15°), the line of
     nodes and the Moon's shadow passing above the Earth in September and
     hitting it again in January.
  3. One year around the Sun on a Keplerian (elliptical) orbit. The axis keeps
     its direction in space, producing the four seasons; perihelion (3 Jan)
     and aphelion (4 Jul) show that the distance is not what causes them.
     Insets: side view of the Earth with tropics and the overhead Sun, and the
     day length over the year in the reference city.

Everything is drawn with a small numpy ray tracer: real continents (Natural
Earth), city lights synthesised from ~7300 populated places, procedural
clouds and lunar maria, Lambert lighting, ocean glint, atmosphere, and soft
shadows computed from the real geometry (fraction of the solar disc hidden
by the Moon or the Earth).

Sizes and distances are NOT to scale (the real Moon is ~60 Earth radii
away and the Sun ~23 000), otherwise nothing would be visible.

Requirements:
    pip install numpy pillow imageio imageio-ffmpeg
    (matplotlib is optional: used for its fonts and for --show)

Examples:
    python earth_moon_sun.py                       # earth_moon_sun.mp4, 960x540
    python earth_moon_sun.py --width 1920 --height 1080 --output hd.mp4
    python earth_moon_sun.py --scenes 2 --lang en  # only the Moon act, in English
    python earth_moon_sun.py --step 10 --output preview.mp4   # quick preview
    python earth_moon_sun.py --city Porto
    python earth_moon_sun.py --city "São Paulo" --lang pt    # southern view of the Moon
    python earth_moon_sun.py --city "-8.84,13.23,Luanda"
"""

import argparse
import json
import locale
import math
import os
import sys
import time
import urllib.request

import numpy as np
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ----------------------------------------------------------------------------
# Model constants (scene units: Earth radius = 1)
# ----------------------------------------------------------------------------
EARTH_R = 1.0
ORBIT_R = 60.0               # Earth–Sun mean distance (not to scale)
ECC = 0.0167                 # real eccentricity of Earth's orbit
PERI_LON = math.radians(193.0)   # direction of perihelion in the model (solar longitude ≈ 283°)
DEMO_INC = 15.0              # Moon orbit inclination used in the eclipse explanation (exaggerated)
SUN_R = 8.0
MOON_DIST = 10.0             # Earth–Moon distance (real: ~60)
MOON_R = 0.273               # real ratio Moon/Earth radius
TILT = math.radians(23.44)
MOON_INC = math.radians(5.14)
YEAR = 365.2422
SYNODIC = 29.530589
SIDEREAL_MONTH = 27.321661
# Angular radius of the Sun used for shadows. Chosen so that, with the
# shortened Moon distance, the umbra on Earth is small (~0.06 Earth radii)
# and surrounded by a wide penumbra, as in a real total eclipse.
SUN_ANG = math.atan((MOON_R - 0.06) / (MOON_DIST - EARTH_R))

LAND_URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
            "master/geojson/ne_50m_land.geojson")
PLACES_URL = ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
              "master/geojson/ne_10m_populated_places_simple.geojson")

# Timeline anchors (days since 21 June, 00:00 UTC — June solstice)
T_MOON = 1.735                         # full moon; start of act 2
T_NEW = T_MOON + SYNODIC / 2           # new moon at ~12:00 UTC → eclipse over Africa
T_SEP = T_NEW + 2 * SYNODIC            # September new moon: no eclipse
T_JAN = T_NEW + 6 * SYNODIC            # January new moon: back on the node line → eclipse
T_ACT3 = T_JAN + 10

# ----------------------------------------------------------------------------
# Texts
# ----------------------------------------------------------------------------
TEXTS = {
    "pt": {
        "t1": "1 · Rotação da Terra — 24 horas",
        "s1": "Eixo inclinado 23,4° · solstício de junho: dia polar no Ártico, noite polar na Antártida",
        "t2": "2 · A Lua — translação, rotação síncrona e fases",
        "s2": "Mês sinódico (lua nova a lua nova): 29,5 dias · a Lua mostra sempre a mesma face à Terra",
        "t2e": "Eclipse solar — a sombra da Lua sobre a Terra",
        "s2e": "A Lua passa entre o Sol e a Terra: sombra (umbra) no centro e penumbra à volta",
        "tx": "Porque não há um eclipse todos os meses?",
        "sx": "A órbita da Lua está inclinada em relação à da Terra (aqui 15°, exagerado; na realidade 5,1°)",
        "node_line": "linha dos nodos", "ecliptic": "plano da órbita da Terra",
        "moon_orbit": "órbita da Lua", "moon_shadow": "sombra da Lua",
        "miss_above": "Lua nova: a sombra passa acima da Terra — não há eclipse",
        "miss_below": "Lua nova: a sombra passa abaixo da Terra — não há eclipse",
        "hit": "Lua nova sobre a linha dos nodos: Sol, Lua e Terra alinhados — eclipse!",
        "s3b": "A Terra está mais perto do Sol no início de janeiro (inverno no norte): as estações vêm da inclinação, não da distância",
        "perihelion": "Periélio · 3 jan · 147,1 milhões km", "aphelion": "Afélio · 4 jul · 152,1 milhões km",
        "elev_chart": "Altura do Sol em {city} · {date} (UTC)",
        "daylen_chart": "Duração do dia em {city}",
        "legend_eq": "Equador", "legend_trop": "Trópicos", "legend_polar": "Círculos polares",
        "subsolar": "Sol a pino",
        "t3": "3 · Translação da Terra — um ano e as quatro estações",
        "s3": "O eixo mantém sempre a mesma direção no espaço: cada hemisfério recebe mais ou menos luz ao longo do ano",
        "months": ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"],
        "rate_h": "1 s ≈ {v} h", "rate_d": "1 s ≈ {v} dias",
        "not_scale": "Tamanhos e distâncias fora de escala",
        "moon_inset": "A Lua vista da Terra",
        "cycle_day": "dia {d} do ciclo lunar",
        "phases": ["Lua nova", "Lua crescente", "Quarto crescente", "Crescente gibosa",
                   "Lua cheia", "Minguante gibosa", "Quarto minguante", "Lua minguante"],
        "solar_ecl": "ECLIPSE SOLAR", "lunar_ecl": "ECLIPSE LUNAR",
        "season_inset": "Vista lateral da Terra",
        "sun": "Sol",
        "north": "Hemisfério Norte", "south": "Hemisfério Sul",
        "seasons": ["Primavera", "Verão", "Outono", "Inverno"],
        "points": ["Equinócio de março", "Solstício de junho",
                   "Equinócio de setembro", "Solstício de dezembro"],
        "illustrative": "rotação diária ilustrativa (abrandada)",
        "downloading": "A descarregar os contornos dos continentes ...",
        "no_lights": "[aviso] Sem dados de localidades: o lado noturno ficará sem luzes das cidades.",
        "offline": "[aviso] Sem dados de continentes: a Terra será desenhada só com oceano.",
        "textures": "A preparar texturas ...",
        "rendering": "A gerar {n} imagens ({w}x{h}) ...",
        "done": "Vídeo guardado em {path} ({s:.0f} s de animação, {m:.1f} min de cálculo)",
        "frames_saved": "Sem imageio-ffmpeg: imagens guardadas em {path}",
    },
    "en": {
        "t1": "1 · Earth's rotation — 24 hours",
        "s1": "Axis tilted 23.4° · June solstice: polar day in the Arctic, polar night in Antarctica",
        "t2": "2 · The Moon — orbit, synchronous rotation and phases",
        "s2": "Synodic month (new moon to new moon): 29.5 days · the Moon always shows the same face to Earth",
        "t2e": "Solar eclipse — the Moon's shadow on the Earth",
        "s2e": "The Moon passes between the Sun and the Earth: umbra in the centre, penumbra around it",
        "tx": "Why isn't there an eclipse every month?",
        "sx": "The Moon's orbit is tilted relative to Earth's (15° here, exaggerated; really 5.1°)",
        "node_line": "line of nodes", "ecliptic": "plane of Earth's orbit",
        "moon_orbit": "Moon's orbit", "moon_shadow": "Moon's shadow",
        "miss_above": "New moon: the shadow passes above the Earth — no eclipse",
        "miss_below": "New moon: the shadow passes below the Earth — no eclipse",
        "hit": "New moon on the line of nodes: Sun, Moon and Earth aligned — eclipse!",
        "s3b": "Earth is closest to the Sun in early January (northern winter): seasons come from the tilt, not the distance",
        "perihelion": "Perihelion · 3 Jan · 147.1 million km", "aphelion": "Aphelion · 4 Jul · 152.1 million km",
        "elev_chart": "Sun elevation in {city} · {date} (UTC)",
        "daylen_chart": "Day length in {city}",
        "legend_eq": "Equator", "legend_trop": "Tropics", "legend_polar": "Polar circles",
        "subsolar": "Sun overhead",
        "t3": "3 · Earth's orbit — one year and the four seasons",
        "s3": "The axis always points the same way in space: each hemisphere gets more or less light through the year",
        "months": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
        "rate_h": "1 s ≈ {v} h", "rate_d": "1 s ≈ {v} days",
        "not_scale": "Sizes and distances not to scale",
        "moon_inset": "The Moon seen from Earth",
        "cycle_day": "day {d} of the lunar cycle",
        "phases": ["New Moon", "Waxing Crescent", "First Quarter", "Waxing Gibbous",
                   "Full Moon", "Waning Gibbous", "Last Quarter", "Waning Crescent"],
        "solar_ecl": "SOLAR ECLIPSE", "lunar_ecl": "LUNAR ECLIPSE",
        "season_inset": "Side view of the Earth",
        "sun": "Sun",
        "north": "Northern Hemisphere", "south": "Southern Hemisphere",
        "seasons": ["Spring", "Summer", "Autumn", "Winter"],
        "points": ["March equinox", "June solstice", "September equinox", "December solstice"],
        "illustrative": "illustrative daily rotation (slowed down)",
        "downloading": "Downloading continent outlines ...",
        "no_lights": "[warning] No populated places data: the night side will have no city lights.",
        "offline": "[warning] No continent data: the Earth will be drawn as ocean only.",
        "textures": "Preparing textures ...",
        "rendering": "Rendering {n} frames ({w}x{h}) ...",
        "done": "Video saved to {path} ({s:.0f} s of animation, {m:.1f} min of rendering)",
        "frames_saved": "imageio-ffmpeg not found: frames saved in {path}",
    },
}
T = TEXTS["en"]

CITIES = {
    "lisboa": ("Lisboa", 38.72, -9.14), "lisbon": ("Lisbon", 38.72, -9.14),
    "porto": ("Porto", 41.15, -8.61), "funchal": ("Funchal", 32.65, -16.91),
    "ponta delgada": ("Ponta Delgada", 37.74, -25.67), "madrid": ("Madrid", 40.42, -3.70),
    "paris": ("Paris", 48.86, 2.35), "london": ("London", 51.51, -0.13), "londres": ("Londres", 51.51, -0.13),
    "berlin": ("Berlin", 52.52, 13.40), "oslo": ("Oslo", 59.91, 10.75), "tromso": ("Tromsø", 69.65, 18.96),
    "reykjavik": ("Reykjavik", 64.15, -21.94), "new york": ("New York", 40.71, -74.01),
    "sao paulo": ("São Paulo", -23.55, -46.63), "rio de janeiro": ("Rio de Janeiro", -22.91, -43.17),
    "brasilia": ("Brasília", -15.79, -47.88), "luanda": ("Luanda", -8.84, 13.23),
    "maputo": ("Maputo", -25.97, 32.57), "praia": ("Praia", 14.93, -23.51), "dili": ("Díli", -8.56, 125.57),
    "cape town": ("Cape Town", -33.92, 18.42), "tokyo": ("Tokyo", 35.68, 139.69),
    "sydney": ("Sydney", -33.87, 151.21), "singapore": ("Singapore", 1.35, 103.82),
}
CITY = CITIES["lisboa"]
HEMI_SOUTH = False


def parse_city(text_):
    """'Lisboa', 'São Paulo' or 'lat,lon[,name]'."""
    import unicodedata
    parts = [x.strip() for x in text_.split(",")]
    try:
        lat, lon = float(parts[0]), float(parts[1])
        return (parts[2] if len(parts) > 2 else f"{lat:.2f}, {lon:.2f}", lat, lon)
    except (ValueError, IndexError):
        pass
    key = "".join(c for c in unicodedata.normalize("NFKD", text_.lower()) if not unicodedata.combining(c))
    if key in CITIES:
        return CITIES[key]
    try:
        from geopy.geocoders import Nominatim
        loc = Nominatim(user_agent="earth_moon_sun").geocode(text_, timeout=10)
        if loc:
            return (text_.split(",")[0], loc.latitude, loc.longitude)
    except Exception:
        pass
    raise SystemExit(f"Unknown city '{text_}'. Use 'lat,lon,name' or one of: {', '.join(sorted(CITIES))}")


def system_language():
    for var in ("LANGUAGE", "LC_ALL", "LC_MESSAGES", "LANG"):
        v = os.environ.get(var, "")
        if v[:2].lower() in TEXTS:
            return v[:2].lower()
    if sys.platform == "win32":
        try:
            import ctypes
            name = locale.windows_locale.get(ctypes.windll.kernel32.GetUserDefaultUILanguage(), "")
            if name[:2] in TEXTS:
                return name[:2]
        except Exception:
            pass
    try:
        v = (locale.getlocale()[0] or "").lower()
        if v[:2] in TEXTS:
            return v[:2]
        if v.startswith("portuguese"):
            return "pt"
    except Exception:
        pass
    return "en"


def num(v, dec=1):
    s = f"{v:.{dec}f}"
    return s.replace(".", ",") if T is TEXTS["pt"] else s


# ----------------------------------------------------------------------------
# Small vector helpers
# ----------------------------------------------------------------------------
def norm(v):
    return v / np.linalg.norm(v, axis=-1, keepdims=True)


def rot_y(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])


def rot_z(a):
    c, s = math.cos(a), math.sin(a)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]])


def smoothstep(x):
    x = min(max(x, 0.0), 1.0)
    return x * x * (3 - 2 * x)


M_TILT = rot_y(-TILT)            # Earth axis = M_TILT @ Z = tilted towards −X
EARTH_AXIS = M_TILT @ np.array([0.0, 0.0, 1.0])


# ----------------------------------------------------------------------------
# Ephemeris of the toy model
# ----------------------------------------------------------------------------
def _peri_time():
    """Perihelion time chosen so that t = 0 is exactly the June solstice."""
    nu0 = -PERI_LON
    E0 = 2 * math.atan(math.sqrt((1 - ECC) / (1 + ECC)) * math.tan(nu0 / 2))
    return -(E0 - ECC * math.sin(E0)) / (2 * math.pi) * YEAR


T_PERI = _peri_time()


def earth_lon_dist(t):
    """Heliocentric longitude (λ=0 → June solstice) and distance, Kepler's equation."""
    M = 2 * math.pi * (t - T_PERI) / YEAR
    E = M
    for _ in range(6):
        E -= (E - ECC * math.sin(E) - M) / (1 - ECC * math.cos(E))
    nu = 2 * math.atan2(math.sqrt(1 + ECC) * math.sin(E / 2), math.sqrt(1 - ECC) * math.cos(E / 2))
    r = ORBIT_R * (1 - ECC * math.cos(E))
    return nu + PERI_LON, r


def earth_pos(t):
    lam, r = earth_lon_dist(t)
    return np.array([r * math.cos(lam), r * math.sin(lam), 0.0])


def sun_dir(t):
    e = earth_pos(t)
    return -e / np.linalg.norm(e)


def solar_longitude(t):
    """Sun's ecliptic longitude: 0 = March equinox, 90 = June solstice ..."""
    return (math.degrees(earth_lon_dist(t)[0]) + 90.0) % 360.0


def time_of_longitude(ls, t_from):
    """First time after t_from when the solar longitude equals ls (degrees)."""
    t = t_from
    for _ in range(40):
        d = (ls - solar_longitude(t) + 180) % 360 - 180
        if abs(d) < 1e-6:
            break
        t += d / 360 * YEAR
    return t if t >= t_from - 1 else t + YEAR


def earth_rotation(t):
    """Rotation angle so that it is 12:00 at Greenwich when frac(t) = 0.5."""
    s_eq = M_TILT.T @ sun_dir(t)
    alpha = math.atan2(s_eq[1], s_eq[0])
    return alpha + 2 * math.pi * ((t % 1.0) - 0.5)


def moon_state(t, dist, inc=MOON_INC):
    """Moon position relative to Earth, and its body axes (x faces Earth)."""
    sun_lon = math.atan2(*sun_dir(t)[1::-1])
    node = math.atan2(*sun_dir(T_NEW)[1::-1])          # node line through the eclipse
    elong = 2 * math.pi * (t - T_NEW) / SYNODIC          # 0 = new moon, π = full moon
    u = sun_lon + elong - node
    ci, si = math.cos(inc), math.sin(inc)
    cO, sO = math.cos(node), math.sin(node)
    rel = dist * np.array([cO * math.cos(u) - sO * math.sin(u) * ci,
                           sO * math.cos(u) + cO * math.sin(u) * ci,
                           math.sin(u) * si])
    z_m = np.array([sO * si, -cO * si, ci])              # orbit normal
    x_m = -rel / np.linalg.norm(rel)                     # near side faces the Earth
    y_m = np.cross(z_m, x_m)
    return rel, np.stack([x_m, y_m, z_m]), elong % (2 * math.pi)


def date_label(t):
    d = np.datetime64("2026-06-21T00:00") + np.timedelta64(int(round(t * 1440)), "m")
    s = str(d)
    month = int(s[5:7]) - 1
    return f"{int(s[8:10])} {T['months'][month]} · {s[11:16]} UTC"


# ----------------------------------------------------------------------------
# Textures
# ----------------------------------------------------------------------------
def periodic_noise(h, w, octaves=6, base=4, seed=0, persistence=0.55):
    """Fractal value noise, seamless in longitude (x)."""
    rng = np.random.default_rng(seed)
    out = np.zeros((h, w), np.float32)
    amp, total = 1.0, 0.0
    for o in range(octaves):
        gw = base * 2 ** o
        gh = max(2, gw // 2)
        g = rng.random((gh + 1, gw)).astype(np.float32)
        x = np.arange(w) * gw / w
        y = np.arange(h) * gh / h
        x0 = np.floor(x).astype(int); fx = x - x0; x1 = (x0 + 1) % gw
        y0 = np.floor(y).astype(int); fy = y - y0; y1 = np.minimum(y0 + 1, gh)
        fx = fx * fx * (3 - 2 * fx); fy = fy * fy * (3 - 2 * fy)
        a = g[y0][:, x0] * (1 - fx) + g[y0][:, x1] * fx
        b = g[y1][:, x0] * (1 - fx) + g[y1][:, x1] * fx
        out += amp * (a * (1 - fy[:, None]) + b * fy[:, None])
        total += amp
        amp *= persistence
    return out / total


def land_mask(w, h, cache):
    path = os.path.join(cache, "ne_50m_land.geojson")
    if not os.path.exists(path):
        try:
            os.makedirs(cache, exist_ok=True)
            print(T["downloading"])
            urllib.request.urlretrieve(LAND_URL, path + ".part")
            os.replace(path + ".part", path)
        except Exception:
            print(T["offline"])
            return np.zeros((h, w), np.float32)
    with open(path, encoding="utf-8") as f:
        gj = json.load(f)
    img = Image.new("L", (w, h), 0)
    dr = ImageDraw.Draw(img)

    def ring(coords):
        return [((lon + 180) / 360 * w, (90 - lat) / 180 * h) for lon, lat in coords]

    for feat in gj["features"]:
        geom = feat["geometry"]
        polys = geom["coordinates"] if geom["type"] == "MultiPolygon" else [geom["coordinates"]]
        for poly in polys:
            dr.polygon(ring(poly[0]), fill=255)
            for hole in poly[1:]:
                dr.polygon(ring(hole), fill=0)
    return np.asarray(img.filter(ImageFilter.GaussianBlur(0.8)), np.float32) / 255.0


def earth_textures(cache, w=2048, h=1024):
    land = land_mask(w, h, cache)
    lat = np.linspace(90, -90, h, endpoint=False)[:, None] - 90 / h
    lon = np.linspace(-180, 180, w, endpoint=False)[None, :] + 180 / w
    alat = np.abs(lat)
    n1 = periodic_noise(h, w, seed=1)
    n2 = periodic_noise(h, w, seed=2, base=8)

    # Land colours by climate band + noise
    tropical = np.array([0.13, 0.30, 0.10])
    desert = np.array([0.70, 0.58, 0.38])
    temperate = np.array([0.24, 0.38, 0.16])
    boreal = np.array([0.20, 0.30, 0.17])
    tundra = np.array([0.45, 0.44, 0.36])
    ice = np.array([0.93, 0.95, 0.98])
    arid = np.clip(np.exp(-((alat - 24) / 9) ** 2) * 1.2 + (n1 - 0.5) * 1.4, 0, 1)[..., None]
    col = tropical * (1 - arid) + desert * arid
    w_temp = np.clip((alat - 30) / 10, 0, 1)[..., None]
    col = col * (1 - w_temp) + (temperate * (1 - arid * 0.6) + desert * arid * 0.6) * w_temp
    w_bor = np.clip((alat - 50) / 8, 0, 1)[..., None]
    col = col * (1 - w_bor) + boreal * w_bor
    w_tun = np.clip((alat - 63) / 6, 0, 1)[..., None]
    col = col * (1 - w_tun) + tundra * w_tun
    greenland = (lat > 59) & (lon > -75) & (lon < -10)
    w_ice = np.clip((alat - 72 + (n2 - 0.5) * 8) / 4, 0, 1) + greenland * 0.95 + (lat < -60)
    w_ice = np.clip(w_ice, 0, 1)[..., None]
    col = col * (1 - w_ice) + ice * w_ice
    col *= (0.85 + 0.3 * n2)[..., None]

    # Oceans: lighter near the coast, sea ice near the poles
    coast = np.asarray(Image.fromarray((land * 255).astype(np.uint8))
                       .filter(ImageFilter.GaussianBlur(6)), np.float32) / 255.0
    deep = np.array([0.015, 0.075, 0.22])
    shallow = np.array([0.03, 0.20, 0.40])
    ocean = deep + (shallow - deep) * np.clip(coast * 2.2, 0, 1)[..., None]
    sea_ice = np.clip((alat - 76 + (n1 - 0.5) * 10) / 4, 0, 1)[..., None]
    ocean = ocean * (1 - sea_ice) + ice * 0.9 * sea_ice

    albedo = ocean * (1 - land[..., None]) + col * land[..., None]
    water = (1 - land) * (1 - sea_ice[..., 0])

    # Clouds: more in the tropics (ITCZ) and in mid-latitude storm tracks
    c = periodic_noise(h, w, seed=7, base=6, octaves=7, persistence=0.6)
    band = 0.55 + 0.45 * (np.exp(-(lat / 9) ** 2) + np.exp(-((alat - 55) / 13) ** 2))
    band -= 0.35 * np.exp(-((alat - 25) / 8) ** 2)
    clouds = np.clip((c * band - 0.33) * 3.0, 0, 0.85).astype(np.float32)
    return albedo.astype(np.float32), water.astype(np.float32), clouds


def city_lights(cache, w=2048, h=1024):
    """Night lights synthesised from ~7300 populated places (brightness grows with population)."""
    path = os.path.join(cache, "ne_10m_populated_places_simple.geojson")
    if not os.path.exists(path):
        try:
            os.makedirs(cache, exist_ok=True)
            urllib.request.urlretrieve(PLACES_URL, path + ".part")
            os.replace(path + ".part", path)
        except Exception:
            print(T["no_lights"])
            return np.zeros((h, w), np.float32)
    with open(path, encoding="utf-8") as f:
        feats = json.load(f)["features"]
    pts = np.zeros((h, w), np.float32)
    for ft in feats:
        pr = ft["properties"]
        pop = pr.get("pop_max") or 0
        if pop < 20000:
            continue
        lon, lat = ft["geometry"]["coordinates"][:2]
        x = int((lon + 180) / 360 * w) % w
        y = min(max(int((90 - lat) / 180 * h), 0), h - 1)
        pts[y, x] += (pop / 1e6) ** 0.6
    img = Image.fromarray(np.clip(pts * 255, 0, 255).astype(np.uint8))
    core = np.asarray(img.filter(ImageFilter.GaussianBlur(1.2)), np.float32) / 255
    glow = np.asarray(img.filter(ImageFilter.GaussianBlur(5)), np.float32) / 255
    lights = core * 6 + glow * 10
    return np.clip(lights, 0, 1).astype(np.float32)


def moon_texture(w=1024, h=512):
    lat = np.radians(np.linspace(90, -90, h, endpoint=False)[:, None] - 90 / h)
    lon = np.radians(np.linspace(-180, 180, w, endpoint=False)[None, :] + 180 / w)
    n1 = periodic_noise(h, w, seed=11, base=8, octaves=7)
    n2 = periodic_noise(h, w, seed=12, base=32, octaves=4, persistence=0.7)
    tex = 0.58 + (n1 - 0.5) * 0.18 + (n2 - 0.5) * 0.12
    # Near-side maria: (lat, lon, radius in degrees, darkness)
    maria = [(33, -16, 17, 0.20), (28, 17, 10, 0.20), (8, 31, 11, 0.21), (17, 59, 7, 0.22),
             (18, -57, 26, 0.17), (-21, -17, 10, 0.15), (-8, 51, 9, 0.17), (-15, 35, 6, 0.15),
             (56, 1, 8, 0.13), (-24, -39, 6, 0.16), (25, -30, 12, 0.12), (0, -10, 8, 0.10)]
    for la, lo, r, k in maria:
        la, lo = math.radians(la), math.radians(lo)
        d = np.degrees(np.arccos(np.clip(np.sin(lat) * math.sin(la)
                                         + np.cos(lat) * math.cos(la) * np.cos(lon - lo), -1, 1)))
        edge = r * (0.85 + 0.35 * n1)
        tex -= k * np.clip((edge - d) / (0.35 * r), 0, 1)
    # Bright young craters (Tycho, Copernicus, Kepler, Aristarchus)
    for la, lo, r in [(-43, -11, 2.2), (10, -20, 1.6), (8, -38, 1.0), (24, -47, 0.9)]:
        la, lo = math.radians(la), math.radians(lo)
        d = np.degrees(np.arccos(np.clip(np.sin(lat) * math.sin(la)
                                         + np.cos(lat) * math.cos(la) * np.cos(lon - lo), -1, 1)))
        tex += 0.25 * np.exp(-(d / r) ** 2) + 0.05 * np.exp(-(d / (r * 6)) ** 2)
    return np.clip(tex, 0.05, 1).astype(np.float32)


def star_map(w=4096, h=2048, n=9000, seed=3):
    rng = np.random.default_rng(seed)
    m = np.zeros((h, w), np.float32)
    z = rng.uniform(-1, 1, n)
    lon = rng.uniform(0, w, n).astype(int)
    lat = ((1 - (np.arcsin(z) / (math.pi / 2) + 1) / 2) * h).astype(int).clip(0, h - 1)
    m[lat, lon] = np.minimum(rng.pareto(2.2, n) * 0.18 + 0.12, 1.0)
    # faint Milky Way band (great circle inclined ~60° to the ecliptic)
    la = np.radians(np.linspace(90, -90, h)[:, None])
    lo = np.radians(np.linspace(-180, 180, w)[None, :])
    v = np.stack(np.broadcast_arrays(np.cos(la) * np.cos(lo), np.cos(la) * np.sin(lo), np.sin(la)), -1)
    pole = norm(np.array([0.0, -0.87, 0.5]))
    band = np.exp(-((v @ pole) / 0.18) ** 2) * (0.04 + 0.05 * periodic_noise(h, w, seed=5, base=16))
    return np.clip(m + band, 0, 1)


# ----------------------------------------------------------------------------
# Ray tracer
# ----------------------------------------------------------------------------
class Camera:
    def __init__(self, pos, target, fov, w, h, up=(0, 0, 1)):
        self.pos = np.asarray(pos, float)
        self.f = norm(np.asarray(target, float) - self.pos)
        self.r = norm(np.cross(self.f, np.asarray(up, float)))
        self.u = np.cross(self.r, self.f)
        self.th = math.tan(math.radians(fov) / 2)
        self.w, self.h = w, h

    def rays(self):
        xs = (np.arange(self.w) + 0.5 - self.w / 2) / (self.w / 2) * self.th
        ys = (self.h / 2 - np.arange(self.h) - 0.5) / (self.w / 2) * self.th
        d = (self.f[None, None] + xs[None, :, None] * self.r + ys[:, None, None] * self.u)
        return norm(d.reshape(-1, 3).astype(np.float32))

    def project(self, pts):
        v = pts - self.pos
        z = v @ self.f
        zs = np.where(z > 1e-6, z, 1e-6)
        x = (v @ self.r) / zs / self.th
        y = (v @ self.u) / zs / self.th
        return (self.w / 2 + x * self.w / 2, self.h / 2 - y * self.w / 2,
                z, np.linalg.norm(v, axis=-1))


def hit_sphere(o, d, c, r):
    oc = (o - c).astype(np.float32)
    b = d @ oc
    cc = float(oc @ oc - r * r)
    disc = b * b - cc
    t = np.full(len(d), np.inf, np.float32)
    m = disc > 0
    tt = -b[m] - np.sqrt(disc[m])
    idx = np.nonzero(m)[0]
    ok = tt > 1e-4
    t[idx[ok]] = tt[ok]
    closest = np.sqrt(np.maximum(float(oc @ oc) - b * b, 0))   # distance from centre to ray
    return t, b, closest


def disc_overlap(a, b, d):
    """Fraction of a disc of radius a (scalar) covered by discs of radius b at distance d."""
    b = np.asarray(b, np.float64)
    d = np.asarray(d, np.float64)
    out = np.zeros_like(d)
    full = d <= np.abs(a - b)
    out[full] = np.minimum(a, b[full]) ** 2 / a ** 2
    part = (~full) & (d < a + b)
    if part.any():
        bp, dp = b[part], np.maximum(d[part], 1e-12)
        c1 = np.clip((dp ** 2 + a ** 2 - bp ** 2) / (2 * dp * a), -1, 1)
        c2 = np.clip((dp ** 2 + bp ** 2 - a ** 2) / (2 * dp * bp), -1, 1)
        k = np.sqrt(np.maximum((-dp + a + bp) * (dp + a - bp) * (dp - a + bp) * (dp + a + bp), 0))
        area = a ** 2 * np.arccos(c1) + bp ** 2 * np.arccos(c2) - 0.5 * k
        out[part] = area / (math.pi * a ** 2)
    return np.clip(out, 0, 1).astype(np.float32)


def shadow_fraction(p, light_dir, occ_c, occ_r):
    """Fraction of the solar disc hidden by a sphere, seen from points p."""
    v = occ_c[None] - p
    dist = np.linalg.norm(v, axis=1)
    vd = v / dist[:, None]
    cosang = np.einsum("ij,ij->i", vd, light_dir)
    sep = np.arccos(np.clip(cosang, -1, 1))
    occ_ang = np.arcsin(np.clip(occ_r / dist, 0, 1))
    f = disc_overlap(SUN_ANG, occ_ang, sep)
    f[cosang <= 0] = 0
    return f


def sample(tex, lat, lon):
    h, w = tex.shape[:2]
    y = ((0.5 - lat / math.pi) * h).astype(int).clip(0, h - 1)
    x = (((lon / (2 * math.pi)) + 0.5) * w).astype(int) % w
    return tex[y, x]


class World:
    def __init__(self, cache):
        print(T["textures"])
        self.albedo, self.water, self.clouds = earth_textures(cache)
        self.lights = city_lights(cache)
        self.moon_tex = moon_texture()
        self.stars = star_map()


def render(world, cam, st, sun_r=SUN_R):
    """Ray-trace one image. st: frame state (positions, sizes, angles)."""
    o = cam.pos
    d = cam.rays()
    n = len(d)
    E, Re = st["E"], st["Re"]
    M, Rm = st["M"], st["Rm"]
    sun_c = np.zeros(3)

    stats = {"earth_shadow": 0.0}
    tE, bE, cE = hit_sphere(o, d, E, Re)
    tS, bS, cS = hit_sphere(o, d, sun_c, sun_r)
    if Rm > 0:
        tM, bM, cM = hit_sphere(o, d, M, Rm)
    else:
        tM = np.full(n, np.inf, np.float32)
    tmin = np.minimum(np.minimum(tE, tM), tS)
    col = np.zeros((n, 3), np.float32)

    # --- background: stars, Milky Way, Sun glow, Earth atmosphere halo ---
    bg = ~np.isfinite(tmin)
    db = d[bg]
    lat = np.arcsin(np.clip(db[:, 2], -1, 1))
    lon = np.arctan2(db[:, 1], db[:, 0])
    col[bg] = sample(world.stars, lat, lon)[:, None] * np.array([0.9, 0.93, 1.0])
    front = bS[bg] < 0
    g = np.exp(-np.maximum(cS[bg] - sun_r, 0) / (sun_r * 0.7)) * front
    col[bg] += g[:, None] * np.array([1.0, 0.78, 0.4]) * 0.75
    frontE = bE[bg] < 0
    halo = np.exp(-np.maximum(cE[bg] - Re, 0) / (0.045 * Re)) * frontE * (cE[bg] < 1.3 * Re)
    if halo.any():
        q = o + d[bg] * (-bE[bg])[:, None]
        nq = norm(q - E)
        lit = np.clip(nq @ st["sun_dir"] + 0.3, 0.12, 1)
        col[bg] += (halo * lit)[:, None] * np.array([0.30, 0.55, 1.0]) * 0.9

    # --- Sun ---
    m = (tS == tmin) & np.isfinite(tS)
    if m.any():
        p = o + d[m] * tS[m, None]
        mu = np.clip(np.einsum("ij,ij->i", norm(p - sun_c), -d[m]), 0, 1)
        col[m] = np.array([1.0, 0.86, 0.5]) * (0.62 + 0.38 * np.sqrt(mu))[:, None] * 1.25

    # --- Earth ---
    m = (tE == tmin) & np.isfinite(tE)
    if m.any():
        dm = d[m]
        p = o + dm * tE[m, None]
        nrm = (p - E) / Re
        L = norm(sun_c - p)
        ndl = np.einsum("ij,ij->i", nrm, L)
        q = nrm @ (rot_z(-st["theta"]) @ M_TILT.T).T          # Earth-fixed coordinates
        la = np.arcsin(np.clip(q[:, 2], -1, 1))
        lo = np.arctan2(q[:, 1], q[:, 0])
        alb = sample(world.albedo, la, lo)
        water = sample(world.water, la, lo)
        cl = sample(world.clouds, la, lo + st["cloud_shift"])
        alb = alb * (1 - cl[:, None]) + np.float32(0.95) * cl[:, None]
        light = np.clip(ndl, 0, 1)
        if Rm > 0:
            fsh = shadow_fraction(p, L, M, Rm) * (ndl > 0)
            stats["earth_shadow"] = float(fsh.max()) if len(fsh) else 0.0
            light = light * (1 - fsh)
        view = -dm
        refl = 2 * ndl[:, None] * nrm - L
        spec = np.clip(np.einsum("ij,ij->i", refl, view), 0, 1) ** 30 * 0.55 * water * (1 - cl) * light
        twilight = np.exp(-((ndl - 0.03) / 0.06) ** 2) * (light > 0) * 0.12
        rim = (1 - np.clip(np.einsum("ij,ij->i", nrm, view), 0, 1)) ** 3 * np.clip(ndl + 0.25, 0.12, 1)
        c = alb * (light * 1.25 + 0.05)[:, None]
        # city lights on the night side (dimmed by clouds)
        night = np.clip((0.02 - ndl) / 0.12, 0, 1)
        lights = sample(world.lights, la, lo) * night * (1 - 0.75 * cl)
        c += lights[:, None] * np.array([1.0, 0.70, 0.32]) * 0.95
        c += spec[:, None] * np.array([1.0, 0.95, 0.85])
        c += twilight[:, None] * np.array([0.9, 0.35, 0.1]) * alb.mean(1, keepdims=True) * 3
        c += rim[:, None] * np.array([0.25, 0.45, 0.95]) * 0.55
        col[m] = c

    # --- Moon ---
    if Rm > 0:
        m = (tM == tmin) & np.isfinite(tM)
        if m.any():
            p = o + d[m] * tM[m, None]
            nrm = (p - M) / Rm
            L = norm(sun_c - p)
            ndl = np.clip(np.einsum("ij,ij->i", nrm, L), 0, 1)
            loc = nrm @ st["moon_axes"].T
            alb = sample(world.moon_tex, np.arcsin(np.clip(loc[:, 2], -1, 1)),
                         np.arctan2(loc[:, 1], loc[:, 0]))
            f = shadow_fraction(p, L, E, Re)
            lit = ndl * (1 - f)
            red = ndl * f                                     # light bent by Earth's atmosphere
            c = alb[:, None] * (lit[:, None] * 1.3 + 0.012) * np.ones(3, np.float32)
            c += alb[:, None] * red[:, None] * np.array([0.42, 0.10, 0.04])
            # earthshine: sunlight reflected by the Earth lights the Moon's night side
            to_e = norm(E - p)
            earth_phase = 0.5 * (1 + float(norm(M - E) @ st["sun_dir"]))
            ndE = np.clip(np.einsum("ij,ij->i", nrm, to_e), 0, 1)
            c += alb[:, None] * (ndE * earth_phase * 0.11)[:, None] * np.array([0.75, 0.85, 1.0])
            col[m] = c

    col = np.clip(col, 0, 1) ** (1 / 1.1)
    render.stats = stats
    return col.reshape(cam.h, cam.w, 3), tmin.reshape(cam.h, cam.w)


# ----------------------------------------------------------------------------
# Overlays (depth-tested 3D lines, text)
# ----------------------------------------------------------------------------
def draw_line3d(img, zbuf, cam, pts, color, alpha, width=1, dash=0):
    if alpha <= 0.01:
        return
    px, py, z, dist = cam.project(pts)
    ix, iy = np.round(px).astype(int), np.round(py).astype(int)
    ok = (z > 0.05) & (ix >= 0) & (ix < cam.w) & (iy >= 0) & (iy < cam.h)
    if dash:
        ok &= (np.arange(len(pts)) // dash) % 2 == 0
    ix, iy, dist = ix[ok], iy[ok], dist[ok]
    vis = dist < zbuf[iy, ix] * 0.999
    ix, iy = ix[vis], iy[vis]
    col = np.asarray(color, np.float32)
    for dx, dy in [(0, 0), (1, 0), (0, 1), (1, 1)][: (1 if width == 1 else 4)]:
        jx, jy = np.clip(ix + dx, 0, cam.w - 1), np.clip(iy + dy, 0, cam.h - 1)
        img[jy, jx] = img[jy, jx] * (1 - alpha) + col * alpha


def circle_pts(center, radius, normal, n=6000):
    normal = norm(np.asarray(normal, float))
    a = norm(np.cross(normal, [1, 0, 0] if abs(normal[0]) < 0.9 else [0, 1, 0]))
    b = np.cross(normal, a)
    ang = np.linspace(0, 2 * math.pi, n)[:, None]
    return center + radius * (np.cos(ang) * a + np.sin(ang) * b)


def line_pts(p0, p1, n=400):
    s = np.linspace(0, 1, n)[:, None]
    return p0 + (p1 - p0) * s


class Fonts:
    def __init__(self, scale):
        reg = bold = None
        try:
            import matplotlib
            base = os.path.join(matplotlib.get_data_path(), "fonts", "ttf")
            reg, bold = os.path.join(base, "DejaVuSans.ttf"), os.path.join(base, "DejaVuSans-Bold.ttf")
        except Exception:
            pass

        def load(path, size):
            try:
                return ImageFont.truetype(path or "DejaVuSans.ttf", size)
            except Exception:
                try:
                    return ImageFont.truetype("arial.ttf", size)
                except Exception:
                    return ImageFont.load_default(size)

        s = scale
        self.title = load(bold, int(22 * s))
        self.sub = load(reg, int(13 * s))
        self.info = load(bold, int(15 * s))
        self.small = load(reg, int(11 * s))
        self.label = load(bold, int(12 * s))


def text(draw, xy, s, font, fill=(255, 255, 255), anchor="la", stroke=2):
    draw.text(xy, s, font=font, fill=fill, anchor=anchor, stroke_width=stroke,
              stroke_fill=(0, 0, 0))


# ----------------------------------------------------------------------------
# Timeline: segments with camera/scene states
# ----------------------------------------------------------------------------
STATES = {
    "close":     dict(cam=(6.6, 60, "rel", 18, 38, 0.0), es=1.0, mr=0.0, mo=0.0, eo=0.0, rays=1.0, geo=1.0),
    "moonwide":  dict(cam=(30, 75, "rel", 30, 40, 0.0), es=1.8, mr=MOON_R, mo=0.75, eo=0.0, rays=0.0),
    "moonwide2": dict(cam=(30, 112, "rel", 30, 40, 0.0), es=1.8, mr=MOON_R, mo=0.75, eo=0.0, rays=0.0),
    "eclipse":   dict(cam=(4.6, 34, "rel", 14, 38, 0.0), es=1.0, mr=MOON_R, mo=0.4, eo=0.0, rays=0.0),
    "eclipse2":  dict(cam=(4.6, 20, "rel", 12, 38, 0.0), es=1.0, mr=MOON_R, mo=0.4, eo=0.0, rays=0.0),
    "moonwide3": dict(cam=(30, 120, "rel", 30, 40, 0.0), es=1.8, mr=MOON_R, mo=0.75, eo=0.0, rays=0.0),
    "moonwide4": dict(cam=(30, 150, "rel", 30, 40, 0.0), es=1.8, mr=MOON_R, mo=0.75, eo=0.0, rays=0.0),
    "explain":   dict(cam=(28, 90, "rel", 7, 44, 0.0), es=1.0, mr=MOON_R, mo=0.8, eo=0.0, rays=0.0,
                      inc=DEMO_INC, xp=1.0),
    "explain2":  dict(cam=(28, 105, "rel", 9, 44, 0.0), es=1.0, mr=MOON_R, mo=0.8, eo=0.0, rays=0.0,
                      inc=DEMO_INC, xp=1.0),
    "solar":     dict(cam=(270, -100, "abs", 30, 44, 1.0), es=3.9, mr=0.0, mo=0.0, eo=0.7, rays=0.0, shift=22.0),
}

# (scene, seconds, t0, t1, state_a, state_b, title, inset, illustrative_rotation)
SEGMENTS = [
    (1, 12.0, 0.0, 1.0, "close", "close", "t1", None, False),
    (2, 3.0, 1.0, T_MOON, "close", "moonwide", "t2", None, False),
    (2, 9.0, T_MOON, T_NEW - 0.35, "moonwide", "moonwide2", "t2", "moon", False),
    (2, 2.5, T_NEW - 0.35, T_NEW - 0.2, "moonwide2", "eclipse", "t2e", "moon", False),
    (2, 7.0, T_NEW - 0.2, T_NEW + 0.2, "eclipse", "eclipse2", "t2e", "moon", False),
    (2, 2.5, T_NEW + 0.2, T_NEW + 0.35, "eclipse2", "moonwide3", "t2", "moon", False),
    (2, 8.0, T_NEW + 0.35, T_MOON + SYNODIC, "moonwide3", "moonwide4", "t2", "moon", False),
    (2, 4.0, T_MOON + SYNODIC, T_MOON + SYNODIC + 3, "moonwide4", "explain", "tx", "moon", False),
    (2, 5.0, T_MOON + SYNODIC + 3, T_SEP - 0.6, "explain", "explain", "tx", "moon", False),
    (2, 5.0, T_SEP - 0.6, T_SEP + 0.6, "explain", "explain", "tx", "moon", False),
    (2, 6.0, T_SEP + 0.6, T_JAN - 0.6, "explain", "explain2", "tx", "moon", False),
    (2, 5.0, T_JAN - 0.6, T_JAN + 0.6, "explain2", "explain2", "tx", "moon", False),
    (3, 4.0, T_JAN + 0.6, T_ACT3, "explain2", "solar", "t3", None, True),
    (3, 22.0, T_ACT3, T_ACT3 + YEAR, "solar", "solar", "t3", "season", True),
    (3, 2.0, T_ACT3 + YEAR, T_ACT3 + YEAR, "solar", "solar", "t3", "season", True),
]


def boundary_speeds():
    """Speed (days per second) at each segment boundary, continuous on both sides.
    Clamped to ≤2.1× the slower neighbour so the time curve never goes backwards."""
    rates = [(t1 - t0) / dur if dur else 0.0 for _, dur, t0, t1, *_ in SEGMENTS]
    v = [rates[0]]
    for a, b in zip(rates[:-1], rates[1:]):
        v.append(min(math.sqrt(a * b), 2.1 * min(a, b)))
    v.append(rates[-1])
    return v


SPEEDS = None


def segment_time(i, s):
    """Time (days) and speed (days/s) inside segment i at fraction s (cubic Hermite)."""
    global SPEEDS
    if SPEEDS is None:
        SPEEDS = boundary_speeds()
    _, dur, t0, t1, *_ = SEGMENTS[i]
    if not dur or t1 == t0:
        return t0, 0.0
    m0, m1 = SPEEDS[i] * dur, SPEEDS[i + 1] * dur
    s2, s3 = s * s, s * s * s
    t = (2 * s3 - 3 * s2 + 1) * t0 + (s3 - 2 * s2 + s) * m0 + (-2 * s3 + 3 * s2) * t1 + (s3 - s2) * m1
    dt = (6 * s2 - 6 * s) * t0 + (3 * s2 - 4 * s + 1) * m0 + (-6 * s2 + 6 * s) * t1 + (3 * s2 - 2 * s) * m1
    return t, dt / dur


def lerp(a, b, s):
    return a + (b - a) * s


def camera_params(state, t):
    dist, az, mode, el, fov, tw = state["cam"]
    az = math.radians(az)
    if mode == "rel":
        s = sun_dir(t)
        az += math.atan2(s[1], s[0])
    return dist, az, math.radians(el), fov, tw


def frame_state(seg, s, theta, w_illus):
    _, dur, t0, t1, a, b, title, inset, _ = seg
    sa, sb = STATES[a], STATES[b]
    k = smoothstep(s) if a != b else s
    t, rate = segment_time(SEGMENTS.index(seg), s)
    da, aza, ela, fa, twa = camera_params(sa, t)
    db, azb, elb, fb, twb = camera_params(sb, t)
    daz = (azb - aza + math.pi) % (2 * math.pi) - math.pi
    # distance interpolated in log space: smooth zoom
    dist = math.exp(lerp(math.log(da), math.log(db), k))
    az, el, fov, tw = aza + daz * k, lerp(ela, elb, k), lerp(fa, fb, k), lerp(twa, twb, k)
    E = earth_pos(t)
    target = E * (1 - tw)
    # shift the view sideways (keeps the orbit clear of the inset on the right)
    shift = lerp(sa.get("shift", 0.0), sb.get("shift", 0.0), k)
    target = target + shift * np.array([-math.sin(az), math.cos(az), 0.0])
    pos = target + dist * np.array([math.cos(el) * math.cos(az), math.cos(el) * math.sin(az), math.sin(el)])
    es = lerp(sa["es"], sb["es"], k)
    mr = lerp(sa["mr"], sb["mr"], k)
    inc = math.radians(lerp(sa.get("inc", 5.14), sb.get("inc", 5.14), k))
    rel, axes, elong = moon_state(t, MOON_DIST, inc)
    return dict(
        t=t, E=E, Re=EARTH_R * es, M=E + rel, Rm=mr * es, moon_axes=axes, elong=elong,
        theta=theta, sun_dir=sun_dir(t), cloud_shift=-0.15 * t,
        cam=(pos, target, fov), mo=lerp(sa["mo"], sb["mo"], k), eo=lerp(sa["eo"], sb["eo"], k),
        rays=lerp(sa["rays"], sb["rays"], k), title=title, inset=inset, illus=w_illus > 0.5,
        xp=lerp(sa.get("xp", 0.0), sb.get("xp", 0.0), k), inc=inc,
        geo=lerp(sa.get("geo", 0.0), sb.get("geo", 0.0), k),
        rate=rate, scene=seg[0])


# ----------------------------------------------------------------------------
# Insets and HUD
# ----------------------------------------------------------------------------
def moon_inset(world, st, size):
    E, M, Rm = st["E"], st["M"], st["Rm"]
    dist = np.linalg.norm(M - E)
    fov = math.degrees(2 * math.atan(Rm / dist) / 0.72)
    cam = Camera(E, M, fov, size, size, up=(0, 0, -1) if HEMI_SOUTH else (0, 0, 1))
    sun_r = np.linalg.norm(E) * math.tan(SUN_ANG)      # real apparent size of the Sun
    img, _ = render(world, cam, st, sun_r=sun_r)
    return img


LINE_STYLES = [(0.0, (1.0, 1.0, 1.0), 0.55), (TILT, (1.0, 0.82, 0.3), 0.8), (-TILT, (1.0, 0.82, 0.3), 0.8),
               (math.pi / 2 - TILT, (0.5, 0.85, 1.0), 0.8), (-(math.pi / 2 - TILT), (0.5, 0.85, 1.0), 0.8)]


def draw_reference_lines(img, zb, cam, E, Re, alpha, n=2500):
    """Equator, tropics and polar circles (latitude circles do not depend on the rotation)."""
    for lat, col, a in LINE_STYLES:
        c = E + EARTH_AXIS * Re * math.sin(lat) * 1.004
        draw_line3d(img, zb, cam, circle_pts(c, Re * math.cos(lat) * 1.004, EARTH_AXIS, n),
                    col, a * alpha, dash=0 if lat else 14)


def surface_point(st, lat, lon):
    q = np.array([math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)])
    n = M_TILT @ rot_z(st["theta"]) @ q
    return st["E"] + n * st["Re"] * 1.003, n


def marker(dr, cam, zb, p, ox=0, oy=0, tol=1.02):
    """Screen position of a 3D point if it is not hidden by a sphere, else None."""
    px, py, z, dist = cam.project(p[None])
    x, y = float(px[0]), float(py[0])
    if z[0] <= 0 or not (0 <= x < cam.w and 0 <= y < cam.h):
        return None
    if dist[0] > zb[int(y), int(x)] * tol:
        return None
    return x + ox, y + oy


def sun_elevation_day(t, lat, lon):
    """Sun elevation (degrees) at a place over the UTC day containing t (model geometry)."""
    day0 = math.floor(t)
    hours = np.linspace(0, 24, 145)
    q = np.array([math.cos(lat) * math.cos(lon), math.cos(lat) * math.sin(lon), math.sin(lat)])
    el = []
    for hh in hours:
        tt = day0 + hh / 24
        n = M_TILT @ rot_z(earth_rotation(tt)) @ q
        el.append(math.degrees(math.asin(np.clip(n @ sun_dir(tt), -1, 1))))
    return hours, np.array(el)


def day_length(t, lat):
    s_eq = M_TILT.T @ sun_dir(t)
    dec = math.asin(np.clip(s_eq[2], -1, 1))
    c = (math.sin(math.radians(-0.833)) - math.sin(lat) * math.sin(dec)) / (math.cos(lat) * math.cos(dec))
    return 2 * math.degrees(math.acos(min(max(c, -1), 1))) / 15


TWILIGHT_COLORS = [(-90, -18, (46, 66, 77)), (-18, -12, (87, 103, 111)), (-12, -6, (107, 141, 152)),
                   (-6, -0.833, (147, 188, 203)), (-0.833, 90, (176, 217, 230))]


def draw_chart(dr, box, xs, ys, xr, yr, fonts, sc, title, xticks, yticks, marker_x=None,
               bands=None, fill=None, curve=(232, 25, 28)):
    x0, y0, x1, y1 = box
    X = lambda v: x0 + (v - xr[0]) / (xr[1] - xr[0]) * (x1 - x0)
    Y = lambda v: y1 - (v - yr[0]) / (yr[1] - yr[0]) * (y1 - y0)
    dr.rectangle(box, fill=(14, 18, 28))
    for lo, hi, col in bands or []:
        dr.rectangle([x0, Y(min(hi, yr[1])), x1, Y(max(lo, yr[0]))], fill=col)
    if fill:
        poly = [(X(xs[0]), Y(yr[0]))] + [(X(a), Y(b)) for a, b in zip(xs, ys)] + [(X(xs[-1]), Y(yr[0]))]
        dr.rectangle(box, fill=fill[1])
        dr.polygon(poly, fill=fill[0])
    pts = [(X(a), Y(min(max(b, yr[0]), yr[1]))) for a, b in zip(xs, ys)]
    dr.line(pts, fill=curve, width=max(2, int(2 * sc)))
    if marker_x is not None:
        mx = X(marker_x)
        my = Y(float(np.interp(marker_x, xs, ys)))
        dr.line([(mx, y0), (mx, y1)], fill=(255, 255, 255), width=1)
        r = 4 * sc
        dr.ellipse([mx - r, my - r, mx + r, my + r], fill=curve, outline=(255, 255, 255))
    dr.rectangle(box, outline=(120, 120, 130))
    for v, lab in xticks:
        text(dr, (X(v), y1 + 3 * sc), lab, fonts.small, (200, 200, 200), anchor="ma", stroke=1)
    for v, lab in yticks:
        text(dr, (x0 - 4 * sc, Y(v)), lab, fonts.small, (200, 200, 200), anchor="rm", stroke=1)
    text(dr, ((x0 + x1) / 2, y0 - 4 * sc), title, fonts.label, anchor="md")


def draw_line_legend(dr, x, y, fonts, sc):
    items = [(T["legend_eq"], (255, 255, 255)), (T["legend_trop"], (255, 209, 77)),
             (T["legend_polar"], (128, 217, 255))]
    for name, col in items:
        dr.line([(x, y), (x + 16 * sc, y)], fill=col, width=max(2, int(2 * sc)))
        text(dr, (x + 21 * sc, y), name, fonts.small, (220, 220, 220), anchor="lm", stroke=1)
        y += 15 * sc


def season_inset(world, st, size):
    E, Re = st["E"], st["Re"]
    s = st["sun_dir"]
    side = norm(np.cross(s, [0, 0, 1]))
    cam = Camera(E + side * Re * 5.2, E, 30, size, size)
    sub = dict(st, Rm=0.0)
    img, zb = render(world, cam, sub)
    ax = EARTH_AXIS
    draw_reference_lines(img, zb, cam, E, Re, 1.0, 1200)
    draw_line3d(img, zb, cam, line_pts(E - ax * Re * 1.45, E + ax * Re * 1.45, 300),
                (1, 1, 1), 0.85, width=2)
    sun_px = cam.project((E + s * Re * 3)[None])[0][0]
    return img, sun_px < size / 2, cam, zb


def season_names(t):
    ls = solar_longitude(t)
    i = int(ls // 90) % 4                       # 0 spring(N) 1 summer 2 autumn 3 winter
    return T["seasons"][i], T["seasons"][(i + 2) % 4]


def phase_name(elong):
    i = int(((math.degrees(elong) + 22.5) % 360) // 45)
    return T["phases"][i]


def solar_eclipse_now(st):
    rel = st["M"] - st["E"]
    s = st["sun_dir"]
    along = rel @ s
    perp = np.linalg.norm(rel - along * s)
    pen = st["Rm"] + (along - st["Re"]) * math.tan(SUN_ANG)
    return along > 0 and perp < st["Re"] + pen


def lunar_eclipse_now(st):
    f = shadow_fraction(st["M"][None], norm(-st["M"])[None], st["E"], st["Re"])[0]
    return f > 0.3


def compose(world, st, fonts, w, h):
    pos, target, fov = st["cam"]
    cam = Camera(pos, target, fov, w, h)
    img, zb = render(world, cam, st)
    shadow_visible = render.stats["earth_shadow"] > 0.3      # Moon's shadow seen on the day side
    E, Re = st["E"], st["Re"]

    # 3D guides
    if st["eo"] > 0:
        orbit = np.array([earth_pos(x) for x in np.linspace(0, YEAR, 9000)])
        draw_line3d(img, zb, cam, orbit, (0.55, 0.75, 1.0), 0.45 * st["eo"])
    if st["mo"] > 0 and st["Rm"] > 0:
        rel = st["M"] - E
        nrm = np.cross(rel, st["moon_axes"][1])
        draw_line3d(img, zb, cam, circle_pts(E, np.linalg.norm(rel), nrm, 7000),
                    (0.8, 0.8, 0.85), 0.35 * st["mo"])
    draw_line3d(img, zb, cam, line_pts(E - EARTH_AXIS * Re * 1.45, E + EARTH_AXIS * Re * 1.45, 500),
                (1.0, 1.0, 1.0), 0.75, width=2)
    geo = st["geo"]
    if geo > 0.02:
        draw_reference_lines(img, zb, cam, E, Re, geo)
    xp_labels = []
    if st["xp"] > 0.01:
        xp = st["xp"]
        node = math.atan2(*sun_dir(T_NEW)[1::-1])
        nd = np.array([math.cos(node), math.sin(node), 0.0])
        perp = np.array([-nd[1], nd[0], 0.0])
        draw_line3d(img, zb, cam, circle_pts(E, 12.5, [0, 0, 1], 8000), (0.45, 0.65, 1.0), 0.55 * xp, dash=40)
        draw_line3d(img, zb, cam, line_pts(E - nd * 13, E + nd * 13, 2500), (1.0, 0.55, 0.85), 0.9 * xp, width=2)
        s_dir = st["sun_dir"]
        draw_line3d(img, zb, cam, line_pts(st["M"], st["M"] - s_dir * 15, 2500), (1.0, 0.55, 0.15),
                    0.85 * xp, width=2, dash=25)
        rel = st["M"] - E
        top = norm(np.cross(np.cross(rel, st["moon_axes"][1]), [0, 0, 1]))   # orbit high point direction
        xp_labels = [(E + nd * 13.6, T["node_line"], (255, 160, 220)),
                     (E + perp * 12.9, T["ecliptic"], (140, 180, 255)),
                     (st["M"] - s_dir * 4.5 + np.array([0, 0, 0.9]), T["moon_shadow"], (255, 170, 80))]
    if st["rays"] > 0:
        s = st["sun_dir"]
        a = norm(np.cross(s, [0, 0, 1])); b = np.cross(a, s)
        for ox, oy in [(-0.75, 0.3), (-0.3, -0.5), (0.2, 0.55), (0.6, -0.2), (0.0, 0.0), (0.45, 0.7), (-0.6, -0.75)]:
            off = (ox * a + oy * b) * Re
            depth = math.sqrt(max(Re * Re - ox * ox - oy * oy, 0))
            end = E + off + s * depth
            draw_line3d(img, zb, cam, line_pts(end + s * 9 * Re, end, 900),
                        (1.0, 0.85, 0.35), 0.7 * st["rays"], width=2, dash=18)

    out = Image.fromarray((img * 255).astype(np.uint8))
    dr = ImageDraw.Draw(out)
    sc = w / 960
    m = int(16 * sc)

    sun_mark = lambda x, y, r: dr.ellipse([x - r, y - r, x + r, y + r], outline=(255, 220, 80),
                                          width=max(2, int(2 * sc)))
    if geo > 0.5:
        # sub-solar point and reference city on the globe
        pos_s = marker(dr, cam, zb, E + st["sun_dir"] * Re * 1.003)
        if pos_s:
            sun_mark(pos_s[0], pos_s[1], 6 * sc)
            text(dr, (pos_s[0], pos_s[1] - 9 * sc), T["subsolar"], fonts.label, (255, 220, 80), anchor="md")
        name, clat, clon = CITY
        pc, _ = surface_point(st, math.radians(clat), math.radians(clon))
        pos_c = marker(dr, cam, zb, pc)
        if pos_c:
            r = 4 * sc
            dr.ellipse([pos_c[0] - r, pos_c[1] - r, pos_c[0] + r, pos_c[1] + r], fill=(232, 25, 28),
                       outline=(255, 255, 255))
            text(dr, (pos_c[0] + 7 * sc, pos_c[1]), name, fonts.label, anchor="lm")
        # Sun elevation chart for the city over this UTC day
        hours, el = sun_elevation_day(st["t"], math.radians(clat), math.radians(clon))
        cw, ch = int(250 * sc), int(120 * sc)
        bx = [w - m - cw, m + int(78 * sc), w - m, m + int(78 * sc) + ch]
        draw_chart(dr, bx, hours, el, (0, 24), (-70, 90), fonts, sc,
                   T["elev_chart"].format(city=name, date=date_label(st["t"]).split(" · ")[0]),
                   [(v, f"{v:02d}h") for v in (0, 6, 12, 18, 24)], [(0, "0°"), (45, "45°"), (90, "90°")],
                   marker_x=(st["t"] % 1) * 24, bands=TWILIGHT_COLORS)
        draw_line_legend(dr, bx[0], bx[3] + 28 * sc, fonts, sc)

    for p3, name, colr in xp_labels:
        px, py, z, _ = cam.project(p3[None])
        if z[0] > 0 and 0 < px[0] < w and 0 < py[0] < h:
            text(dr, (float(px[0]), float(py[0])), name, fonts.label, colr, anchor="mm")
    if st["xp"] > 0.5:
        elong = (math.degrees(st["elong"]) + 180) % 360 - 180
        if abs(elong) < 25:
            rel = st["M"] - E
            msg = T["hit"] if solar_eclipse_now(st) else (T["miss_above"] if rel[2] > 0 else T["miss_below"])
            text(dr, (w / 2, h - m - int(40 * sc)), msg, fonts.info, (255, 210, 120), anchor="md")

    # Perihelion / aphelion (act 3)
    if st["eo"] > 0.6:
        # labels placed towards the inside of the orbit (clear of the season labels)
        for tt, name in [(T_PERI + YEAR, T["perihelion"]), (T_PERI + YEAR / 2, T["aphelion"])]:
            px, py, z, _ = cam.project(np.stack([earth_pos(tt), np.zeros(3)]))
            if z[0] > 0:
                x, y = float(px[0]), float(py[0])
                inward = px[1] > x
                dr.ellipse([x - 3 * sc, y - 3 * sc, x + 3 * sc, y + 3 * sc], fill=(255, 190, 120))
                parts = name.split(" · ")
                for li, line in enumerate([" · ".join(parts[:2]), " · ".join(parts[2:])]):
                    text(dr, (x + (10 if inward else -10) * sc, y + (22 + 13 * li) * sc), line, fonts.small,
                         (255, 205, 150), anchor="lm" if inward else "rm")

    # Season labels on the orbit (act 3)
    if st["eo"] > 0.6:
        for i, name in enumerate(T["points"]):
            p = earth_pos(time_of_longitude(i * 90, 0.0))
            px, py, z, _ = cam.project(p[None])
            if z[0] > 0:
                x, y = float(px[0]), float(py[0])
                dr.ellipse([x - 3 * sc, y - 3 * sc, x + 3 * sc, y + 3 * sc], fill=(140, 190, 255))
                text(dr, (x, y - 8 * sc), name, fonts.label, (190, 215, 255), anchor="md")

    # Titles
    text(dr, (m, m), T[st["title"]], fonts.title)
    sub_key = "s" + st["title"][1:]
    if sub_key == "s3" and st["t"] > T_ACT3 + YEAR * 0.45:
        sub_key = "s3b"
    text(dr, (m, m + int(30 * sc)), T[sub_key], fonts.sub, (215, 215, 215))
    # Date / speed
    rate = st["rate"]
    if rate < 1e-4:
        rate_s = ""
    elif rate < 2:
        rate_s = T["rate_h"].format(v=num(rate * 24, 1 if rate * 24 < 10 else 0))
    else:
        rate_s = T["rate_d"].format(v=num(rate, 0 if rate >= 10 else 1))
    info = date_label(st["t"]) if not st["illus"] else date_label(st["t"]).split(" · ")[0]
    text(dr, (m, h - m - int(20 * sc)), info, fonts.info, anchor="ld")
    text(dr, (m, h - m), rate_s + ("   · " + T["illustrative"] if st["illus"] else ""),
         fonts.small, (200, 200, 200), anchor="ld")
    text(dr, (w - m, h - m), T["not_scale"], fonts.small, (170, 170, 170), anchor="rd")

    # Insets
    isz = int(190 * sc)
    if st["inset"] == "moon" and st["Rm"] > 0:
        im = moon_inset(WORLD, st, isz)
        x0, y0 = w - isz - m, m + int(72 * sc)
        out.paste(Image.fromarray((im * 255).astype(np.uint8)), (x0, y0))
        dr.rectangle([x0 - 1, y0 - 1, x0 + isz, y0 + isz], outline=(120, 120, 130))
        text(dr, (x0 + isz / 2, y0 - 4 * sc), T["moon_inset"], fonts.label, anchor="md")
        day = ((st["t"] - T_NEW) % SYNODIC)
        text(dr, (x0 + isz / 2, y0 + isz + 6 * sc), phase_name(st["elong"]), fonts.info, anchor="ma")
        text(dr, (x0 + isz / 2, y0 + isz + 26 * sc), T["cycle_day"].format(d=num(day, 1)),
             fonts.small, (200, 200, 200), anchor="ma")
        if lunar_eclipse_now(st):
            text(dr, (x0 + isz / 2, y0 + isz + 44 * sc), T["lunar_ecl"], fonts.info, (255, 120, 80), anchor="ma")
        if shadow_visible and st["xp"] < 0.5:
            text(dr, (w / 2, h - m - int(40 * sc)), T["solar_ecl"], fonts.title, (255, 200, 90), anchor="md")
    elif st["inset"] == "season":
        im, sun_left, icam, izb = season_inset(WORLD, st, isz)
        x0, y0 = w - isz - m, m + int(72 * sc)
        out.paste(Image.fromarray((im * 255).astype(np.uint8)), (x0, y0))
        pos_s = marker(dr, icam, izb, E + st["sun_dir"] * Re * 1.01, x0, y0, tol=1.5)
        if pos_s:
            sun_mark(pos_s[0], pos_s[1], 5 * sc)
        dr.rectangle([x0 - 1, y0 - 1, x0 + isz, y0 + isz], outline=(120, 120, 130))
        text(dr, (x0 + isz / 2, y0 - 4 * sc), T["season_inset"], fonts.label, anchor="md")
        arrow = ("← " + T["sun"]) if sun_left else (T["sun"] + " →")
        text(dr, (x0 + (8 * sc if sun_left else isz - 8 * sc), y0 + isz - 8 * sc), arrow,
             fonts.label, (255, 215, 110), anchor="ld" if sun_left else "rd")
        n_season, s_season = season_names(st["t"])
        text(dr, (x0 + isz / 2, y0 + isz + 8 * sc), f"{T['north']}: {n_season}", fonts.label, anchor="ma")
        text(dr, (x0 + isz / 2, y0 + isz + 26 * sc), f"{T['south']}: {s_season}", fonts.label, anchor="ma")
        # Day length over the calendar year for the reference city
        name, clat, _ = CITY
        t_jan1 = 194.0                                   # 1 Jan 2027 (days since 21 Jun 2026)
        days = np.arange(0, 366, 3)
        dl = [day_length(t_jan1 + d, math.radians(clat)) for d in days]
        cw, ch = isz, int(95 * sc)
        by = y0 + isz + int(72 * sc)
        bx = [x0, by, x0 + cw, by + ch]
        initials = [mo[0].upper() for mo in T["months"]]
        draw_chart(dr, bx, days, dl, (0, 365), (0, 24), fonts, sc,
                   T["daylen_chart"].format(city=name),
                   [(int(i * 30.4 + 15), initials[i]) for i in range(0, 12, 2)],
                   [(0, "0h"), (12, "12h"), (24, "24h")],
                   marker_x=(st["t"] - t_jan1) % 365.25,
                   fill=((176, 217, 230), (46, 66, 77)), curve=(255, 214, 110))
        draw_line_legend(dr, x0 - 165 * sc, by + 18 * sc, fonts, sc)
    return out


# ----------------------------------------------------------------------------
def build_frames(fps, speed, scenes, step):
    """List of (segment, fraction, displayed rotation angle, illustrative weight).

    When time runs faster than ~1 day per second the real rotation would
    strobe (it would even seem to turn backwards), so the Earth then spins
    at a slow illustrative rate; it blends back to the true angle whenever
    time slows down again (e.g. for the eclipses)."""
    frames = []
    fake = None
    spin = 2 * math.pi * 0.4 / fps
    for i, seg in enumerate(SEGMENTS):
        n = max(1, int(round(seg[1] / speed * fps)))
        for j in range(n):
            s = j / n
            t, rate = segment_time(i, s)
            true = earth_rotation(t)
            w = min(max((rate * speed - 1.0) / 1.5, 0.0), 1.0)
            if fake is None or w == 0:
                fake = true
            else:
                fake += spin
            diff = (fake - true + math.pi) % (2 * math.pi) - math.pi
            if seg[0] in scenes:
                frames.append((seg, s, true + diff * w, w))
    return frames[::step]


WORLD = None


def main():
    global T, WORLD
    p = argparse.ArgumentParser(description="Animated Earth–Moon–Sun model (rotation, phases, eclipse, seasons).")
    p.add_argument("--output", "-o", default="earth_moon_sun.mp4", help="video file (.mp4) (default: %(default)s)")
    p.add_argument("--width", type=int, default=960)
    p.add_argument("--height", type=int, default=540)
    p.add_argument("--fps", type=int, default=30)
    p.add_argument("--speed", type=float, default=1.0, help="playback speed factor (2 = half the duration)")
    p.add_argument("--scenes", default="1,2,3", help="acts to include, e.g. '2' or '1,3' (default: all)")
    p.add_argument("--lang", choices=list(TEXTS), help="language of the texts (default: system language)")
    p.add_argument("--step", type=int, default=1, help="render only every N-th frame (quick preview)")
    p.add_argument("--show", action="store_true", help="also show the frames in a window while rendering")
    p.add_argument("--city", default="Lisboa",
                   help="reference city: a known name (e.g. Lisboa, Porto, 'São Paulo') or 'lat,lon,name'")
    p.add_argument("--hemisphere", choices=["auto", "north", "south"], default="auto",
                   help="how the Moon phases are shown (default: from the city latitude)")
    p.add_argument("--cache", default=os.path.join(os.path.expanduser("~"), ".cache", "earth_moon_sun"))
    a = p.parse_args()

    global CITY, HEMI_SOUTH
    T = TEXTS[a.lang or system_language()]
    CITY = parse_city(a.city)
    HEMI_SOUTH = (a.hemisphere == "south") or (a.hemisphere == "auto" and CITY[1] < 0)
    scenes = {int(x) for x in a.scenes.split(",") if x.strip()}
    WORLD = World(a.cache)
    fonts = Fonts(a.width / 960)
    frames = build_frames(a.fps, a.speed, scenes, max(1, a.step))
    print(T["rendering"].format(n=len(frames), w=a.width, h=a.height))

    writer, folder = None, None
    try:
        import imageio.v2 as imageio
        writer = imageio.get_writer(a.output, fps=a.fps, codec="libx264", quality=8,
                                    macro_block_size=2, pixelformat="yuv420p")
    except Exception:
        folder = os.path.splitext(a.output)[0] + "_frames"
        os.makedirs(folder, exist_ok=True)

    viewer = None
    if a.show:
        import matplotlib.pyplot as plt
        plt.ion()
        fig, axv = plt.subplots(figsize=(a.width / 100, a.height / 100))
        axv.axis("off")
        viewer = None

    t_start = time.time()
    for k, (seg, s, theta, w) in enumerate(frames):
        st = frame_state(seg, s, theta, w)
        img = compose(WORLD, st, fonts, a.width, a.height)
        if writer:
            writer.append_data(np.asarray(img))
        else:
            img.save(os.path.join(folder, f"frame_{k:05d}.png"))
        if a.show:
            if viewer is None:
                viewer = axv.imshow(img)
            else:
                viewer.set_data(img)
            plt.pause(0.001)
        if k % 50 == 0:
            el = time.time() - t_start
            eta = el / (k + 1) * (len(frames) - k - 1)
            print(f"  {k + 1}/{len(frames)}  ({eta / 60:.1f} min)", flush=True)
    if writer:
        writer.close()
        print(T["done"].format(path=a.output, s=len(frames) / a.fps,
                               m=(time.time() - t_start) / 60))
    else:
        print(T["frames_saved"].format(path=folder))


if __name__ == "__main__":
    main()
