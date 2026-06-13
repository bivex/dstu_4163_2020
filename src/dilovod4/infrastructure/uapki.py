"""UAPKI — Python-обгортка над нативною бібліотекою libuapki (ctypes).

Реальне підписання файлів ключем за українськими стандартами (ДСТУ 4145 та ін.)
через бібліотеку UAPKI (external/UAPKI). Уся взаємодія — через єдину C-функцію
`process(jsonRequest) -> jsonResponse` + `json_free` (так само, як офіційні
.NET/Java/Node.js інтеграції).

Це інфраструктурний адаптер: домен про UAPKI не знає. Обгортка піднімає КЕП із
реального контейнера підпису у доменну ElectronicSignatureMark (стик §4.4(22)
ДСТУ 4163 ↔ Art.18/24 Закону 2155-VIII).

Потрібна зібрана бібліотека:
    cd external/UAPKI/library && bash build-uapki.sh macos-arm64
    # створити симлінки major-версій у build/out/ (libuapki.dylib тощо)
Шлях задається через DILOVOD4_UAPKI_LIB (повний шлях до libuapki.<ver>.dylib)
або автопошуком у external/UAPKI/library/build/out.
"""

from __future__ import annotations

import base64
import ctypes
import json
import os
from dataclasses import dataclass
from pathlib import Path

from ..domain.model import CertificateStatus, ElectronicSignatureMark


class UapkiError(RuntimeError):
    """Помилка виклику UAPKI (errorCode != 0)."""

    def __init__(self, method: str, error_code: int, payload: dict) -> None:
        self.method = method
        self.error_code = error_code
        self.payload = payload
        msg = payload.get("error", "")
        super().__init__(f"UAPKI {method} -> errorCode={error_code} {msg}".strip())


class UapkiLibraryNotFound(RuntimeError):
    """Нативну libuapki не знайдено — потрібна збірка або явний шлях."""


_DEFAULT_BUILD_OUT = (
    Path(__file__).resolve().parents[3]
    / "external" / "UAPKI" / "library" / "build" / "out"
)

# Нативна libuapki — process-global singleton: один INIT на процес, повторний
# INIT після DEINIT не підтримується. Тримаємо стан ініціалізації на рівні модуля.
_PROCESS_INITIALIZED = False


def _resolve_library(explicit: str | None) -> str:
    candidates: list[Path] = []
    env = explicit or os.environ.get("DILOVOD4_UAPKI_LIB")
    if env:
        candidates.append(Path(env))
    if _DEFAULT_BUILD_OUT.is_dir():
        # major/unversioned symlink має пріоритет, далі — будь-який versioned
        candidates.append(_DEFAULT_BUILD_OUT / "libuapki.dylib")
        candidates.extend(sorted(_DEFAULT_BUILD_OUT.glob("libuapki.*.dylib")))
        candidates.extend(sorted(_DEFAULT_BUILD_OUT.glob("libuapki*.so")))
    for c in candidates:
        if c and c.is_file():
            return str(c)
    raise UapkiLibraryNotFound(
        "libuapki не знайдено. Зберіть (build-uapki.sh) або задайте DILOVOD4_UAPKI_LIB."
    )


