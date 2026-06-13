"""Підпис апаратним токеном ІІТ (E.Key Almaz-1C) через native-messaging host euscpnmh.

Контейнери на захищеному носії (ЗНКІ) не віддають приватний ключ — підпис робить
сам токен. UAPKI/cm-pkcs12 працює лише з файлами, тож для токена йдемо через
рідний хост ІІТ euscpnmh (його ставить «ІІТ Користувач ЦСК»). Хост говорить
JSON-RPC по stdio; протокол і структури з euscprpc.dylib та
референс-клієнтів EUSignES6 / SA-SignInfo.

Протокол:
  кадр = 4 байти довжини (LE) + рядок 'last' + base64(JSON-RPC)
  кожен складний параметр обгорнутий: {className, classVersion, classFields}
  бінарний параметр (тег-3) = EndUserByteArray{data: base64}

Потік (відповідає SA-SignInfo EndUserAgent.ts):
  Initialize -> SetUIMode(0) -> SetModeSettings(online)
  -> SetCMPSettings/SetTSPSettings/SetOCSPSettings (КНЕДП емітента)
  -> SetFileStoreSettings(кеш сертифікатів)
  -> GetKeyInfo(keyMedia) -> GetCertificatesByKeyInfo(keyInfo,[cmp],[port])
     (euscp САМ тягне сертифікат підписувача з КНЕДП за ключем)
  -> SaveCertificate ланцюга, КРІМ Key-Agreement-серта (інакше Sign -> code 50)
  -> CtxCreate -> CtxReadPrivateKey([ctx, keyMedia]) -> CtxSign(...)

Особливості:
  * ReadPrivateKey показує GUI -> у headless code 12; контекстний CtxSign не плутає
    підписний/шифрувальний сертифікати (глобальний Sign брав не той -> code 50).
  * CMP/TSP/OCSP-адреси потрібні з ПОВНИМ шляхом (.../services/cmp/), не лише хост.
  * CAdES-T валідує позначку часу онлайн у момент підпису -> треба досяжний OCSP,
    інакше CtxSign -> code 51.

ПІН передається лише у пам'яті (не логувати!). Апаратний токен має ліміт спроб
ПІН — невірний ПІН дає code 0x18 (спроба згоряє); помилки формату/носія до
автентифікації (code 2/0x11) спробу НЕ витрачають.
"""

from __future__ import annotations

import base64
import json
import os
import struct
import subprocess
import tempfile
from dataclasses import dataclass

# Стандартні шляхи інсталяції «ІІТ Користувач ЦСК» (euscpnmh.app) на macOS.
_DEFAULT_HOST = "/Applications/euscpnmh.app/Contents/MacOS/euscpnmh"
_DEFAULT_LIBDIR = "/Applications/euscpnmh.app/Contents/MacOS"
# origin браузерного розширення ІІТ — хост вимагає його як аргумент.
_ORIGIN = "chrome-extension://jffafkigfgmjafhpkoibhfefeaebmccg/"

# Коди помилок EUSign (з EUSignES6 euscpm.js).
EU_OK = 0
EU_BAD_PARAMETER = 0x02       # невірний формат виклику — спроба ПІН НЕ згоряє
EU_KEY_MEDIAS_FAILED = 0x11   # сбій носія до автентифікації — ПІН не перевірявся
EU_CANCELED_BY_GUI = 0x0C
EU_BAD_PRIVATE_KEY = 0x18     # невірний ПІН — спроба ЗГОРЯЄ
EU_BAD_CERT = 0x32            # 50: сертифікат не може бути використаний
EU_CERT_NOT_FOUND = 0x33      # 51: сертифікат не знайдено

# Типи підпису (EndUserSignType).
SIGN_TYPE_CADES_BES = 1
SIGN_TYPE_CADES_T = 4
# Алгоритм підпису DSTU 4145 з ГОСТ 34.311.
SIGN_ALGO_DSTU4145 = 1


class TokenError(RuntimeError):
    """Помилка взаємодії з токеном через euscpnmh (з кодом EUSign, якщо є)."""

    def __init__(self, method: str, code: int, message: str = "") -> None:
        self.method = method
        self.code = code
        super().__init__(f"{method} -> code={code} ({message})")


class TokenHostNotFound(RuntimeError):
    """euscpnmh не знайдено — потрібно встановити «ІІТ Користувач ЦСК»."""


def _byte_array(b64: str) -> dict:
    """Бінарний параметр (тег-3) як EndUserByteArray."""
    return {"className": "EndUserByteArray", "classVersion": 0,
            "classFields": {"data": b64}}


def _wrap(class_name: str, fields: dict) -> dict:
    """Обгортка структури EUSign: {className, classVersion, classFields}."""
    return {"className": class_name, "classVersion": 0, "classFields": fields}


