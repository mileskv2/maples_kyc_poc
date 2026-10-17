"""Turn any uploaded file (PDF or photo) into page images and words with positions.

Every extractor works on the same shape: a list of lines, each a list of words
{text, x0, y0, x1, y1}. The PDF text layer and Tesseract both produce it, which is what
lets us run the same parser on both and compare them.
"""

from functools import lru_cache

import pymupdf
import pytesseract
import numpy as np
from PIL import Image, ImageFilter, ImageOps

DPI = 200
IMAGE_TYPES = {".jpg", ".jpeg", ".png"}


@lru_cache(maxsize=64)
def page_images(path):
    """Every page as a PIL image. Cached: classification and extraction both need them."""
    if path.suffix.lower() in IMAGE_TYPES:
        return [ImageOps.exif_transpose(Image.open(path)).convert("RGB")]
    images = []
    for page in pymupdf.open(path):
        pix = page.get_pixmap(dpi=DPI)
        images.append(Image.frombytes("RGB", (pix.width, pix.height), pix.samples))
    return images


def text_layer_words(path):
    """Words embedded in a PDF, scaled to page-image pixels. Empty for scans and photos."""
    if path.suffix.lower() != ".pdf":
        return []
    words, offset = [], 0
    scale = DPI / 72
    for page in pymupdf.open(path):
        for x0, y0, x1, y1, text, *_ in page.get_text("words"):
            words.append({"text": text, "x0": x0 * scale, "y0": y0 * scale + offset,
                          "x1": x1 * scale, "y1": y1 * scale + offset})
        offset += page.rect.height * scale  # stack pages so page 2 sits below page 1
    return words


def flatten_lighting(img):
    """Divide out the background (shadows, light gradients from phone photos) before OCR."""
    gray = ImageOps.grayscale(img)
    background = np.asarray(gray.filter(ImageFilter.GaussianBlur(25)), float) + 1
    flat = np.clip(np.asarray(gray, float) / background * 255, 0, 255).astype(np.uint8)
    return ImageOps.autocontrast(Image.fromarray(flat), cutoff=1)


def deskew(img):
    """Straighten a tilted page: the right angle makes text rows line up, so row darkness varies most."""
    small = img.resize((img.width // 4, img.height // 4))
    ink = np.asarray(small, float) < 128
    best, best_score = 0, -1
    for angle in np.arange(-5, 5.25, 0.25):
        rows = np.asarray(Image.fromarray(ink).rotate(angle, fillcolor=0)).sum(axis=1)
        if rows.var() > best_score:
            best, best_score = angle, rows.var()
    return img.rotate(best, fillcolor=255, expand=True)


def prepare_for_ocr(img):
    return deskew(flatten_lighting(img))


@lru_cache(maxsize=64)
def ocr_words(path):
    """Tesseract words across all pages, stacked top to bottom like text_layer_words."""
    words, offset = [], 0
    for img in page_images(path):
        data = pytesseract.image_to_data(prepare_for_ocr(img), output_type=pytesseract.Output.DICT)
        for i, text in enumerate(data["text"]):
            if text.strip() and float(data["conf"][i]) > 0:
                words.append({"text": text, "x0": data["left"][i], "y0": data["top"][i] + offset,
                              "x1": data["left"][i] + data["width"][i],
                              "y1": data["top"][i] + data["height"][i] + offset})
        offset += img.height
    return tuple(words)  # tuple so the cache can't be mutated by a caller


def group_lines(words):
    """Group words whose vertical centres are close into reading-order lines."""
    lines = []
    for w in sorted(words, key=lambda w: (w["y0"] + w["y1"]) / 2):
        mid = (w["y0"] + w["y1"]) / 2
        height = w["y1"] - w["y0"]
        if lines and abs(lines[-1]["mid"] - mid) < max(height, 1) * 0.6:
            lines[-1]["words"].append(w)
        else:
            lines.append({"mid": mid, "words": [w]})
    return [sorted(line["words"], key=lambda w: w["x0"]) for line in lines]


def full_text(path):
    """All readable text: the text layer if there is one, otherwise OCR."""
    words = text_layer_words(path) or ocr_words(path)
    return "\n".join(" ".join(w["text"] for w in line) for line in group_lines(words))
