#!/usr/bin/env python3
"""
World map of the difference between (mean) solar time and official time.

    difference = local mean solar time − official time
               = longitude / 15 − UTC offset of the time zone      (hours)

  red    → negative: the clock is AHEAD of the Sun
           (it would have to be set back to match solar time)
  blue   → positive: the clock is BEHIND the Sun
  white  → official time ≈ solar time

The colour is computed point by point from the longitude, so it changes
smoothly inside each country or time zone.

With --mode zones it draws a plain time-zone map instead: one pastel colour
per UTC offset (paler over the open sea), places with daylight saving time
hatched.

Map texts and country names follow the system language by default, or the
language given with --lang. Supported: en, pt (European Portuguese), es, fr,
de, it, ru, zh, ja, ar.

Data (downloaded automatically on the first run and cached):
  - Time zones: timezone-boundary-builder (github.com/evansiroky)
  - Land and countries: Natural Earth 1:50m (github.com/nvkelso/natural-earth-vector)

Requirements:
    pip install numpy scipy matplotlib cartopy geopandas rasterio shapely
    Windows: pip install tzdata
    Arabic with matplotlib < 3.11: pip install arabic-reshaper python-bidi
    Chinese/Japanese: a CJK font (e.g. Noto Sans CJK; Windows/macOS already have one)

Examples:
    python solar_time_map.py                                  # Equal Earth, system language
    python solar_time_map.py --projection robinson --lang pt
    python solar_time_map.py -p mercator --date 2026-07-01 --lang de
    python solar_time_map.py -p miller --output miller.png --no-names
    python solar_time_map.py --mode zones -p miller --lang pt  # time-zone map
"""

import argparse
import ctypes
import datetime as dt
import locale
import os
import sys
import textwrap
import urllib.request
import warnings
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import numpy as np
import matplotlib
import matplotlib.pyplot as plt
from matplotlib import font_manager
from matplotlib.colors import LinearSegmentedColormap
import matplotlib.patches as mpatches

import geopandas as gpd
import rasterio.features
from rasterio.transform import from_origin
from scipy.ndimage import distance_transform_edt
import shapely.geometry
from shapely.ops import polylabel
from shapely.prepared import prep
import cartopy.crs as ccrs

warnings.filterwarnings("ignore", message="Geometry is in a geographic CRS")

# ----------------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------------
TZ_VERSION = "2025b"
URLS = {
    "timezones.zip": ("https://github.com/evansiroky/timezone-boundary-builder/releases/download/"
                      f"{TZ_VERSION}/timezones-with-oceans-now.shapefile.zip"),
    "land.geojson": ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
                     "master/geojson/ne_50m_land.geojson"),
    "countries.geojson": ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
                          "master/geojson/ne_50m_admin_0_countries.geojson"),
    "marine.geojson": ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
                       "master/geojson/ne_50m_geography_marine_polys.geojson"),
    "regions.geojson": ("https://raw.githubusercontent.com/nvkelso/natural-earth-vector/"
                        "master/geojson/ne_50m_geography_regions_polys.geojson"),
}

# Island groups missing from Natural Earth's regions (lon, lat, names), for svg/pdf
EXTRA_ISLANDS = [
    (-16.95, 32.75, {"en": "Madeira", "pt": "Madeira", "es": "Madeira", "fr": "Madère",
                     "de": "Madeira", "it": "Madera", "ru": "Мадейра", "zh": "马德拉群岛",
                     "ja": "マデイラ諸島", "ar": "ماديرا"}),
    (-90.5, -0.6, {"en": "Galápagos Islands", "pt": "Galápagos", "es": "Islas Galápagos",
                   "fr": "Îles Galápagos", "de": "Galápagos-Inseln", "it": "Isole Galápagos",
                   "ru": "Галапагосские острова", "zh": "加拉帕戈斯群岛", "ja": "ガラパゴス諸島",
                   "ar": "جزر غالاباغوس"}),
    (-109.35, -27.1, {"en": "Easter Island", "pt": "Ilha de Páscoa", "es": "Isla de Pascua",
                      "fr": "Île de Pâques", "de": "Osterinsel", "it": "Isola di Pasqua",
                      "ru": "Остров Пасхи", "zh": "复活节岛", "ja": "イースター島",
                      "ar": "جزيرة القيامة"}),
    (-176.5, -43.9, {"en": "Chatham Islands", "pt": "Ilhas Chatham", "es": "Islas Chatham",
                     "fr": "Îles Chatham", "de": "Chathaminseln", "it": "Isole Chatham",
                     "ru": "Острова Чатем", "zh": "查塔姆群岛", "ja": "チャタム諸島",
                     "ar": "جزر تشاتام"}),
]

# key: (cartopy factory, latitude limits or None for the whole globe)
PROJECTIONS = {
    "equal-earth": (lambda: ccrs.EqualEarth(), None),
    "robinson":    (lambda: ccrs.Robinson(),   None),
    "miller":      (lambda: ccrs.Miller(),     (-60, 85)),
    "mercator":    (lambda: ccrs.Mercator(),   (-60, 84)),
}

CMAP = LinearSegmentedColormap.from_list(
    "solar", ["#e8121b", "#f47f84", "#ffffff", "#7f9cff", "#1747ff"])
ZONE_LINE_COLOR = "#9a5b2e"
BORDER_COLOR = "#8c8c8c"
ANTARCTICA_COLOR = "#eef0f1"

# --mode zones: one pastel colour per whole UTC offset (cycling, so neighbouring
# zones always differ), others for half and quarter hours; the open sea is paler
ZONE_COLORS = ["#f3cf9c", "#eba882", "#bfd497", "#a9c0cc"]
ZONE_HALF_COLOR = "#c8acd9"
ZONE_QUARTER_COLOR = "#e8a9c4"
SEA_PALENESS = 0.55            # how much the sea colours are mixed with white
HATCH_COLOR = "#7a5a46"
OCEAN_COLOR = "#5f7f93"
SEA_NAME_COLOR = "#6d8797"

# ----------------------------------------------------------------------------
# Translations
# ----------------------------------------------------------------------------
CREDIT = "timezone-boundary-builder, Natural Earth"