@dataclass(frozen=True)
class TokenSignResult:
    """Результат підпису токеном."""

    container: bytes        # CMS-контейнер (CAdES-BES або CAdES-T)
    sign_type: int          # SIGN_TYPE_CADES_BES / SIGN_TYPE_CADES_T
    has_timestamp: bool     # чи містить timeStampToken


class EuscpnmhClient:
    """Тонкий JSON-RPC клієнт до native-messaging host euscpnmh."""

    def __init__(self, host_path: str | None = None, lib_dir: str | None = None) -> None:
        self._host = host_path or _DEFAULT_HOST
        self._libdir = lib_dir or _DEFAULT_LIBDIR
        if not os.path.exists(self._host):
            raise TokenHostNotFound(
                f"euscpnmh не знайдено: {self._host}. Встановіть «ІІТ Користувач ЦСК»."
            )
        env = dict(os.environ, DYLD_LIBRARY_PATH=self._libdir)
        self._p = subprocess.Popen(
            [self._host, _ORIGIN],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
        )
        self._id = 0

    def _raw(self, method: str, params: list | None = None) -> dict:
        self._id += 1
        req = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or []}
        data = json.dumps(req).encode("utf-8")
        assert self._p.stdin and self._p.stdout
        self._p.stdin.write(struct.pack("<I", len(data)) + data)
        self._p.stdin.flush()
        hdr = self._p.stdout.read(4)
        if len(hdr) < 4:
            raise TokenError(method, -1, "host died (no response)")
        ln = struct.unpack("<I", hdr)[0]
        raw = self._p.stdout.read(ln).decode("utf-8", "ignore")
        s = json.loads(raw)
        # відповідь: рядок 'last'+base64(JSON-RPC), або сам JSON
        payload = s[4:] if isinstance(s, str) and s.startswith("last") else s
        return json.loads(base64.b64decode(payload))

    def call(self, method: str, params: list | None = None) -> tuple:
        """Викликати метод -> (result, error_dict)."""
        r = self._raw(method, params)
        inner = r.get("result", {})
        return inner.get("result"), inner.get("error", {})

    def call_ok(self, method: str, params: list | None = None):
        """Викликати метод, кинути TokenError якщо code не 0/None."""
        result, err = self.call(method, params)
        code = err.get("code")
        if code not in (EU_OK, None):
            raise TokenError(method, code, err.get("message", ""))
        return result

    def close(self) -> None:
        try:
            if self._p.stdin:
                self._p.stdin.close()
        except Exception:
            pass
        self._p.terminate()

    def __enter__(self) -> "EuscpnmhClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _split_signing_chain(p7b_der: bytes) -> list[bytes]:
    """Розкласти p7b-бандл на DER-сертифікати, ВІДКИНУВШИ Key-Agreement-серт
    підписувача (інакше euscp чіпляє шифрувальний і Sign дає code 50)."""
    out: list[bytes] = []
    with tempfile.NamedTemporaryFile("wb", suffix=".p7b", delete=False) as f:
        f.write(p7b_der)
        p7path = f.name
    try:
        pem = subprocess.run(
            ["openssl", "pkcs7", "-inform", "DER", "-in", p7path, "-print_certs"],
            capture_output=True, text=True,
        ).stdout
    finally:
        os.unlink(p7path)
    for blk in pem.split("-----BEGIN CERTIFICATE-----")[1:]:
        cert_pem = ("-----BEGIN CERTIFICATE-----"
                    + blk.split("-----END CERTIFICATE-----")[0]
                    + "-----END CERTIFICATE-----\n")
        with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as cf:
            cf.write(cert_pem)
            cpath = cf.name
        try:
            info = subprocess.run(
                ["openssl", "x509", "-in", cpath, "-noout", "-ext", "keyUsage"],
                capture_output=True, text=True,
            ).stdout
            der = subprocess.run(
                ["openssl", "x509", "-in", cpath, "-outform", "DER"],
                capture_output=True,
            ).stdout
        finally:
            os.unlink(cpath)
        if "Key Agreement" in info and "Digital Signature" not in info:
            continue  # шифрувальний серт користувача — пропускаємо
        out.append(der)
    return out


