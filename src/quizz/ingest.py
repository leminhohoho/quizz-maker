"""Normalize slides to PDF and extract per-page text and images for the agent."""

import hashlib
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pymupdf

from quizz import paths

SOFFICE_CANDIDATES = ["/Applications/LibreOffice.app/Contents/MacOS/soffice"]
PAGE_DPI = 110


class MissingDependency(RuntimeError):
    def __init__(self, message: str, hint: str):
        super().__init__(message)
        self.hint = hint


def _slug(stem: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", stem.lower()).strip("-") or "slides"


def _soffice() -> str:
    for name in ("soffice", "libreoffice"):
        found = shutil.which(name)
        if found:
            return found
    for candidate in SOFFICE_CANDIDATES:
        if Path(candidate).exists():
            return candidate
    raise MissingDependency(
        "LibreOffice is required to convert PPTX to PDF",
        hint="brew install --cask libreoffice (or export the slides to PDF yourself)",
    )


def _pptx_to_pdf(src: Path, out_dir: Path) -> Path:
    soffice = _soffice()
    with tempfile.TemporaryDirectory() as tmp:
        proc = subprocess.run(
            [soffice, "--headless", "--convert-to", "pdf", "--outdir", tmp, str(src)],
            capture_output=True,
            text=True,
            timeout=300,
        )
        produced = Path(tmp) / f"{src.stem}.pdf"
        if proc.returncode != 0 or not produced.exists():
            raise RuntimeError(f"LibreOffice conversion failed: {proc.stderr.strip() or proc.stdout.strip()}")
        target = out_dir / "source.pdf"
        shutil.move(produced, target)
        return target


def ingest(src: Path) -> dict:
    src = Path(src)
    suffix = src.suffix.lower()
    if suffix not in (".pdf", ".pptx"):
        raise ValueError(f"unsupported file type {suffix!r}; expected .pdf or .pptx")
    sha256 = hashlib.sha256(src.read_bytes()).hexdigest()
    out = paths.build_dir() / _slug(src.stem)
    pages_dir = out / "pages"
    if pages_dir.exists():
        shutil.rmtree(pages_dir)
    pages_dir.mkdir(parents=True)
    if suffix == ".pptx":
        pdf = _pptx_to_pdf(src, out)
    else:
        pdf = out / "source.pdf"
        shutil.copyfile(src, pdf)
    with pymupdf.open(pdf) as doc:
        for number, page in enumerate(doc, start=1):
            (pages_dir / f"{number:03d}.txt").write_text(page.get_text())
            page.get_pixmap(dpi=PAGE_DPI).save(pages_dir / f"{number:03d}.png")
        page_count = doc.page_count
    manifest = {"sha256": sha256, "pages": page_count, "filename": src.name}
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2))
    return {"pdf": str(pdf), "pages": page_count, "sha256": sha256, "dir": str(out)}