TEXTS = {
    "en": {
        "language": "English",
        "title": "Difference between solar time and official time — {proj} projection",
        "subtitle": "Local mean solar time (longitude/15) − {mode}.   "
                    "Red: clock ahead of the Sun · Blue: clock behind the Sun",
        "mode_std": "standard time (no daylight saving)",
        "mode_date": "legal time on {date} (daylight saving included)",
        "cbar": "Solar time − official time (h)",
        "credit": "Data: " + CREDIT,
        "proj": {"equal-earth": "Equal Earth", "robinson": "Robinson",
                 "miller": "Miller cylindrical", "mercator": "Mercator"},
        "downloading": "Downloading {name} ...",
        "reading": "Reading time zones ...",
        "raster": "Rasterising time zones and land ...",
        "merging": "Merging time zones by UTC offset ...",
        "saved": "Map saved to {path}",
        "title_zones": "Time zones of the world — {proj} projection",
        "subtitle_zones": "UTC offset of the official time: {mode}.",
        "dst_std": "Hatched: places that use daylight saving time",
        "dst_date": "Hatched: daylight saving time in force on {date}",
        "sea": "Paler colours: open sea (nautical time zones, 15° strips)",
    },
    "pt": {
        "language": "Português (Portugal)",
        "title": "Diferença entre a hora solar e a hora oficial — projeção {proj}",
        "subtitle": "Hora solar média local (longitude/15) − {mode}.   "
                    "Vermelho: relógio adiantado em relação ao Sol · Azul: relógio atrasado",
        "mode_std": "hora padrão (sem hora de verão)",
        "mode_date": "hora legal em {date} (inclui hora de verão)",
        "cbar": "Diferença hora solar − hora oficial (h)",
        "credit": "Dados: " + CREDIT,
        "proj": {"equal-earth": "Equal Earth", "robinson": "Robinson",
                 "miller": "Miller cilíndrica", "mercator": "Mercator"},
        "downloading": "A descarregar {name} ...",
        "reading": "A ler os fusos horários ...",
        "raster": "A rasterizar fusos e terra ...",
        "merging": "A unir fusos por desvio horário ...",
        "saved": "Mapa guardado em {path}",
        "title_zones": "Fusos horários do mundo — projeção {proj}",
        "subtitle_zones": "Desvio UTC da hora oficial: {mode}.",
        "dst_std": "Riscado: locais com hora de verão",
        "dst_date": "Riscado: hora de verão em vigor em {date}",
        "sea": "Cores mais claras: mar alto (fusos náuticos, faixas de 15°)",
    },
    "es": {
        "language": "Español",
        "title": "Diferencia entre la hora solar y la hora oficial — proyección {proj}",
        "subtitle": "Hora solar media local (longitud/15) − {mode}.   "
                    "Rojo: reloj adelantado respecto al Sol · Azul: reloj atrasado",
        "mode_std": "hora estándar (sin horario de verano)",
        "mode_date": "hora legal el {date} (incluye horario de verano)",
        "cbar": "Hora solar − hora oficial (h)",
        "credit": "Datos: " + CREDIT,
        "proj": {"equal-earth": "Equal Earth", "robinson": "Robinson",
                 "miller": "cilíndrica de Miller", "mercator": "Mercator"},
        "downloading": "Descargando {name} ...",
        "reading": "Leyendo los husos horarios ...",
        "raster": "Rasterizando husos y tierra ...",
        "merging": "Uniendo husos por desfase horario ...",
        "saved": "Mapa guardado en {path}",
        "title_zones": "Husos horarios del mundo — proyección {proj}",
        "subtitle_zones": "Desfase UTC de la hora oficial: {mode}.",
        "dst_std": "Rayado: lugares con horario de verano",
        "dst_date": "Rayado: horario de verano vigente el {date}",
        "sea": "Colores más claros: alta mar (husos náuticos, franjas de 15°)",
    },
    "fr": {
        "language": "Français",
        "title": "Écart entre l'heure solaire et l'heure légale — projection {proj}",
        "subtitle": "Heure solaire moyenne locale (longitude/15) − {mode}.   "
                    "Rouge : horloge en avance sur le Soleil · Bleu : horloge en retard",
        "mode_std": "heure normale (sans heure d'été)",
        "mode_date": "heure légale le {date} (heure d'été incluse)",
        "cbar": "Heure solaire − heure légale (h)",
        "credit": "Données : " + CREDIT,
        "proj": {"equal-earth": "Equal Earth", "robinson": "de Robinson",
                 "miller": "cylindrique de Miller", "mercator": "de Mercator"},
        "downloading": "Téléchargement de {name} ...",
        "reading": "Lecture des fuseaux horaires ...",
        "raster": "Rastérisation des fuseaux et des terres ...",
        "merging": "Fusion des fuseaux par décalage horaire ...",
        "saved": "Carte enregistrée dans {path}",
        "title_zones": "Fuseaux horaires du monde — projection {proj}",
        "subtitle_zones": "Décalage UTC de l'heure légale : {mode}.",
        "dst_std": "Hachuré : lieux appliquant l'heure d'été",
        "dst_date": "Hachuré : heure d'été en vigueur le {date}",
        "sea": "Couleurs plus claires : haute mer (fuseaux nautiques, bandes de 15°)",
    },
    "de": {
        "language": "Deutsch",
        "title": "Unterschied zwischen Sonnenzeit und gesetzlicher Zeit — {proj}",
        "subtitle": "Mittlere Ortssonnenzeit (Längengrad/15) − {mode}.   "
                    "Rot: Uhr geht der Sonne vor · Blau: Uhr geht nach",
        "mode_std": "Normalzeit (ohne Sommerzeit)",
        "mode_date": "gesetzliche Zeit am {date} (mit Sommerzeit)",
        "cbar": "Sonnenzeit − gesetzliche Zeit (h)",
        "credit": "Daten: " + CREDIT,
        "proj": {"equal-earth": "Equal-Earth-Projektion", "robinson": "Robinson-Projektion",
                 "miller": "Miller-Zylinderprojektion", "mercator": "Mercator-Projektion"},
        "downloading": "Lade {name} herunter ...",
        "reading": "Lese Zeitzonen ...",
        "raster": "Rasterisiere Zeitzonen und Landflächen ...",
        "merging": "Fasse Zeitzonen nach UTC-Versatz zusammen ...",
        "saved": "Karte gespeichert unter {path}",
        "title_zones": "Zeitzonen der Welt — {proj}",
        "subtitle_zones": "UTC-Versatz der gesetzlichen Zeit: {mode}.",
        "dst_std": "Schraffiert: Orte mit Sommerzeit",
        "dst_date": "Schraffiert: Sommerzeit am {date} in Kraft",
        "sea": "Hellere Farben: offenes Meer (nautische Zeitzonen, 15°-Streifen)",
    },
    "it": {
        # "ora solare" in italiano significa anche "ora invernale": si usa "tempo solare"
        "language": "Italiano",
        "title": "Differenza tra tempo solare e ora ufficiale — proiezione {proj}",
        "subtitle": "Tempo solare medio locale (longitudine/15) − {mode}.   "
                    "Rosso: orologio avanti rispetto al Sole · Blu: orologio indietro",
        "mode_std": "ora standard (senza ora legale)",
        "mode_date": "ora in vigore il {date} (ora legale inclusa)",
        "cbar": "Tempo solare − ora ufficiale (h)",
        "credit": "Dati: " + CREDIT,
        "proj": {"equal-earth": "Equal Earth", "robinson": "di Robinson",
                 "miller": "cilindrica di Miller", "mercator": "di Mercatore"},
        "downloading": "Download di {name} ...",
        "reading": "Lettura dei fusi orari ...",
        "raster": "Rasterizzazione di fusi orari e terre emerse ...",
        "merging": "Unione dei fusi per scostamento orario ...",
        "saved": "Mappa salvata in {path}",
        "title_zones": "Fusi orari del mondo — proiezione {proj}",
        "subtitle_zones": "Scostamento UTC dell'ora ufficiale: {mode}.",
        "dst_std": "Tratteggio: luoghi con ora legale",
        "dst_date": "Tratteggio: ora legale in vigore il {date}",
        "sea": "Colori più chiari: mare aperto (fusi nautici, fasce di 15°)",
    },
    "ru": {
        "language": "Русский",
        "title": "Разница между солнечным и официальным временем — проекция {proj}",
        "subtitle": "Среднее местное солнечное время (долгота/15) − {mode}.   "
                    "Красный: часы спешат относительно Солнца · Синий: часы отстают",
        "mode_std": "стандартное время (без летнего)",
        "mode_date": "официальное время на {date} (с учётом летнего)",
        "cbar": "Солнечное время − официальное время (ч)",
        "credit": "Данные: " + CREDIT,
        "proj": {"equal-earth": "Equal Earth", "robinson": "Робинсона",
                 "miller": "Миллера", "mercator": "Меркатора"},
        "downloading": "Загрузка {name} ...",
        "reading": "Чтение часовых поясов ...",
        "raster": "Растеризация поясов и суши ...",
        "merging": "Объединение поясов по смещению UTC ...",
        "saved": "Карта сохранена: {path}",
        "title_zones": "Часовые пояса мира — проекция {proj}",
        "subtitle_zones": "Смещение официального времени от UTC: {mode}.",
        "dst_std": "Штриховка: места с летним временем",
        "dst_date": "Штриховка: летнее время действует {date}",
        "sea": "Светлые цвета: открытое море (морские пояса, полосы по 15°)",
    },
    "zh": {
        "language": "中文",
        "title": "太阳时与官方时间之差 — {proj}投影",
        "subtitle": "地方平太阳时（经度/15）− {mode}。   红色：时钟快于太阳 · 蓝色：时钟慢于太阳",
        "mode_std": "标准时间（不含夏令时）",
        "mode_date": "{date} 的法定时间（含夏令时）",
        "cbar": "太阳时 − 官方时间（小时）",
        "credit": "数据：" + CREDIT,
        "proj": {"equal-earth": "等面积地球 (Equal Earth) ", "robinson": "罗宾森",
                 "miller": "米勒圆柱", "mercator": "墨卡托"},
        "downloading": "正在下载 {name} ...",
        "reading": "正在读取时区 ...",
        "raster": "正在栅格化时区和陆地 ...",
        "merging": "正在按时差合并时区 ...",
        "saved": "地图已保存到 {path}",
        "title_zones": "世界时区 — {proj}投影",
        "subtitle_zones": "官方时间的 UTC 偏移：{mode}。",
        "dst_std": "斜线：实行夏令时的地区",
        "dst_date": "斜线：{date} 正在实行夏令时",
        "sea": "浅色：公海（航海时区，每 15° 一带）",
    },
    "ja": {
        "language": "日本語",
        "title": "太陽時と公式時刻の差 — {proj}図法",
        "subtitle": "地方平均太陽時（経度/15）− {mode}。   赤：時計が太陽より進んでいる · 青：時計が遅れている",
        "mode_std": "標準時（夏時間なし）",
        "mode_date": "{date} の法定時刻（夏時間を含む）",
        "cbar": "太陽時 − 公式時刻（時間）",
        "credit": "データ：" + CREDIT,
        "proj": {"equal-earth": "イコールアース", "robinson": "ロビンソン",
                 "miller": "ミラー", "mercator": "メルカトル"},
        "downloading": "{name} をダウンロード中 ...",
        "reading": "タイムゾーンを読み込み中 ...",
        "raster": "タイムゾーンと陸地をラスタ化中 ...",
        "merging": "時差ごとにタイムゾーンを統合中 ...",
        "saved": "地図を保存しました: {path}",
        "title_zones": "世界の時間帯 — {proj}図法",
        "subtitle_zones": "公式時刻の UTC との時差：{mode}。",
        "dst_std": "斜線：夏時間を実施している地域",
        "dst_date": "斜線：{date} に夏時間を実施中",
        "sea": "淡い色：公海（航海時間帯、15° ごとの帯）",
    },
    "ar": {
        "language": "العربية",
        "title": "الفرق بين التوقيت الشمسي والتوقيت الرسمي — إسقاط {proj}",
        "subtitle": "التوقيت الشمسي المحلي المتوسط (خط الطول/15) − {mode}.   "
                    "الأحمر: الساعة متقدمة على الشمس · الأزرق: الساعة متأخرة",
        "mode_std": "التوقيت القياسي (دون التوقيت الصيفي)",
        "mode_date": "التوقيت الرسمي في {date} (يشمل التوقيت الصيفي)",
        "cbar": "التوقيت الشمسي − التوقيت الرسمي (ساعة)",
        "credit": "البيانات: " + CREDIT,
        "proj": {"equal-earth": "Equal Earth", "robinson": "روبنسون",
                 "miller": "ميلر", "mercator": "ميركاتور"},
        "downloading": "جارٍ تنزيل {name} ...",
        "reading": "جارٍ قراءة المناطق الزمنية ...",
        "raster": "جارٍ تحويل المناطق الزمنية واليابسة إلى شبكة ...",
        "merging": "جارٍ دمج المناطق الزمنية حسب فرق التوقيت ...",
        "saved": "تم حفظ الخريطة في {path}",
        "title_zones": "المناطق الزمنية في العالم — إسقاط {proj}",
        "subtitle_zones": "فرق التوقيت الرسمي عن UTC: {mode}.",
        "dst_std": "المناطق المخططة: أماكن تطبق التوقيت الصيفي",
        "dst_date": "المناطق المخططة: التوقيت الصيفي سارٍ في {date}",
        "sea": "الألوان الأفتح: أعالي البحار (مناطق زمنية بحرية، شرائح بعرض 15°)",
    },
}
LANGUAGES = list(TEXTS)
RTL = {"ar"}