class UapkiClient:
    """Тонкий клієнт над libuapki: JSON-запит -> JSON-відповідь.

    Керує lifecycle: INIT/OPEN/SELECT_KEY/SIGN/CLOSE/DEINIT. Працює як
    контекстний менеджер — гарантує CLOSE+DEINIT.
    """

    def __init__(self, library_path: str | None = None) -> None:
        self._lib_path = _resolve_library(library_path)
        lib_dir = os.path.dirname(self._lib_path)
        # Залежні бібліотеки (libuapkic/libuapkif/libcm-pkcs12) шукаються за
        # @rpath. DYLD_LIBRARY_PATH, виставлений у вже запущеному процесі, dlopen
        # не бачить — тож попередньо завантажуємо залежності у порядку залежностей,
        # щоб вони були в процесі на момент dlopen(libuapki).
        self._preloaded: list[ctypes.CDLL] = []
        for dep in ("libuapkic", "libuapkif", "libcm-pkcs12"):
            for cand in (
                os.path.join(lib_dir, f"{dep}.dylib"),
                *sorted(__import__("glob").glob(os.path.join(lib_dir, f"{dep}.*.dylib"))),
                os.path.join(lib_dir, f"{dep}.so"),
            ):
                if os.path.isfile(cand):
                    try:
                        self._preloaded.append(ctypes.CDLL(cand, mode=ctypes.RTLD_GLOBAL))
                        break
                    except OSError:
                        continue
        self._lib = ctypes.CDLL(self._lib_path)
        self._lib.process.restype = ctypes.c_void_p
        self._lib.process.argtypes = [ctypes.c_char_p]
        self._lib.json_free.argtypes = [ctypes.c_void_p]
        self._opened = False
        self._initialized = False

    # --- низькорівневий виклик ---
    def call(self, method: str, parameters: dict | None = None) -> dict:
        req: dict = {"method": method}
        if parameters is not None:
            req["parameters"] = parameters
        ptr = self._lib.process(json.dumps(req).encode("utf-8"))
        if not ptr:
            raise UapkiError(method, -1, {"error": "null response"})
        out = ctypes.string_at(ptr).decode("utf-8")
        self._lib.json_free(ptr)
        resp = json.loads(out)
        if resp.get("errorCode") != 0:
            raise UapkiError(method, int(resp.get("errorCode", -1)), resp.get("result", resp))
        return resp.get("result", {})

    def version(self) -> dict:
        return self.call("VERSION")

    # --- lifecycle ---
    def init(
        self,
        cert_cache_dir: str,
        crl_cache_dir: str,
        *,
        offline: bool = True,
        providers_dir: str | None = None,
    ) -> None:
        # cmProviders.dir має закінчуватися '/' — UAPKI будує шлях як
        # dir + 'lib' + name + '.dylib'. За замовчуванням — каталог libuapki,
        # де лежить і libcm-pkcs12.
        prov_dir = providers_dir or os.path.dirname(self._lib_path)
        global _PROCESS_INITIALIZED
        if _PROCESS_INITIALIZED:
            # бібліотека вже ініціалізована в цьому процесі — повторний INIT
            # native singleton не дозволяє; перевикористовуємо наявний стан.
            self._initialized = True
            return
        self.call("INIT", {
            "cmProviders": {"dir": _dir(prov_dir), "allowedProviders": [{"lib": "cm-pkcs12"}]},
            "certCache": {"path": _dir(cert_cache_dir), "trustedCerts": []},
            "crlCache": {"path": _dir(crl_cache_dir)},
            "offline": offline,
        })
        _PROCESS_INITIALIZED = True
        self._initialized = True

    def open_pkcs12(self, storage_path: str, password: str, *, mode: str = "RO") -> None:
        self.call("OPEN", {
            "provider": "PKCS12", "storage": storage_path,
            "password": password, "mode": mode,
        })
        self._opened = True

    def list_keys(self) -> list[dict]:
        return self.call("KEYS").get("keys", [])

    def select_key(self, key_id: str) -> dict:
        return self.call("SELECT_KEY", {"id": key_id})

    def sign_bytes(
        self,
        data: bytes,
        *,
        signature_format: str = "CMS",
        detached: bool = False,
        include_cert: bool = True,
        include_time: bool = True,
        doc_id: str = "doc-0",
    ) -> dict:
        """Підписати дані вибраним ключем. Повертає об'єкт підпису (bytes у base64)."""
        params: dict = {
            "signParams": {
                "signatureFormat": signature_format,
                "detachedData": detached,
            },
            "dataTbs": [{"id": doc_id, "bytes": base64.b64encode(data).decode("ascii")}],
        }
        if signature_format != "RAW":
            params["signParams"]["includeCert"] = include_cert
            params["signParams"]["includeTime"] = include_time
        result = self.call("SIGN", params)
        return result["signatures"][0]

    def sign_file(self, path: str, **kw) -> dict:
        """Підписати вміст файла на диску."""
        with open(path, "rb") as fh:
            return self.sign_bytes(fh.read(), **kw)

    def close(self) -> None:
        if self._opened:
            try:
                self.call("CLOSE")
            finally:
                self._opened = False
        # DEINIT навмисно не викликаємо: native singleton не підтримує повторний
        # INIT після DEINIT у тому ж процесі. Ініціалізація лишається на рівні
        # модуля до завершення процесу.
        self._initialized = False

    def __enter__(self) -> "UapkiClient":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _dir(path: str) -> str:
    """Нормалізувати каталог кешу до вигляду з кінцевим '/' (UAPKI цього очікує)."""
    p = path if path.endswith("/") else path + "/"
    return p


@dataclass(frozen=True)
class SignResult:
    """Результат підписання: контейнер + дані для доменної відмітки."""

    container: bytes  # CMS/CAdES контейнер (декодований з base64)
    signing_time: str | None
    key_id: str
    cert_serial: str
    signature_format: str

    def to_signature_mark(
        self,
        *,
        signer: str,
        issuer: str,
        valid_from: str,
        valid_to: str,
        is_qualified: bool = True,
        status: CertificateStatus = CertificateStatus.ACTIVE,
    ) -> ElectronicSignatureMark:
        """Зібрати доменну ElectronicSignatureMark з результату підписання.

        signer/issuer/valid_* поки що передаються явно (повний розбір X.509 із
        контейнера — наступний крок через uapkif/CERT_INFO). timestamp береться з
        кваліфікованої позначки часу UAPKI, якщо є.
        """
        return ElectronicSignatureMark(
            signer=signer,
            certificate_serial=self.cert_serial,
            issuer=issuer,
            valid_from=valid_from,
            valid_to=valid_to,
            timestamp=self.signing_time or "",
            is_qualified=is_qualified,
            status=status,
        )


def sign_file_pkcs12(
    file_path: str,
    pkcs12_path: str,
    password: str,
    *,
    cert_cache_dir: str,
    crl_cache_dir: str,
    key_id: str | None = None,
    signature_format: str = "CMS",
    detached: bool = False,
    library_path: str | None = None,
) -> SignResult:
    """Високорівнева зручність: підписати файл ключем із PKCS#12-контейнера.

    Виконує весь lifecycle INIT->OPEN->SELECT_KEY->SIGN->CLOSE->DEINIT і повертає
    SignResult. key_id=None -> береться перший ключ контейнера.
    """
    with UapkiClient(library_path) as client:
        client.init(cert_cache_dir, crl_cache_dir, offline=True)
        client.open_pkcs12(pkcs12_path, password)
        keys = client.list_keys()
        if not keys:
            raise UapkiError("KEYS", -1, {"error": "no keys in container"})
        kid = key_id or keys[0]["id"]
        sel = client.select_key(kid)
        cert_serial = sel.get("certId", "") or ""
        sig = client.sign_bytes(
            _read(file_path),
            signature_format=signature_format,
            detached=detached,
        )
        return SignResult(
            container=base64.b64decode(sig["bytes"]),
            signing_time=sig.get("signingTime"),
            key_id=kid,
            cert_serial=cert_serial,
            signature_format=signature_format,
        )


def _read(path: str) -> bytes:
    with open(path, "rb") as fh:
        return fh.read()
