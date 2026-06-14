"""ASiC-контейнер (ETSI EN 319 162-1) — пакування detached-підписів у ZIP.

Пакування != підписання: спершу формуються detached-підписи (CAdES .p7s через
токен/UAPKI), потім вони складаються поруч у ZIP. Це знімає конфлікт стеків —
кожна підпис самодостатня, зливати в один CMS не треба.

Розкладка ASiC-E (CAdES):
  mimetype                          (STORED, перший: application/vnd.etsi.asic-e+zip)
  <datafile>                        (вихідні файли в корені)
  META-INF/signatureNNN.p7s         (detached CAdES кожного підписувача)
  META-INF/ASiCManifestNNN.xml      (обовʼязковий для CAdES; SigReference + digest
                                     кожного data-файла)

КЛЮЧОВЕ (інакше czo.gov.ua -> помилка 33): кожна підпис має ВЛАСНИЙ
ASiCManifestNNN.xml із SHA-256 DigestValue кожного data-файла, не лише URI.
"""

from __future__ import annotations

import base64
import hashlib
import os
import zipfile
from dataclasses import dataclass
from xml.sax.saxutils import escape

_MIME = {
    "asic-s": "application/vnd.etsi.asic-s+zip",
    "asic-e": "application/vnd.etsi.asic-e+zip",
}
_MIME_BY_EXT = {
    "pdf": "application/pdf", "xml": "application/xml", "txt": "text/plain",
    "html": "text/html", "htm": "text/html", "json": "application/json",
    "zip": "application/zip", "p7s": "application/pkcs7-signature",
}


def _mime_for(name: str) -> str:
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return _MIME_BY_EXT.get(ext, "application/octet-stream")


def _build_manifest(sig_uri: str, data_files: list[tuple[str, bytes]]) -> bytes:
    """ASiCManifest XML (EN 319 162-1 §A.4): SigReference + DataObjectReference
    із SHA-256 digest кожного data-файла."""
    refs = []
    for name, data in data_files:
        h = base64.b64encode(hashlib.sha256(data).digest()).decode("ascii")
        refs.append(
            f'  <asic:DataObjectReference URI="{escape(name)}" '
            f'MimeType="{escape(_mime_for(name))}">\n'
            f'    <ds:DigestMethod Algorithm="http://www.w3.org/2001/04/xmlenc#sha256"/>\n'
            f'    <ds:DigestValue>{h}</ds:DigestValue>\n'
            f'  </asic:DataObjectReference>'
        )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<asic:ASiCManifest xmlns:asic="http://uri.etsi.org/02918/v1.2.1#" '
        'xmlns:ds="http://www.w3.org/2000/09/xmldsig#">\n'
        f'  <asic:SigReference URI="{escape(sig_uri)}" '
        'MimeType="application/pkcs7-signature"/>\n'
        + "\n".join(refs) + "\n"
        '</asic:ASiCManifest>\n'
    ).encode("utf-8")


@dataclass(frozen=True)
class AsicSignature:
    """Одна detached-CAdES-підпис НАД МАНІФЕСТОМ для пакування.

    ВАЖЛИВО (ETSI EN 319 162-1 §A.4): у ASiC-E CAdES підпис покриває
    ASiCManifestNNN.xml (а той містить digest data-файлів), НЕ самі файли.
    cms тут — detached-CAdES над маніфестом, який повертає manifest_for().
    """
    cms: bytes          # detached .p7s над відповідним ASiCManifestNNN.xml
    label: str = ""


def manifest_for(sig_index: int, data_files: list[tuple[str, bytes]]) -> bytes:
    """Побудувати ASiCManifestNNN.xml, який підписувач має підписати detached.

    sig_index — 1-based номер підпису (signatureNNN.p7s).
    Повертає точні байти манІфеста; підпишіть саме їх (CAdES detached), а готовий
    .p7s передайте у build_asic_e як AsicSignature(cms).
    """
    idx = f"{sig_index:03d}"
    return _build_manifest(f"META-INF/signature{idx}.p7s", data_files)


def build_asic_e(
    data_files: list[tuple[str, bytes]],
    signatures: list[AsicSignature],
    out_path: str,
) -> str:
    """Зібрати ASiC-E (CAdES) контейнер.

    data_files — [(імʼя, байти), ...] вихідних файлів.
    signatures  — detached-CAdES-підписи НАД МАНІФЕСТАМИ (i-та підпис над
                  manifest_for(i+1, data_files)); порядок визначає NNN.
    Кожна підпис -> signatureNNN.p7s + власний ASiCManifestNNN.xml.
    """
    if not data_files:
        raise ValueError("потрібен щонайменше один файл даних")
    if not signatures:
        raise ValueError("потрібна щонайменше одна підпис")

    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        # mimetype — перший і STORED (EN 319 162-1 §A.1)
        zi = zipfile.ZipInfo("mimetype")
        zi.compress_type = zipfile.ZIP_STORED
        z.writestr(zi, _MIME["asic-e"])
        # файли даних у корені
        for name, data in data_files:
            z.writestr(name, data)
        # кожна підпис над своїм манІфестом
        for i, sig in enumerate(signatures, 1):
            idx = f"{i:03d}"
            z.writestr(f"META-INF/signature{idx}.p7s", sig.cms)
            z.writestr(f"META-INF/ASiCManifest{idx}.xml",
                       _build_manifest(f"META-INF/signature{idx}.p7s", data_files))
    return out_path


def build_asic_s(data_name: str, data: bytes, signature_cms: bytes, out_path: str) -> str:
    """Зібрати ASiC-S (один файл даних, одна detached-CAdES-підпис)."""
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as z:
        zi = zipfile.ZipInfo("mimetype")
        zi.compress_type = zipfile.ZIP_STORED
        z.writestr(zi, _MIME["asic-s"])
        z.writestr(data_name, data)
        z.writestr("META-INF/signature.p7s", signature_cms)
    return out_path


def read_asic(path: str) -> dict:
    """Розібрати ASiC: тип, файли даних, підписи, маніфести."""
    with zipfile.ZipFile(path) as z:
        names = z.namelist()
        mt = z.read("mimetype").decode("ascii") if "mimetype" in names else ""
        typ = "asic-s" if mt == _MIME["asic-s"] else (
            "asic-e" if mt == _MIME["asic-e"] else "unknown")
        out: dict = {"type": typ, "data_files": [], "signatures": [], "manifests": []}
        for n in names:
            if n == "mimetype":
                continue
            if not n.startswith("META-INF/"):
                out["data_files"].append(n)
            elif "ASiCManifest" in n:
                out["manifests"].append(n)
            elif n.lower().endswith(".p7s"):
                out["signatures"].append(n)
        return out
