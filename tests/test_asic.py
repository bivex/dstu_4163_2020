"""Тести ASiC-пакувальника (детерміновані, без токена/мережі)."""

from __future__ import annotations

import zipfile

import pytest

from dilovod4.infrastructure.asic import (
    AsicSignature,
    build_asic_e,
    build_asic_s,
    read_asic,
)


def test_asic_e_layout(tmp_path):
    data = b"%PDF-1.7 demo content\n"
    out = str(tmp_path / "doc.asice")
    build_asic_e(
        [("doc.pdf", data)],
        [AsicSignature(b"sig-one-cms"), AsicSignature(b"sig-two-cms")],
        out,
    )
    z = zipfile.ZipFile(out)
    infos = z.infolist()
    # mimetype перший і STORED
    assert infos[0].filename == "mimetype"
    assert infos[0].compress_type == zipfile.ZIP_STORED
    assert z.read("mimetype") == b"application/vnd.etsi.asic-e+zip"
    names = z.namelist()
    assert "doc.pdf" in names
    # дві підписи + два власних маніфести
    assert "META-INF/signature001.p7s" in names
    assert "META-INF/signature002.p7s" in names
    assert "META-INF/ASiCManifest001.xml" in names
    assert "META-INF/ASiCManifest002.xml" in names


def test_asic_e_manifest_has_digest(tmp_path):
    import base64
    import hashlib

    data = b"data to be hashed in manifest"
    out = str(tmp_path / "d.asice")
    build_asic_e([("a.pdf", data)], [AsicSignature(b"cms")], out)
    z = zipfile.ZipFile(out)
    manifest = z.read("META-INF/ASiCManifest001.xml").decode()
    # SigReference + DataObjectReference з правильним SHA-256 DigestValue
    assert 'SigReference URI="META-INF/signature001.p7s"' in manifest
    assert "xmlenc#sha256" in manifest
    expected = base64.b64encode(hashlib.sha256(data).digest()).decode()
    assert expected in manifest


def test_asic_s_single_file(tmp_path):
    out = str(tmp_path / "d.asics")
    build_asic_s("file.txt", b"hello", b"sig-cms", out)
    z = zipfile.ZipFile(out)
    assert z.read("mimetype") == b"application/vnd.etsi.asic-s+zip"
    assert z.read("file.txt") == b"hello"
    assert "META-INF/signature.p7s" in z.namelist()


def test_read_asic_roundtrip(tmp_path):
    out = str(tmp_path / "r.asice")
    build_asic_e([("x.pdf", b"x")], [AsicSignature(b"s1"), AsicSignature(b"s2")], out)
    info = read_asic(out)
    assert info["type"] == "asic-e"
    assert info["data_files"] == ["x.pdf"]
    assert len(info["signatures"]) == 2
    assert len(info["manifests"]) == 2


def test_asic_e_requires_data_and_signatures(tmp_path):
    out = str(tmp_path / "e.asice")
    with pytest.raises(ValueError):
        build_asic_e([], [AsicSignature(b"s")], out)
    with pytest.raises(ValueError):
        build_asic_e([("a", b"a")], [], out)