def sign_file_with_token(
    file_path: str,
    pin: str,
    cmp_url: str,
    *,
    out_path: str | None = None,
    tsp_url: str | None = None,
    ocsp_url: str | None = None,
    with_timestamp: bool = False,
    type_index: int = 1,
    dev_index: int = 0,
    store_dir: str | None = None,
    host_path: str | None = None,
    lib_dir: str | None = None,
) -> TokenSignResult:
    """Підписати файл апаратним токеном ІІТ (E.Key Almaz-1C) headless.

    cmp_url — CMP-адреса КНЕДП-емітента з ПОВНИМ шляхом
              (напр. 'ca.tax.gov.ua/services/cmp/' для ДПС). euscp сам дотягне
              сертифікат підписувача за ключем носія.
    with_timestamp=True -> CAdES-T (квал. позначка часу, Art.26.4); потребує
              tsp_url і досяжного ocsp_url (інакше CtxSign -> code 51).
    type_index/dev_index — індекси носія з EnumKeyMediaTypes/Devices
              (E.Key Almaz-1C зазвичай type=1, dev=0).
    ПІН лише у пам'яті — не логувати.
    """
    out = out_path or file_path + ".p7s"
    with open(file_path, "rb") as fh:
        data_b64 = base64.b64encode(fh.read()).decode("ascii")

    store = os.path.abspath(store_dir or os.path.join(os.getcwd(), ".euscp_store"))
    os.makedirs(store, exist_ok=True)

    key_media = _wrap("EndUserKeyMedia", {
        "typeIndex": type_index, "devIndex": dev_index, "password": pin,
    })

    with EuscpnmhClient(host_path, lib_dir) as cli:
        cli.call_ok("Initialize")
        cli.call("SetUIMode", [0])  # headless, без GUI-діалогів
        cli.call_ok("SetModeSettings", [_wrap("EndUserModeSettings", {"offlineMode": False})])
        cli.call_ok("SetCMPSettings", [_wrap("EndUserCMPSettings", {
            "useCMP": True, "address": cmp_url, "port": "80", "commonName": "",
        })])
        if with_timestamp:
            if not tsp_url or not ocsp_url:
                raise TokenError("SetTSPSettings", -1,
                                 "CAdES-T потребує tsp_url і ocsp_url")
            cli.call_ok("SetTSPSettings", [_wrap("EndUserTSPSettings", {
                "getStamps": True, "address": tsp_url, "port": "80",
            })])
            cli.call_ok("SetOCSPAccessInfoModeSettings",
                        [_wrap("EndUserOCSPAccessInfoModeSettings", {"enabled": True})])
            cli.call_ok("SetOCSPSettings", [_wrap("EndUserOCSPSettings", {
                "useOCSP": True, "beforeStore": False, "address": ocsp_url, "port": "80",
            })])
        cli.call_ok("SetFileStoreSettings", [_wrap("EndUserFileStoreSettings", {
            "path": store, "checkCRLs": False, "autoRefresh": True, "ownCRLsOnly": False,
            "fullAndDeltaCRLs": False, "autoDownloadCRLs": False,
            "saveLoadedCerts": True, "expireTime": 3600,
        })])

        # дотягнути сертифікат підписувача з КНЕДП за ключем носія
        ki = cli.call_ok("GetKeyInfo", [key_media])
        pki_b64 = ki.get("classFields", {}).get("privateKeyInfo") if isinstance(ki, dict) else None
        if not pki_b64:
            raise TokenError("GetKeyInfo", -1, "немає privateKeyInfo у відповіді")
        certs = cli.call_ok("GetCertificatesByKeyInfo",
                            [_byte_array(pki_b64), [cmp_url], ["80"]])
        bundle_b64 = certs.get("classFields", {}).get("data") if isinstance(certs, dict) else (
            certs if isinstance(certs, str) else None)
        if bundle_b64:
            for der in _split_signing_chain(base64.b64decode(bundle_b64)):
                cli.call("SaveCertificate", [_byte_array(base64.b64encode(der).decode("ascii"))])

        # підпис через контекст (серт привʼязаний до контексту ключа)
        ctx = cli.call_ok("CtxCreate")
        pk_ctx = cli.call_ok("CtxReadPrivateKey", [ctx, key_media])
        sign_type = SIGN_TYPE_CADES_T if with_timestamp else SIGN_TYPE_CADES_BES
        cli.call("SetRuntimeParameter", ["SignType", sign_type])
        sig = cli.call_ok("CtxSign", [pk_ctx, SIGN_ALGO_DSTU4145, _byte_array(data_b64),
                                      False, True])
        cli.call("CtxFreePrivateKey", [pk_ctx])

        sig_b64 = sig.get("classFields", {}).get("data") if isinstance(sig, dict) else sig
        if not sig_b64:
            raise TokenError("CtxSign", -1, "порожній результат підпису")
        container = base64.b64decode(sig_b64)

    with open(out, "wb") as fh:
        fh.write(container)
    # timeStampToken OID 1.2.840.113549.1.9.16.2.14
    has_ts = bytes.fromhex("2a864886f70d010910020e") in container
    return TokenSignResult(
        container=container,
        sign_type=sign_type,
        has_timestamp=has_ts,
    )
