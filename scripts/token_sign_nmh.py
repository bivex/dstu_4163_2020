#!/usr/bin/env python3
"""Підпис файла апаратним токеном ІІТ (E.Key Almaz-1C) через euscpnmh.

Йде через native-messaging host euscpnmh (він сам піднімає контекст бібліотеки —
на відміну від прямого виклику euscp.dylib, який падає на WRITE_SETTINGS).
Протокол: 4-байтова довжина (LE) + рядок 'last' + base64(JSON-RPC).

PIN береться з оточення TOKEN_PIN — НЕ передавайте його в аргументах.

УВАГА: апаратний токен має ліміт невірних PIN (зазвичай 3) -> блокування.
Скрипт робить РІВНО ОДНЕ читання ключа. Якщо формат методу невірний, повернеться
BAD_PARAMETER (code 2) — спроба PIN при цьому НЕ згоряє (помилка до аутентифікації).
Реальний невірний PIN -> code 0x18 (BAD_PRIVATE_KEY). Звіряйте код перед повтором.

Запуск:
    TOKEN_PIN='...' python3 scripts/token_sign_nmh.py <файл> [out.p7s]
"""

from __future__ import annotations

import base64
import json
import os
import struct
import subprocess
import sys

HOST = "/Applications/euscpnmh.app/Contents/MacOS/euscpnmh"
MAC = "/Applications/euscpnmh.app/Contents/MacOS"
ORIGIN = "chrome-extension://jffafkigfgmjafhpkoibhfefeaebmccg/"

# тип/пристрій носія з EnumKeyMediaTypes/Devices (підтверджено: Алмаз-1К, 803383)
TOKEN_TYPE_INDEX = int(os.environ.get("TOKEN_TYPE_INDEX", "1"))
TOKEN_DEV_INDEX = int(os.environ.get("TOKEN_DEV_INDEX", "0"))
# CMP-адреса КНЕДП, що видав сертифікат (з реєстру CAs.json). Типово — ДПС.
CMP_URL = os.environ.get("TOKEN_CMP", "ca.tax.gov.ua/services/cmp/")

# коди помилок EUSign (з EUSignES6 euscpm.js)
EU_OK = 0
EU_BAD_PARAMETER = 0x02         # невірний формат виклику — спроба PIN НЕ згоряє
EU_BAD_PRIVATE_KEY = 0x18       # невірний PIN — спроба ЗГОРАЄ
EU_KEY_MEDIAS_FAILED = 0x11


class Nmh:
    def __init__(self) -> None:
        env = dict(os.environ, DYLD_LIBRARY_PATH=MAC)
        self.p = subprocess.Popen(
            [HOST, ORIGIN],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env,
        )
        self._id = 0

    def call(self, method: str, params=None) -> dict:
        self._id += 1
        req = {"jsonrpc": "2.0", "id": self._id, "method": method, "params": params or []}
        data = json.dumps(req).encode("utf-8")
        self.p.stdin.write(struct.pack("<I", len(data)) + data)
        self.p.stdin.flush()
        hdr = self.p.stdout.read(4)
        if len(hdr) < 4:
            raise RuntimeError(f"no response to {method} (host died)")
        ln = struct.unpack("<I", hdr)[0]
        raw = self.p.stdout.read(ln).decode("utf-8", "ignore")
        s = json.loads(raw)
        payload = s[4:] if isinstance(s, str) and s.startswith("last") else s
        return json.loads(base64.b64decode(payload))

    def res(self, method: str, params=None):
        r = self.call(method, params)
        inner = r.get("result", {})
        return inner.get("result"), inner.get("error", {})

    def close(self) -> None:
        try:
            self.p.stdin.close()
        except Exception:
            pass
        self.p.terminate()


