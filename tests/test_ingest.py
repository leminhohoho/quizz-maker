import hashlib
import json

import pymupdf
import pytest

from quizz import ingest


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("QUIZZ_HOME", str(tmp_path / "home"))
    return tmp_path / "home"


def make_pdf(path, texts):
    doc = pymupdf.open()
    for text in texts:
        page = doc.new_page()
        page.insert_text((72, 72), text)
    doc.save(path)
    return path


def test_pdf_ingest_writes_pages_and_manifest(tmp_path, home):
    src = make_pdf(tmp_path / "Week 3 - Enthalpy.pdf", ["Hess's law", "Bond enthalpies"])
    info = ingest.ingest(src)
    out = home / "build" / "week-3-enthalpy"
    assert info["dir"] == str(out)
    assert info["pages"] == 2
    assert info["sha256"] == hashlib.sha256(src.read_bytes()).hexdigest()
    assert "Hess's law" in (out / "pages" / "001.txt").read_text()
    assert "Bond enthalpies" in (out / "pages" / "002.txt").read_text()
    assert (out / "pages" / "002.png").read_bytes()[:4] == b"\x89PNG"
    assert (out / "source.pdf").exists()
    manifest = json.loads((out / "manifest.json").read_text())
    assert manifest == {"sha256": info["sha256"], "pages": 2, "filename": src.name}


def test_reingest_replaces_stale_pages(tmp_path, home):
    src = make_pdf(tmp_path / "deck.pdf", ["a", "b", "c"])
    ingest.ingest(src)
    make_pdf(src, ["only one"])
    ingest.ingest(src)
    assert sorted(p.name for p in (home / "build" / "deck" / "pages").iterdir()) == ["001.png", "001.txt"]


def test_pptx_without_libreoffice_reports_missing_dependency(tmp_path, monkeypatch):
    monkeypatch.setenv("PATH", str(tmp_path))
    monkeypatch.setattr(ingest, "SOFFICE_CANDIDATES", [])
    deck = tmp_path / "deck.pptx"
    deck.write_bytes(b"PK\x03\x04")
    with pytest.raises(ingest.MissingDependency) as err:
        ingest.ingest(deck)
    assert "libreoffice" in err.value.hint


def test_unsupported_extension(tmp_path):
    f = tmp_path / "notes.docx"
    f.write_bytes(b"x")
    with pytest.raises(ValueError, match="pdf"):
        ingest.ingest(f)
