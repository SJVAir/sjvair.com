from io import BytesIO

import numpy as np
from PIL import Image

from camp.apps.entries.levels import AQLevel, LevelSet


# Working ranges used to map each product's continuous column-density value
# onto SJVAir's existing six-color AQI palette. There is no official NAAQS
# crosswalk for column density (see the "Comparison Methodology" section of
# docs/superpowers/specs/2026-07-11-tempo-integration-design.md) -- these are
# a starting point, not a regulatory scale, and should be revisited once we
# have a few weeks of real ingested values to check the distribution against.
#
# no2: confirmed against NASA's own GIBS colormap max (0-3.0e16 molec/cm^2).
# o3tot: derived from the standard ~250-450 Dobson Unit range for total
#   column ozone, converted at 1 DU = 2.69e16 molec/cm^2 (a fixed physical
#   constant, not TEMPO-specific).
# hcho: estimated -- tropospheric HCHO columns are typically an order of
#   magnitude below NO2 hotspots. Needs recalibration against real data.
PRODUCT_COLOR_RANGES = {
    'no2': (0.0, 3.0e16),
    'o3tot': (6.7e18, 1.2e19),
    'hcho': (0.0, 2.0e16),
    'cldo4': (0.0, 1.0),  # cloud fraction is already 0-1; not user-facing but rendered for completeness
}

# Fraction of each product's range where each AQI color band starts.
_BAND_FRACTIONS = (0.0, 0.05, 0.15, 0.30, 0.55, 0.80)


def _level_set_for(product: str) -> LevelSet:
    low, high = PRODUCT_COLOR_RANGES[product]
    span = high - low
    breakpoints = [low + span * frac for frac in _BAND_FRACTIONS]
    return LevelSet(
        AQLevel.GOOD(breakpoints[0]),
        AQLevel.MODERATE(breakpoints[1]),
        AQLevel.UNHEALTHY_SENSITIVE(breakpoints[2]),
        AQLevel.UNHEALTHY(breakpoints[3]),
        AQLevel.VERY_UNHEALTHY(breakpoints[4]),
        AQLevel.HAZARDOUS(breakpoints[5]),
    )


def _hex_to_rgb(hex_color: str) -> tuple:
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i + 2], 16) for i in (0, 2, 4))


def render_preview(array: np.ndarray, product: str) -> bytes:
    """
    Colorizes a 2D array of column-density values into an RGBA PNG using
    SJVAir's AQI palette, scaled to `product`'s working range. NaN cells
    (masked/QA-flagged pixels) render fully transparent.
    """
    levels = _level_set_for(product)
    height, width = array.shape
    rgba = np.zeros((height, width, 4), dtype=np.uint8)

    valid = ~np.isnan(array)
    for y in range(height):
        for x in range(width):
            if not valid[y, x]:
                continue
            r, g, b = _hex_to_rgb(levels.get_color(float(array[y, x])))
            rgba[y, x] = (r, g, b, 255)

    image = Image.fromarray(rgba, mode='RGBA')
    buffer = BytesIO()
    image.save(buffer, format='PNG')
    return buffer.getvalue()