def main(argv: list[str]) -> int:
    if not argv:
        print("usage: TOKEN_PIN='...' python3 token_sign_nmh.py <file> [out.p7s]")
        return 2
    pin = os.environ.get("TOKEN_PIN")
    if not pin:
        print("set TOKEN_PIN env var (do not pass PIN on the command line)")
        return 2

    src = argv[0]
    out = argv[1] if len(argv) > 1 else src + ".p7s"
    with open(src, "rb") as fh:
        data = fh.read()
    data_b64 = base64.b64encode(data).decode("ascii")

    nmh = Nmh()
    try:
        _, e = nmh.res("Initialize")
        print("Initialize:", e.get("message"))

        # headless: без GUI-діалогів
        nmh.res("SetUIMode", [0])

        # онлайн-режим + CMP, щоб бібліотека сама дотягла сертифікат за ключем
        # (code 51 CERT_NOT_FOUND інакше — серта нема в локальному кеші).
        # поля з EUSignES6: EndUserModeSettings.offlineMode,
        # EndUserCMPSettings{useCMP,address,port,commonName}.
        mode = {
            "className": "EndUserModeSettings", "classVersion": 0,
            "classFields": {"offlineMode": False},
        }
        m_set, e1 = nmh.res("SetModeSettings", [mode])
        print(f"SetModeSettings(online): code={e1.get('code')} ({e1.get('message')})")
        cmp = {
            "className": "EndUserCMPSettings", "classVersion": 0,
            "classFields": {
                "useCMP": True,
                "address": "ca.monobank.ua",
                "port": "80",
                "commonName": "",
            },
        }
        c_set, e2 = nmh.res("SetCMPSettings", [cmp])
        print(f"SetCMPSettings: code={e2.get('code')} ({e2.get('message')})")

        # файлове сховище сертифікатів (інакше SaveCertificate -> code 49 STORAGE_FAILED).
        # поля з EUSignES6 EndUserFileStoreSettings.
        store_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                                 ".euscp_store")
        store_dir = os.path.abspath(store_dir)
        os.makedirs(store_dir, exist_ok=True)
        fs = {
            "className": "EndUserFileStoreSettings", "classVersion": 0,
            "classFields": {
                "path": store_dir,
                "checkCRLs": False,
                "autoRefresh": True,
                "ownCRLsOnly": False,
                "fullAndDeltaCRLs": False,
                "autoDownloadCRLs": False,
                "saveLoadedCerts": True,
                "expireTime": 3600,
            },
        }
        _, efs = nmh.res("SetFileStoreSettings", [fs])
        print(f"SetFileStoreSettings: code={efs.get('code')} ({efs.get('message')}) path={store_dir}")

        # Нативний флоу резолву серта (з SA-SignInfo EndUserAgent.ts
        # SearchPrivateKeyCertificatesWithCMP): GetKeyInfo(keyMedia) -> keyInfo,
        # потім GetCertificatesByKeyInfo(keyInfo,[cmp],["80"]) — euscp САМ тягне
        # own-сертифікат за ключем через CMP і привʼязує його.
        token_key_media = {
            "className": "EndUserKeyMedia", "classVersion": 0,
            "classFields": {
                "typeIndex": TOKEN_TYPE_INDEX,
                "devIndex": TOKEN_DEV_INDEX,
                "password": pin,
            },
        }
        ki, eki = nmh.res("GetKeyInfo", [token_key_media])
        print(f"GetKeyInfo: code={eki.get('code')} ({eki.get('message')})")
        if eki.get("code") in (0, None) and ki is not None:
            # keyInfo: беремо поле privateKeyInfo і обгортаємо у EndUserByteArray (тег-3)
            # (з euscp.app.js: e = e.GetPrivateKeyInfo(); new ByteArray(e)).
            pki_b64 = ki.get("classFields", {}).get("privateKeyInfo")
            key_info_ba = {
                "className": "EndUserByteArray", "classVersion": 0,
                "classFields": {"data": pki_b64},
            }
            # КНЕДП — ДПС (ca.tax.gov.ua), не monobank. euscp бере keyInfo прямо
            # з токена (правильний SKI самого носія) і тягне own-серт із ДПС.
            certs, egc = nmh.res("GetCertificatesByKeyInfo",
                                 [key_info_ba, [CMP_URL], ["80"]])
            print(f"GetCertificatesByKeyInfo: code={egc.get('code')} ({egc.get('message')}) "
                  f"certs={len(certs) if isinstance(certs, list) else certs!r}")
            if egc.get("code") in (0, None) and certs:
                def byte_array(b64s: str) -> dict:
                    return {"className": "EndUserByteArray", "classVersion": 0,
                            "classFields": {"data": b64s}}
                # результат — EndUserByteArray із p7b (CMS-бандл усієї ланцюга).
                b64 = certs.get("classFields", {}).get("data") if isinstance(certs, dict) else (
                    certs if isinstance(certs, str) else None)
                if b64:
                    # p7b містить ДВА серти підписувача (Digital Signature та Key
                    # Agreement) + ланцюг CA. Якщо зберегти весь бандл — euscp чіпляє
                    # шифрувальний -> Sign code 50. Якщо лише підписний — нема ланцюга
                    # -> ReadKey code 51. Рішення: зберегти ВСЕ, КРІМ Key Agreement-
                    # серта підписувача (підписний + CA лишаються).
                    import subprocess as _sp, tempfile as _tf
                    saved = 0
                    skipped = 0
                    try:
                        p7 = base64.b64decode(b64)
                        with _tf.NamedTemporaryFile("wb", suffix=".p7b", delete=False) as _f:
                            _f.write(p7); _p7path = _f.name
                        pem = _sp.run(["openssl", "pkcs7", "-inform", "DER", "-in", _p7path,
                                       "-print_certs"], capture_output=True, text=True).stdout
                        os.unlink(_p7path)
                        for blk in pem.split("-----BEGIN CERTIFICATE-----")[1:]:
                            cert_pem = "-----BEGIN CERTIFICATE-----" + \
                                blk.split("-----END CERTIFICATE-----")[0] + \
                                "-----END CERTIFICATE-----\n"
                            with _tf.NamedTemporaryFile("w", suffix=".pem", delete=False) as _cf:
                                _cf.write(cert_pem); _cpath = _cf.name
                            info = _sp.run(["openssl", "x509", "-in", _cpath, "-noout",
                                            "-ext", "keyUsage"],
                                           capture_output=True, text=True).stdout
                            der = _sp.run(["openssl", "x509", "-in", _cpath, "-outform", "DER"],
                                          capture_output=True).stdout
                            os.unlink(_cpath)
                            # пропускаємо шифрувальний серт користувача (Key Agreement)
                            if "Key Agreement" in info and "Digital Signature" not in info:
                                skipped += 1
                                continue
                            _, es = nmh.res("SaveCertificate",
                                            [byte_array(base64.b64encode(der).decode("ascii"))])
                            if es.get("code") in (0, None):
                                saved += 1
                        print(f"SaveCertificate: {saved} збережено, {skipped} Key-Agreement пропущено")
                    except Exception as exc:
                        print(f"  p7b filter skipped: {exc}")
                        _, es = nmh.res("SaveCertificates", [byte_array(b64)])
                        print(f"SaveCertificates(fallback): code={es.get('code')} ({es.get('message')})")


        # КОНТЕКСТНИЙ шлях (як основний у SA-SignInfo): сертифікат привʼязаний до
        # контексту ключа, тому глобальний Sign не плутає підписний/шифрувальний.
        #   CtxCreate() -> ctx; CtxReadPrivateKey([ctx, keyMedia]);
        #   CtxSign([ctx, signAlgo, byteArray(data), external=False, appendCert=True])
        key_media = {
            "className": "EndUserKeyMedia", "classVersion": 0,
            "classFields": {
                "typeIndex": TOKEN_TYPE_INDEX,
                "devIndex": TOKEN_DEV_INDEX,
                "password": pin,
            },
        }
        ctx, ec = nmh.res("CtxCreate")
        print(f"CtxCreate: code={ec.get('code')} ({ec.get('message')})")
        pk_ctx, erk = nmh.res("CtxReadPrivateKey", [ctx, key_media])
        code = erk.get("code", -1)
        print(f"CtxReadPrivateKey: code={code} ({erk.get('message')})")
        if code == EU_BAD_PRIVATE_KEY:
            print("  -> НЕВІРНИЙ PIN. Спроба ЗГОРІЛА. Перевірте залишок спроб у GUI ІІТ!")
            return 4
        if code not in (EU_OK, None):
            print(f"  -> читання ключа не вдалося ({code}).")
            return 6

        # CtxSign: signAlgo DSTU4145WithGOST34311 = 1, external=False, appendCert=True
        data_ba = {"className": "EndUserByteArray", "classVersion": 0,
                   "classFields": {"data": data_b64}}
        sig, e = nmh.res("CtxSign", [pk_ctx, 1, data_ba, False, True])
        print(f"CtxSign: code={e.get('code')} ({e.get('message')})")
        if e.get("code") in (EU_OK, None) and sig:
            sig_b64 = sig.get("classFields", {}).get("data") if isinstance(sig, dict) else sig
            if sig_b64:
                container = base64.b64decode(sig_b64)
                with open(out, "wb") as fh:
                    fh.write(container)
                print(f"OK: signed -> {out} ({len(container)} bytes)")
                nmh.res("CtxFreePrivateKey", [pk_ctx])
                return 0
        return 7
    finally:
        nmh.close()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