# Fonts tried for scripts not covered by matplotlib's default font
FONT_CANDIDATES = {
    "zh": ["Noto Sans CJK SC", "Source Han Sans SC", "Microsoft YaHei", "SimHei",
           "PingFang SC", "Hiragino Sans GB", "WenQuanYi Zen Hei", "Noto Sans CJK TC",
           "Noto Sans CJK JP", "Arial Unicode MS"],
    "ja": ["Noto Sans CJK JP", "Source Han Sans JP", "Yu Gothic", "Meiryo", "MS Gothic",
           "Hiragino Sans", "Hiragino Kaku Gothic ProN", "Noto Sans CJK SC",
           "Noto Sans CJK TC", "Arial Unicode MS"],
    "ar": ["Noto Sans Arabic", "Segoe UI", "Arial", "Tahoma", "Geeza Pro", "DejaVu Sans"],
}

T = TEXTS["en"]        # active texts (set in main)
LANG = "en"


def normalise_language(code):
    """'pt_PT.UTF-8', 'pt-BR', 'Portuguese_Portugal' ... → 'pt' (or None)."""
    if not code:
        return None
    code = code.strip().lower().replace("-", "_")
    names = {"english": "en", "portuguese": "pt", "spanish": "es", "french": "fr",
             "german": "de", "italian": "it", "russian": "ru", "chinese": "zh",
             "japanese": "ja", "arabic": "ar"}
    for name, c in names.items():          # Windows style "Portuguese_Portugal"
        if code.startswith(name):
            return c
    c = code.split("_")[0].split(".")[0]
    return c if c in TEXTS else None


