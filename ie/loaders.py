"""Turn a PDF or image into text. Use the PDF text layer when present, otherwise OCR.

OCR needs the Tesseract binary plus `pytesseract` and Pillow. PDF rasterizing
uses poppler's `pdftoppm`. Both are free: `apt install tesseract-ocr poppler-utils`
(on macOS: `brew install tesseract poppler`).
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

MIN_TEXT_CHARS = 40  # below this, a PDF page is treated as scanned


@dataclass
class LoadedDoc:
    path: str
    text: str
    method: str  # "text-layer" | "ocr"
    pages: int
    ocr_confidence: float | None = None  # mean Tesseract word confidence 0-1


def _pdf_text(path: Path) -> tuple[str, int]:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    pages = []
    for p in reader.pages:
        try:
            pages.append(p.extract_text(extraction_mode="layout") or "")
        except TypeError:  # older pypdf without layout mode
            pages.append(p.extract_text() or "")
    return "\n\f\n".join(pages), len(reader.pages)


def _clean_for_ocr(img):
    """Denoise, binarize and deskew. These steps make the biggest difference on phone photos and faxes."""
    import numpy as np
    from PIL import ImageFilter

    img = img.convert("L").filter(ImageFilter.MedianFilter(3))
    img = img.point(lambda p: 255 if p > 150 else 0)
    best_angle, best_score = 0.0, -1.0
    for tenth in range(-30, 31, 3):  # search -3.0..+3.0 degrees
        ang = tenth / 10
        arr = np.asarray(img.rotate(ang, expand=True, fillcolor=255)) < 128
        prof = arr.sum(axis=1).astype(float)
        score = float(((prof[1:] - prof[:-1]) ** 2).sum())  # sharp row profile = level text lines
        if score > best_score:
            best_angle, best_score = ang, score
    return img.rotate(best_angle, expand=True, fillcolor=255)


def _ocr_image(img) -> tuple[str, float]:
    import pytesseract

    img = _clean_for_ocr(img)
    data = pytesseract.image_to_data(img, config="--psm 6", output_type=pytesseract.Output.DICT)
    confs = [float(c) for c, w in zip(data["conf"], data["text"]) if w.strip() and float(c) >= 0]
    text = pytesseract.image_to_string(img, config="--psm 6")
    return text, (sum(confs) / len(confs) / 100) if confs else 0.0


def _ocr_pdf(path: Path) -> tuple[str, int, float]:
    from PIL import Image

    if not shutil.which("pdftoppm"):
        raise RuntimeError("Scanned PDF needs OCR: install poppler-utils (pdftoppm) and tesseract-ocr")
    with tempfile.TemporaryDirectory() as tmp:
        subprocess.run(["pdftoppm", "-r", "300", "-png", str(path), f"{tmp}/p"], check=True, capture_output=True)
        texts, confs = [], []
        files = sorted(Path(tmp).glob("p*.png"))
        for f in files:
            t, c = _ocr_image(Image.open(f))
            texts.append(t)
            confs.append(c)
    return "\n\f\n".join(texts), len(files), (sum(confs) / len(confs) if confs else 0.0)


def load(path: str | Path) -> LoadedDoc:
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".pdf":
        text, pages = _pdf_text(path)
        if len(text.strip()) >= MIN_TEXT_CHARS * pages:
            return LoadedDoc(str(path), text, "text-layer", pages)
        text, pages, conf = _ocr_pdf(path)
        return LoadedDoc(str(path), text, "ocr", pages, conf)
    if suffix in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp"}:
        from PIL import Image

        text, conf = _ocr_image(Image.open(path))
        return LoadedDoc(str(path), text, "ocr", 1, conf)
    if suffix in {".txt", ".md"}:
        return LoadedDoc(str(path), path.read_text(encoding="utf-8"), "text-layer", 1)
    raise ValueError(f"Unsupported file type: {suffix}")
