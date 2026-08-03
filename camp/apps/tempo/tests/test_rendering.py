import numpy as np
from PIL import Image
from io import BytesIO

from camp.apps.tempo.rendering import render_preview


def test_render_preview_returns_valid_png():
    array = np.array([[0.0, 1.5e16], [3.0e16, np.nan]])
    png_bytes = render_preview(array, 'no2')

    image = Image.open(BytesIO(png_bytes))
    assert image.format == 'PNG'
    assert image.size == (2, 2)
    assert image.mode == 'RGBA'


def test_render_preview_masks_nan_as_transparent():
    array = np.array([[0.0, np.nan]])
    png_bytes = render_preview(array, 'no2')

    image = Image.open(BytesIO(png_bytes))
    pixels = np.array(image)
    assert pixels[0, 1, 3] == 0   # NaN cell: alpha channel is 0
    assert pixels[0, 0, 3] == 255  # valid cell: fully opaque


def test_render_preview_low_and_high_values_use_different_colors():
    array = np.array([[0.0, 3.0e16]])
    png_bytes = render_preview(array, 'no2')

    image = Image.open(BytesIO(png_bytes))
    pixels = np.array(image)
    assert tuple(pixels[0, 0][:3]) != tuple(pixels[0, 1][:3])