def system_language():
    """Language of the operating system / user session."""
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
    if sys.platform == "darwin":
        try:
            import subprocess
            out = subprocess.run(["defaults", "read", "-g", "AppleLanguages"],
                                 capture_output=True, text=True, timeout=3).stdout
            for tok in out.replace('"', " ").replace(",", " ").split():
                c = normalise_language(tok)
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


def setup_fonts(lang):
    """Pick a font able to show the language's script."""
    cands = FONT_CANDIDATES.get(lang)
    if not cands:
        return
    available = {f.name for f in font_manager.fontManager.ttflist}
    for name in cands:
        if name in available:
            matplotlib.rcParams["font.family"] = [name, "DejaVu Sans"]
            return
    print(f"[warning] No font found for '{lang}' (tried: {', '.join(cands[:4])} ...). "
          "Texts may show as empty boxes.")


def _native_complex_text():
    """matplotlib >= 3.11 joins Arabic letters and orders right-to-left itself."""
    try:
        major, minor = (int(x) for x in matplotlib.__version__.split(".")[:2])
        return (major, minor) >= (3, 11)
    except ValueError:
        return False


NATIVE_RTL = _native_complex_text()


def shape(text):
    """Arabic needs letter joining and right-to-left ordering (older matplotlib)."""
    if LANG not in RTL or NATIVE_RTL:
        return text
    try:
        import arabic_reshaper
        from bidi.algorithm import get_display
        return get_display(arabic_reshaper.reshape(text))
    except ImportError:
        return text


def say(key, **kw):
    print(T[key].format(**kw))


# ----------------------------------------------------------------------------
# Data
# ----------------------------------------------------------------------------
def get_data(folder):
    os.makedirs(folder, exist_ok=True)
    paths = {}
    for name, url in URLS.items():
        dest = os.path.join(folder, name)
        if not os.path.exists(dest):
            say("downloading", name=name)
            tmp = dest + ".part"
            urllib.request.urlretrieve(url, tmp)
            os.replace(tmp, dest)
        paths[name] = dest
    return paths


def utc_offset(tzid, date=None):
    """UTC offset (hours) of a time zone and whether it has daylight saving.

    Without date: standard time (no DST) = the smaller offset between January
    and July, which works in both hemispheres; DST = the two differ.
    With date: the legal offset on that day; DST = in force on that day."""
    try:
        z = ZoneInfo(tzid)
    except (ZoneInfoNotFoundError, ValueError):
        return np.nan, False
    year = date.year if date is not None else dt.date.today().year
    offs = [dt.datetime(year, m, 15, 12, tzinfo=dt.timezone.utc).astimezone(z)
            .utcoffset().total_seconds() / 3600 for m in (1, 7)]
    if date is not None:
        t = dt.datetime(date.year, date.month, date.day, 12, tzinfo=dt.timezone.utc)
        legal = t.astimezone(z).utcoffset().total_seconds() / 3600
        return legal, legal > min(offs)
    return min(offs), offs[0] != offs[1]


def load_timezones(path, date, tolerance):
    say("reading")
    tz = gpd.read_file(f"zip://{path}")
    tz["offset"], tz["dst"] = zip(*(utc_offset(t, date) for t in tz["tzid"]))
    tz = tz.dropna(subset=["offset"])
    tz["geometry"] = tz.geometry.simplify(tolerance, preserve_topology=True)
    return tz


