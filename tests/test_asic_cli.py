"""Тести ASiC CLI (presentation) — без токена/мережі."""

from __future__ import annotations

import zipfile

from dilovod4.presentation.asic_cli import main


def test_cli_manifest_to_file(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.7 x\n")
    out = tmp_path / "m1.xml"
    rc = main(["manifest", str(pdf), "-n", "1", "-o", str(out)])
    assert rc == 0
    xml = out.read_text(encoding="utf-8")
    assert 'SigReference URI="META-INF/signature001.p7s"' in xml
    assert "xmlenc#sha256" in xml


def test_cli_pack_and_inspect(tmp_path, capsys):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"%PDF-1.7 content\n")
    s1 = tmp_path / "s1.p7s"
    s1.write_bytes(b"cms-signature-one")
    s2 = tmp_path / "s2.p7s"
    s2.write_bytes(b"cms-signature-two")
    out = tmp_path / "doc.asice"

    rc = main(["pack", str(pdf), "-s", str(s1), "-s", str(s2), "-o", str(out)])
    assert rc == 0
    z = zipfile.ZipFile(out)
    assert z.infolist()[0].filename == "mimetype"
    names = z.namelist()
    assert "META-INF/signature001.p7s" in names
    assert "META-INF/signature002.p7s" in names
    assert "META-INF/ASiCManifest001.xml" in names
    assert "META-INF/ASiCManifest002.xml" in names

    capsys.readouterr()  # очистити
    rc = main(["inspect", str(out)])
    assert rc == 0
    captured = capsys.readouterr()
    assert "asic-e" in captured.out
    assert "doc.pdf" in captured.out


def test_cli_pack_requires_signature(tmp_path):
    pdf = tmp_path / "doc.pdf"
    pdf.write_bytes(b"x")
    rc = main(["pack", str(pdf), "-o", str(tmp_path / "o.asice")])
    assert rc == 2