# ----------------------------------------------------------------------------
# Grid (raster) of UTC offsets and of solar time − official time
# ----------------------------------------------------------------------------
def join_islands(near_coast, nearest, radius, res):
    """Closes the gaps of up to about 2·radius degrees between islands (and coasts)
    with the same UTC offset, so an archipelago such as Hawaii, the Line Islands
    or French Polynesia gets one outline instead of a ring around every island.

    Morphological closing (dilation, then erosion) of each offset's area, done
    with distance transforms; a sea cell is only filled when its nearest civil
    zone has that offset, so different offsets never take each other's sea."""
    r = radius / res
    pad = int(np.ceil(2 * r)) + 2
    wrap = lambda a: np.concatenate([a[:, -pad:], a, a[:, :pad]], axis=1)   # noqa: E731
    area, near = wrap(near_coast), wrap(nearest)
    joined = area.copy()
    for v in np.unique(area[~np.isnan(area)]):
        mask = area == v
        # a closing never leaves the bounding box; the empty border lets it work
        rows, cols = np.nonzero(mask.any(axis=1))[0], np.nonzero(mask.any(axis=0))[0]
        y0, y1, x0, x1 = rows[0], rows[-1] + 1, cols[0], cols[-1] + 1
        m = np.pad(mask[y0:y1, x0:x1], pad)
        grown = distance_transform_edt(~m) <= r
        closed = (distance_transform_edt(grown) > r)[pad:-pad, pad:-pad]
        fill = closed & np.isnan(area[y0:y1, x0:x1]) & (near[y0:y1, x0:x1] == v)
        joined[y0:y1, x0:x1][fill] = v
    # fold the wrapped margins back onto the other side of the 180° meridian
    out = joined[:, pad:-pad].copy()
    for src, dst in ((joined[:, :pad], out[:, -pad:]), (joined[:, -pad:], out[:, :pad])):
        take = np.isnan(dst) & ~np.isnan(src)
        dst[take] = src[take]
    return out


def compute_grid(timezones, land, res, sea_margin, island_join):
    """Returns the UTC offset grid, the land, Antarctica and daylight-saving
    (land only) masks, and the zones as drawn.

    The "with oceans" data covers the sea with nautical zones (Etc/GMT±N), plain
    15° strips set by longitude. Left alone they swallow the small islands, so
    the Azores, Iceland or Kiribati would get the lines and labels of the strip
    around them (−2, −1, −11 ...). As on usual time-zone maps, every civil zone
    is therefore extended into the sea up to `sea_margin` degrees from its
    coast (each sea cell takes the nearest civil zone), and nearby islands of
    the same offset are joined (`island_join`, see join_islands); the nautical
    strips only fill the open ocean beyond."""
    width, height = int(round(360 / res)), int(round(180 / res))
    transform = from_origin(-180, 90, res, res)

    say("raster")
    nautical = timezones["tzid"].str.startswith("Etc/")

    def rasterise(zones):
        return rasterio.features.rasterize(
            ((g, float(v)) for g, v in zip(zones.geometry, zones["offset"])),
            out_shape=(height, width), transform=transform, fill=np.nan, dtype="float32")

    civil = rasterise(timezones[~nautical])
    sea = rasterise(timezones[nautical])
    is_land = rasterio.features.rasterize(
        ((g, 1) for g in land.geometry), out_shape=(height, width),
        transform=transform, fill=0, dtype="uint8").astype(bool)

    # Nearest civil zone for every cell, wrapping around the 180° meridian
    pad = int(np.ceil(sea_margin / res)) + 1
    wrapped = np.concatenate([civil[:, -pad:], civil, civil[:, :pad]], axis=1)
    dist, (iy, ix) = distance_transform_edt(np.isnan(wrapped), sampling=res,
                                            return_indices=True)
    nearest = wrapped[iy, ix][:, pad:-pad]
    dist = dist[:, pad:-pad]
    near_coast = np.where(dist <= sea_margin, nearest, np.nan)
    if island_join > 0:
        near_coast = join_islands(near_coast, nearest, island_join, res)
    offset = np.where(np.isnan(near_coast), sea, near_coast)
    offset = np.where(np.isnan(offset), nearest, offset)

    lat = 90 - res * (np.arange(height) + 0.5)
    antarctica = is_land & (lat[:, None] < -60)
    civil_zones = timezones[~nautical]
    dst = rasterio.features.rasterize(
        ((g, 1) for g in civil_zones.geometry[civil_zones["dst"].astype(bool)]),
        out_shape=(height, width), transform=transform, fill=0, dtype="uint8").astype(bool)
    dst &= is_land & ~antarctica

    say("merging")
    zones = gpd.GeoDataFrame(
        [{"offset": float(v), "geometry": shapely.geometry.shape(g)}
         for g, v in rasterio.features.shapes(offset, transform=transform)],
        crs="EPSG:4326")
    return offset, is_land, antarctica, dst, zones


def solar_difference(offset, is_land, antarctica, res):
    """Local mean solar time − official time (hours), on land outside Antarctica."""
    lon = -180 + res * (np.arange(offset.shape[1]) + 0.5)
    diff = lon[None, :] / 15.0 - offset
    diff = (diff + 12) % 24 - 12            # e.g. Kiribati (+14) near −157°
    diff[~is_land | antarctica] = np.nan
    return diff


def zone_colours(offset, is_land, antarctica):
    """RGBA image of the time zones: a pastel colour per offset, paler at sea."""
    whole = np.isclose(offset, np.round(offset))
    half = np.isclose(np.mod(offset, 1), 0.5)
    idx = np.mod(np.nan_to_num(np.round(offset)), len(ZONE_COLORS)).astype(int)
    palette = np.array([matplotlib.colors.to_rgb(c) for c in ZONE_COLORS])
    rgb = palette[idx]
    rgb[~whole & half] = matplotlib.colors.to_rgb(ZONE_HALF_COLOR)
    rgb[~whole & ~half] = matplotlib.colors.to_rgb(ZONE_QUARTER_COLOR)
    rgb[~is_land] += (1 - rgb[~is_land]) * SEA_PALENESS
    alpha = ~(np.isnan(offset) | antarctica)
    return np.dstack([rgb, alpha]).astype("float32")


# ----------------------------------------------------------------------------
# Labels
# ----------------------------------------------------------------------------
def format_offset(h):
    sign = "+" if h >= 0 else "−"
    a = abs(h)
    whole = int(a)
    frac = {0: "", 0.25: "¼", 0.5: "½", 0.75: "¾"}.get(round((a - whole) * 4) / 4, "")
    if h == 0:
        return "0"
    return f"{sign}{frac}" if whole == 0 and frac else f"{sign}{whole}{frac}"


class Labeller:
    """Places texts avoiding overlaps (first come, first served)."""

    def __init__(self, fig, ax):
        self.ax = ax
        self.renderer = fig.canvas.get_renderer()
        self.boxes = []

    def text(self, *args, margin=2, **kw):
        t = self.ax.text(*args, **kw)
        box = t.get_window_extent(self.renderer).padded(margin)
        bb = self.ax.bbox
        if not (bb.contains(box.x0, box.y0) and bb.contains(box.x1, box.y1)) or \
                any(box.overlaps(b) for b in self.boxes):
            t.remove()
            return None
        self.boxes.append(box)
        return t


def regions_by_offset(timezones):
    """Merges zones with the same offset and returns contiguous regions."""
    merged = timezones[["offset", "geometry"]].dissolve(by="offset").reset_index()
    return merged, merged.explode(index_parts=False).reset_index(drop=True)


def label_points(geom, n=7):
    """Candidate label positions inside a region: its representative point first,
    then other inner points nearest to it (used when a country name is in the way)."""
    p0 = geom.representative_point()
    x0, y0, x1, y1 = geom.bounds
    xs, ys = np.meshgrid(np.linspace(x0, x1, n + 2)[1:-1], np.linspace(y0, y1, n + 2)[1:-1])
    pts = [shapely.geometry.Point(x, y) for x, y in zip(xs.ravel(), ys.ravel())]
    pts = [p for p in pts if geom.contains(p)]
    return [p0] + sorted(pts, key=p0.distance)


def country_name_column(countries):
    col = f"NAME_{LANG.upper()}"
    return col if col in countries.columns else "NAME"


# ----------------------------------------------------------------------------
# Drawing
# ----------------------------------------------------------------------------
def draw(offset, is_land, antarctica, dst, zones, land, countries, marine, islands,
         projection, limit, date, names, output, show, mode, res):
    factory, lat_lim = PROJECTIONS[projection]
    pc = ccrs.PlateCarree()

    fig = plt.figure(figsize=(16, 9.2), facecolor="white")
    ax = fig.add_axes([0.01, 0.10, 0.98, 0.82], projection=factory())
    if lat_lim:
        ax.set_extent([-180, 180, lat_lim[0], lat_lim[1]], crs=pc)
    else:
        ax.set_global()
    ax.set_facecolor("white")

    extent = [-180, 180, -90, 90]
    ny, nx = offset.shape
    regrid = (min(nx, 4000), min(ny, 2000))

    # Antarctica in light grey (neither the difference nor the zones have much
    # practical meaning there)
    ax.imshow(np.where(antarctica, 1.0, np.nan), extent=extent, transform=pc,
              origin="upper", cmap=LinearSegmentedColormap.from_list("a", [ANTARCTICA_COLOR] * 2),
              vmin=0, vmax=1, regrid_shape=regrid, interpolation="nearest", zorder=1)
    if mode == "solar":
        im = ax.imshow(solar_difference(offset, is_land, antarctica, res), extent=extent,
                       transform=pc, origin="upper", cmap=CMAP, vmin=-limit, vmax=limit,
                       regrid_shape=regrid, interpolation="nearest", zorder=2)
    else:
        ax.imshow(zone_colours(offset, is_land, antarctica), extent=extent, transform=pc,
                  origin="upper", regrid_shape=regrid, interpolation="nearest", zorder=2)
        dst_shapes = [shapely.geometry.shape(g) for g, _ in rasterio.features.shapes(
            dst.astype("uint8"), mask=dst, transform=from_origin(-180, 90, res, res))]
        ax.add_geometries(dst_shapes, crs=pc, facecolor="none", edgecolor=HATCH_COLOR,
                          linewidth=0, hatch="////", alpha=0.45, zorder=2.5)

    # Country borders, coastlines and time-zone limits
    ax.add_geometries(countries.geometry, crs=pc, facecolor="none",
                      edgecolor=BORDER_COLOR, linewidth=0.25, zorder=3)
    ax.add_geometries(land.geometry, crs=pc, facecolor="none",
                      edgecolor="#6f6f6f", linewidth=0.3, zorder=3)
    merged, regions = regions_by_offset(zones)
    ax.add_geometries(merged.geometry, crs=pc, facecolor="none",
                      edgecolor=ZONE_LINE_COLOR, linewidth=0.55, zorder=4)

    lab = Labeller(fig, ax)
    fig.canvas.draw()          # needed to measure texts

    # Labels, first come first served:
    #   1. names of the large countries
    #   2. UTC offsets of small regions: islands with a zone of their own
    #      (Azores, Iceland, Kiribati, Chatham ...), which names would cover
    #   3. (time-zone map) names of the medium countries, then the UTC offset of
    #      every large enough land part of a zone
    #   4. names of the other countries
    #   5. (time-zone map) names of the oceans, seas and bays
    #   6. UTC offsets of the large regions (largest first)
    #   (vector output) names of the small countries and of island groups
    zones_map = mode == "zones"
    # svg/pdf can be zoomed: there is room for many more small names
    detail = os.path.splitext(output or "")[1].lower() in (".svg", ".pdf")
    small_font = 3.5 if detail else 4.6
    regions = regions.assign(area=regions.geometry.area).sort_values("area", ascending=False)
    small = regions["area"] < 200
    placed = []                 # (offset, point) of every offset label

    def label_offsets(sel, skip_near=None):
        for g, v in zip(sel.geometry, sel["offset"]):
            if skip_near is not None and any(
                    pv == v and g.distance(pp) < skip_near for pv, pp in placed):
                continue        # the same offset is already written close by
            for p in label_points(g):
                if p.y < -62 or (lat_lim and not (lat_lim[0] + 2 < p.y < lat_lim[1] - 2)):
                    continue
                if lab.text(p.x, p.y, format_offset(v), transform=pc,
                            fontsize=8.5 if zones_map else 7.5,
                            fontweight="bold", color="#3b2a1e", ha="center", va="center",
                            zorder=6, margin=1):
                    placed.append((v, p))
                    break

    def inside_map(p):
        return not lat_lim or lat_lim[0] + 1 < p.y < lat_lim[1] - 1

    # Beside a small country or island: a ring of spots around (x, y)
    def beside(x, y):
        return [shapely.geometry.Point(x + dx, y + dy)
                for dx, dy in ((-3, 0), (3, 0), (0, 2), (0, -2), (-5, 0), (5, 0),
                               (-4, 2), (4, 2), (-4, -2), (4, -2), (0, 3.5))]

    # Country names, all in capitals, sized by the country's area; when the
    # usual spot is taken, a few other points inside the country are tried
    sel = countries.iloc[0:0]
    if names:
        col = country_name_column(countries)
        sel = countries[countries["CONTINENT"] != "Antarctica"]
        area_km2 = sel.geometry.to_crs("ESRI:54009").area / 1e6       # Mollweide
        size = np.clip(3.2 + 1.5 * np.log10(area_km2.clip(lower=1) / 1000), 0, 10.5)
        # long names ("República Democrática do Congo", in two lines) would
        # dominate their neighbours: at most the size of a medium country, not bold
        long_name = sel[col].fillna(sel["NAME"]).str.len() > 18
        size = np.where(long_name, np.minimum(size, 7.2), size)
        if detail:      # a little smaller overall, leaving room for small countries
            size = np.maximum(size - 1.7, small_font)
        sel = sel.assign(size=size)
        sel = sel[sel["size"] >= (small_font if detail else 5)].sort_values("size", ascending=False)

    def two_lines(name, longer_than=18):
        """Splits a long name at the space nearest its middle (very long names,
        such as "República Democrática do Congo", in three lines)."""
        if len(name) <= longer_than or " " not in name or LANG in ("zh", "ja"):
            return name
        if len(name) > 24:
            return "\n".join(textwrap.wrap(name, 12, break_on_hyphens=False,
                                           break_long_words=False))
        spaces = [i for i, ch in enumerate(name) if ch == " "]
        i = min(spaces, key=lambda i: abs(i - len(name) / 2))
        return name[:i] + "\n" + name[i + 1:]

    land_shape = prep(land.union_all())

    def label_countries(rows):
        for _, r in rows.iterrows():
            name = two_lines((str(r[col]) if r[col] else str(r["NAME"])).upper())
            main_part = max(getattr(r.geometry, "geoms", [r.geometry]), key=lambda g: g.area)
            spots = [shapely.geometry.Point(r["LABEL_X"], r["LABEL_Y"])] + label_points(main_part, 5)[:6]
            tries = [(name, r["size"], p) for p in spots]
            if (zones_map or detail) and r["size"] < 7.5:
                # small countries in crowded areas (Portugal, Benelux): a smaller
                # font, inside or just beside the country, also in two lines
                # (never over another country: only at sea or inside this one)
                around = spots + [p for p in beside(r["LABEL_X"], r["LABEL_Y"])
                                  if not land_shape.contains(p) or r.geometry.contains(p)]
                for fs in (small_font, 2.8) if detail else (small_font,):
                    tries += [(n, fs, p) for n in dict.fromkeys([name, two_lines(name, 0)])
                              for p in around]
            any(lab.text(p.x, p.y, shape(n), transform=pc, fontsize=fs,
                         color="#1d1d1d", ha="center", va="center",
                         fontweight="bold" if fs >= 8 else "normal", linespacing=0.95,
                         zorder=5, margin=2 if fs > 5 else 1)
                for n, fs, p in tries if inside_map(p))

    def label_islands():
        """Island groups (Azores, Canaries, Hawaii, Line Islands ...) in italics."""
        icol = f"NAME_{LANG.upper()}" if f"NAME_{LANG.upper()}" in islands.columns else "NAME"
        taken = {str(n).lower() for c in ("NAME", "NAME_EN", col) for n in countries[c]}
        groups = islands[(islands["FEATURECLA"] == "Island group") & (islands["SCALERANK"] >= 1)]
        groups = groups[groups.geometry.area < 100]             # not the West Indies, Sunda ...
        rows = [(names_.get(LANG, names_["en"]), shapely.geometry.Point(x, y).buffer(1.5))
                for x, y, names_ in EXTRA_ISLANDS]
        rows += [(str(r[icol] or r["NAME"]), r.geometry)
                 for _, r in groups.sort_values("SCALERANK").iterrows()
                 if str(r["NAME_EN"]).lower() not in taken and str(r[icol]).lower() not in taken]
        named = []              # areas of the groups already named: skip their islands
        for name, geom in rows:
            p = geom.representative_point()
            if any(a.contains(p) for a in named):
                continue        # e.g. Oahu or Maui once "Hawaiian Islands" is there
            for q in filter(inside_map, [p] + beside(p.x, p.y)):
                if lab.text(q.x, q.y, shape(name), transform=pc, fontsize=small_font + 0.3,
                            style="italic", color="#2b2b2b", ha="center", va="center",
                            zorder=5, margin=1):
                    named.append(geom.envelope.buffer(1.5))
                    break

    def label_marine():
        """Oceans (capitals, spaced letters) and the main seas, gulfs and bays."""
        mcol = f"name_{LANG}" if f"name_{LANG}" in marine.columns else "name"
        sea = marine[marine["scalerank"] <= 2].sort_values("scalerank")
        for _, r in sea.iterrows():
            name = str(r[mcol] or r["name_en"] or r["name"])
            ocean = r["featurecla"] == "ocean"
            if ocean and LANG not in ("zh", "ja", "ar"):
                name = " ".join(name.upper())
            main_part = max(getattr(r.geometry, "geoms", [r.geometry]), key=lambda g: g.area)
            spots = [polylabel(main_part, tolerance=0.5)] + label_points(main_part, 5)[:4]
            for p in filter(inside_map, spots):
                if lab.text(p.x, p.y, shape(name), transform=pc,
                            fontsize=10 if ocean else 6.5, style="italic",
                            color=OCEAN_COLOR if ocean else SEA_NAME_COLOR,
                            ha="center", va="center", zorder=5):
                    break

    def label_land_offsets():
        # The land part of a zone often merges with the nautical strip of the same
        # offset (eastern USA and the Atlantic −5), so it gets a label of its own
        on_land = is_land & ~antarctica & ~np.isnan(offset)
        land_regions = gpd.GeoDataFrame(
            [{"offset": float(v), "geometry": shapely.geometry.shape(g)}
             for g, v in rasterio.features.shapes(offset, mask=on_land,
                                                  transform=from_origin(-180, 90, res, res))],
            crs="EPSG:4326")
        land_regions = land_regions.assign(area=land_regions.geometry.area)
        land_regions = land_regions[land_regions["area"] >= 0.8].sort_values("area", ascending=False)
        label_offsets(land_regions, skip_near=8)

    label_countries(sel[sel["size"] >= 7.5])
    label_offsets(regions[small & (regions["area"] >= 3)])
    if zones_map:
        label_countries(sel[(sel["size"] >= 6) & (sel["size"] < 7.5)])
        if not detail:
            label_land_offsets()
    label_countries(sel[sel["size"] < (6 if zones_map else 7.5)])
    if zones_map and detail:    # in svg/pdf the small countries go before them
        label_land_offsets()
    if detail and names:
        label_islands()
    if zones_map:
        label_marine()
    label_offsets(regions[~small], skip_near=6 if zones_map else None)

    # Cylindrical maps: the offset of each 15° nautical strip under the map
    if zones_map and lat_lim:
        for h in range(-12, 13):
            lon = min(max(h * 15, -176.25), 176.25)
            ax.annotate(format_offset(h), (lon, lat_lim[0]), xycoords=pc._as_mpl_transform(ax),
                        xytext=(0, -3), textcoords="offset points", ha="center", va="top",
                        fontsize=8, fontweight="bold", color="#3b2a1e", annotation_clip=False)

    # Titles, colour scale and credits (mirrored for right-to-left languages)
    rtl = LANG in RTL
    x_text, ha = (0.985, "right") if rtl else (0.015, "left")
    when = T["mode_date"].format(date=date.isoformat()) if date else T["mode_std"]
    title, subtitle = ("title_zones", "subtitle_zones") if zones_map else ("title", "subtitle")
    fig.text(x_text, 0.965, shape(T[title].format(proj=T["proj"][projection])),
             fontsize=16, fontweight="bold", color="#222", ha=ha)
    fig.text(x_text, 0.94, shape(T[subtitle].format(mode=when)),
             fontsize=9.5, color="#555", ha=ha)

    if zones_map:
        dst_text = T["dst_date"].format(date=date.isoformat()) if date else T["dst_std"]
        land_colour, sea_colour = zone_colours(np.array([[0.0, 0.0]]), np.array([[True, False]]),
                                               np.zeros((1, 2), bool))[0, :, :3]
        handles = [mpatches.Patch(facecolor=land_colour, edgecolor=HATCH_COLOR, hatch="////",
                                  linewidth=0.4, label=shape(dst_text)),
                   mpatches.Patch(facecolor=sea_colour, edgecolor="#999", linewidth=0.4,
                                  label=shape(T["sea"]))]
        fig.legend(handles=handles, loc="lower right" if rtl else "lower left",
                   bbox_to_anchor=(0.985 if rtl else 0.015, 0.02), fontsize=8.5,
                   frameon=False, handlelength=2.2, handleheight=1.3)
    else:
        cax = fig.add_axes([0.75 if rtl else 0.03, 0.06, 0.22, 0.018])
        cb = fig.colorbar(im, cax=cax, orientation="horizontal",
                          ticks=np.arange(-limit, limit + 0.01, 1))
        cb.ax.tick_params(labelsize=8)
        cb.outline.set_linewidth(0.4)
        cb.set_label(shape(T["cbar"]), fontsize=8.5)
    fig.text(0.015 if rtl else 0.985, 0.012, shape(T["credit"]), fontsize=7, color="#888",
             ha="left" if rtl else "right")

    if output:
        fig.savefig(output, dpi=150)
        say("saved", path=output)
    if show or not output:
        plt.show()


# ----------------------------------------------------------------------------
def main():
    global T, LANG
    p = argparse.ArgumentParser(
        description="World map of the difference between solar time and official time.")
    p.add_argument("--mode", "-m", default="solar", choices=["solar", "zones"],
                   help="solar: solar time − official time (default); "
                        "zones: plain time-zone map, one colour per UTC offset")
    p.add_argument("--projection", "-p", default="equal-earth", choices=list(PROJECTIONS),
                   help="map projection (default: equal-earth)")
    p.add_argument("--lang", "-l", metavar="LANG",
                   help="language for texts and country names: " + ", ".join(LANGUAGES) +
                        " (default: system language, falling back to English)")
    p.add_argument("--date", metavar="YYYY-MM-DD",
                   help="use the legal time of this date (daylight saving included); "
                        "without it, standard time is used")
    p.add_argument("--limit", type=float, default=2.0,
                   help="difference in hours shown with the strongest colour (default: 2; "
                        "--mode solar only)")
    p.add_argument("--res", type=float, default=0.1,
                   help="grid resolution in degrees (default: 0.1)")
    p.add_argument("--simplify", type=float, default=0.02,
                   help="polygon simplification tolerance in degrees (default: 0.02)")
    p.add_argument("--sea-margin", type=float, default=1.5,
                   help="how far (degrees) each civil time zone extends into the sea "
                        "before the nautical zones take over (default: 1.5)")
    p.add_argument("--island-join", type=float, default=4.0,
                   help="join islands (and coasts) with the same UTC offset that are up to "
                        "about twice this many degrees apart into one zone outline; "
                        "0 = a separate outline around every island (default: 4)")
    p.add_argument("--no-names", action="store_true", help="hide country names")
    p.add_argument("--output", "-o",
                   help="output file: png, pdf or svg "
                        "(default: solar_time_map.png, or time_zones_map.png with --mode zones)")
    p.add_argument("--show", action="store_true", help="also open the map in a window")
    p.add_argument("--cache", default=os.path.join(os.path.expanduser("~"), ".cache", "solar_time_map"),
                   help="folder for downloaded data (default: %(default)s)")
    p.add_argument("--list-langs", action="store_true", help="list supported languages and exit")
    a = p.parse_args()

    if a.list_langs:
        for c in LANGUAGES:
            print(f"{c}  {TEXTS[c]['language']}")
        return

    if a.lang:
        LANG = normalise_language(a.lang)
        if LANG is None:
            p.error(f"unsupported language '{a.lang}'. Choose from: {', '.join(LANGUAGES)}")
    else:
        LANG = system_language()
    T = TEXTS[LANG]
    setup_fonts(LANG)
    if LANG in RTL and not NATIVE_RTL:
        try:
            import arabic_reshaper, bidi  # noqa: F401
        except ImportError:
            print("[warning] For correct Arabic text: pip install arabic-reshaper python-bidi")

    date = dt.date.fromisoformat(a.date) if a.date else None
    paths = get_data(a.cache)
    timezones = load_timezones(paths["timezones.zip"], date, a.simplify)
    land = gpd.read_file(paths["land.geojson"])
    countries = gpd.read_file(paths["countries.geojson"])
    marine = gpd.read_file(paths["marine.geojson"])
    islands = gpd.read_file(paths["regions.geojson"])

    output = a.output or ("time_zones_map.png" if a.mode == "zones" else "solar_time_map.png")
    offset, is_land, antarctica, dst, zones = compute_grid(timezones, land, a.res, a.sea_margin,
                                                            a.island_join)
    draw(offset, is_land, antarctica, dst, zones, land, countries, marine, islands,
         a.projection, a.limit, date, not a.no_names, output, a.show, a.mode, a.res)


if __name__ == "__main__":
    main()
