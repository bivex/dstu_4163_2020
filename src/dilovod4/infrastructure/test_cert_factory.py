"""Генератор тестових сертифікатів (X.509) для розробки й тестів підписання.

Будує міні-тестовий PKI поверх ``cryptography`` (без нативних залежностей):
тестовий CA + листя двох типів, що їх парсить ``cert_info_from_cms`` і приймає
EUSign/openssl/UAPKI:

- **eSign** — кваліфікований сертифікат фізичної особи (КЕП). Subject:
  ``CN=ПІБ``, ``serialNumber=РНОКПП``; QC statement ``QcType=eSign``;
  ``keyUsage=nonRepudiation``.
- **eSeal** — кваліфікований сертифікат печатки юридичної особи/ФОП. Subject:
  ``CN=назва юрособи``, ``O=назва``, ``organizationIdentifier=NTRUA-ЄДРПОУ``
  (схема NTR за ETSI EN 319 412-5, як у реальних українських сертифікатах);
  QC statement ``QcType=eSeal``; ``keyUsage=nonRepudiation``.

За замовчуванням ключі — ECDSA P-256 (как у Дія/ДПС, криптографічно валідні,
повністю сумісні з EUSign/openssl/UAPKI). Опційно ``dstu=True`` намагається
згенерувати справжній ДСТУ-4145 ключ через нативну libuapki (feature-detection,
прозорий fallback на ECDSA, якщо бібліотека не зібрана або cryptography не
парсить DSTU SubjectPublicKeyInfo).

Це **тільки для тестів** — приватний ключ CA повертається у відкритому вигляді.
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.hazmat.primitives.serialization import pkcs12 as _pkcs12
from cryptography.x509.oid import NameOID, ObjectIdentifier

if TYPE_CHECKING:
    from cryptography.hazmat.primitives.asymmetric import ec as _ec  # noqa: F401

_log = logging.getLogger(__name__)

# --- OID (ETSI EN 319 412-5 + X.520) -----------------------------------
# Розширення qcStatements — контейнер для QC-тверджень сертифіката.
OID_QC_STATEMENTS_EXT = ObjectIdentifier("1.3.6.1.5.5.7.1.3")
# QC type: електронний підпис особи / електронна печатка організації.
OID_QC_TYPE_ESIGN = "0.4.0.1862.1.5.1"
OID_QC_TYPE_ESEAL = "0.4.0.1862.1.5.3"
# QC compliance (наявність SSCD) — statementInfo відсутній.
OID_QC_SSCD = "0.4.0.1862.1.4"
# organizationIdentifier (X.520 attribute 2.5.4.97) — за EEA-схемою (NTR/VAT/PSD).
OID_ORGANIZATION_IDENTIFIER = NameOID.ORGANIZATION_IDENTIFIER  # 2.5.4.97

# --- DSTU 4145 (UAPKI) -------------------------------------------------
# Алгоритм ДСТУ 4145 + GOST 34.311 та параметри кривої M257_PB.
DSTU_MECHANISM_OID = "1.2.804.2.1.1.1.1.3.1.1"
DSTU_CURVE_M257PB_OID = "1.2.804.2.1.1.1.1.3.1.1.2.6"
DSTU_SIGN_ALGO_OID = "1.2.804.2.1.1.1.1.3.1.1"


@dataclass(frozen=True)
class CaKey:
    """Тестовий CA: сертифікат (DER) + приватний ключ."""

    cert: x509.Certificate
    key: object  # ECDSA private key (DSTU не підтримується cryptography як CA-ключ)

    @property
    def cert_der(self) -> bytes:
        return self.cert.public_bytes(serialization.Encoding.DER)

    @property
    def cert_pem(self) -> bytes:
        return self.cert.public_bytes(serialization.Encoding.PEM)


@dataclass(frozen=True)
class LeafKey:
    """Лист-сертифікат (eSign/eSeal): сертифікат + приватний ключ."""

    cert: x509.Certificate
    key: object  # ECDSA (або DSTU-обгортка, але cryptography вміє лише ECDSA sign)
    cert_type: str  # "esign" | "eseal"

    @property
    def cert_der(self) -> bytes:
        return self.cert.public_bytes(serialization.Encoding.DER)

    @property
    def cert_pem(self) -> bytes:
        return self.cert.public_bytes(serialization.Encoding.PEM)

    @property
    def subject_cn(self) -> str:
        try:
            return self.cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value
        except IndexError:
            return ""


# --- ASN.1 helpers (мінімальний DER-енкодер для QC statements) --------

def _enc_oid(oid: str) -> bytes:
    """DER-кодування OBJECT IDENTIFIER."""
    parts = [int(p) for p in oid.split(".")]
    first = parts[0] * 40 + parts[1]
    body = bytearray([first])
    for p in parts[2:]:
        if p == 0:
            body.append(0)
            continue
        chunks: list[int] = []
        while p > 0:
            chunks.append(p & 0x7F)
            p >>= 7
        chunks.reverse()
        for i, c in enumerate(chunks):
            body.append(c | (0x80 if i < len(chunks) - 1 else 0))
    return b"\x06" + bytes([len(body)]) + bytes(body)


def _enc_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    out: list[int] = []
    while n:
        out.insert(0, n & 0xFF)
        n >>= 8
    return bytes([0x80 | len(out)]) + bytes(out)


def _enc_seq(content: bytes) -> bytes:
    return b"\x30" + _enc_len(len(content)) + content


def _qc_statements_extension(qc_type_oid: str) -> x509.UnrecognizedExtension:
    """qcStatements (1.3.6.1.5.5.7.1.3) = SEQUENCE OF SEQUENCE{ statementId OID }.

    Кожне твердження — ``SEQUENCE { statementId OID }`` без statementInfo
    (достатньо для ідентифікації типу eSign/eSeal парсером).
    """
    statements = _enc_seq(_enc_oid(qc_type_oid)) + _enc_seq(_enc_oid(OID_QC_SSCD))
    value = _enc_seq(statements)
    return x509.UnrecognizedExtension(OID_QC_STATEMENTS_EXT, value)


# --- ключі ---------------------------------------------------------------

def _generate_keypair(dstu: bool = False) -> object:
    """Згенерувати ключ сертифіката.

    Завжди повертає ECDSA P-256 — ``cryptography`` не підтримує DSTU 4145 ані як
    криву, ані як алгоритм підпису сертифіката, тож повноцінний DSTU-сертифікат
    цією фабрикою не випускається. Опція ``dstu=True`` лише проганяє демонстраційний
    keygen через нативну UAPKI (feature-detection), щоб підтвердити, що шлях
    ``CREATE_KEY`` працює в середовищі; сертифікат усе одно ECDSA. Якщо UAPKI
    недоступна — прозорий fallback із warning, тестування продовжується.
    """
    if dstu:
        try:
            _dstu_keygen_demo()
            _log.info("DSTU keygen через UAPKI виконано (демонстрація); cert = ECDSA")
        except Exception as exc:  # noqa: BLE001
            _log.warning("DSTU keygen via UAPKI недоступний (%s) — fallback ECDSA", exc)
    return ec.generate_private_key(ec.SECP256R1())


def _dstu_keygen_demo() -> None:
    """Демонстраційний keygen ДСТУ-ключа через нативну libuapki.

    Feature-detection: піднімає ``UapkiLibraryNotFound``/``UapkiError``, якщо
    бібліотека не зібрана або INIT уже виконано в цьому процесі інакше (нативний
    singleton). Виклик лише підтверджує працездатність ``CREATE_KEY``; згенерований
    ключ/CSR не використовується (сертифікат ECDSA). Повноцінний DSTU-сертифікат
    потребує CA на основі UAPKI — окрема інтеграція поза цією фабрикою.
    """
    from .uapki import UapkiClient, UapkiLibraryNotFound

    with tempfile.TemporaryDirectory() as tmp:
        try:
            client = UapkiClient()
        except UapkiLibraryNotFound:
            raise
        client.init(tmp + "/certs", tmp + "/crls", offline=True)
        # CREATE-режим PKCS12-сховища + DSTU-ключ — повторно лише якщо singleton дозволяє.
        try:
            client.open_pkcs12(tmp + "/dstu.p12", "test", mode="CREATE")
            client.call(
                "CREATE_KEY",
                {
                    "mechanismId": DSTU_MECHANISM_OID,
                    "parameterId": DSTU_CURVE_M257PB_OID,
                    "label": "test-dstu-keygen",
                },
            )
            client.call("GET_CSR", {"signAlgo": DSTU_SIGN_ALGO_OID})
        finally:
            client.close()


def _build_leaf_subject(
    *, common_name: str, kind: str, organization: str, identifier: str
) -> x509.Name:
    attrs = [
        x509.NameAttribute(NameOID.COUNTRY_NAME, "UA"),
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
    ]
    if organization:
        attrs.append(x509.NameAttribute(NameOID.ORGANIZATION_NAME, organization))
    # identifier: для eSign — РНОКПП у serialNumber; для eSeal — NTRUA-ЄДРПОУ
    # в organizationIdentifier (2.5.4.97). Реальні UA-сертифікати також несуть
    # serialNumber=UA-ЄДРПОУ-NNNN, тож додаємо обидва для сумісності парсерів.
    if kind == "esign":
        attrs.append(x509.NameAttribute(NameOID.SERIAL_NUMBER, identifier))
    else:  # eseal
        attrs.append(x509.NameAttribute(OID_ORGANIZATION_IDENTIFIER, identifier))
        attrs.append(
            x509.NameAttribute(NameOID.SERIAL_NUMBER, f"UA-{identifier.split('-')[-1]}-0001")
        )
    return x509.Name(attrs)


# --- публічне API ---------------------------------------------------------

def generate_test_ca(
    common_name: str = "Тестовий КНЕДП Діловод", *, dstu: bool = False
) -> CaKey:
    """Створити тестовий self-signed CA (ECDSA P-256).

    DSTU-опція не впливає на CA (CA-ключ завжди ECDSA — cryptography не підписує
    DSTU), але приймається для одноманітності API.
    """
    del dstu  # CA завжди ECDSA
    key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name(
        [
            x509.NameAttribute(NameOID.COUNTRY_NAME, "UA"),
            x509.NameAttribute(NameOID.ORGANIZATION_NAME, common_name),
            x509.NameAttribute(NameOID.COMMON_NAME, common_name),
            x509.NameAttribute(OID_ORGANIZATION_IDENTIFIER, "NTRUA-00000000"),
        ]
    )
    now = _dt.datetime.now(_dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _dt.timedelta(minutes=1))
        .not_valid_after(now + _dt.timedelta(days=365 * 10))
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=1), critical=True
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
        )
        .sign(key, hashes.SHA256())
    )
    return CaKey(cert=cert, key=key)


def _issue_leaf(
    ca: CaKey,
    *,
    common_name: str,
    kind: str,
    organization: str,
    identifier: str,
    valid_days: int,
    dstu: bool,
) -> LeafKey:
    if kind not in ("esign", "eseal"):
        raise ValueError(f"невідомий тип сертифіката: {kind!r}")
    key = _generate_keypair(dstu=dstu)
    subject = _build_leaf_subject(
        common_name=common_name, kind=kind, organization=organization, identifier=identifier
    )
    qc_type_oid = OID_QC_TYPE_ESEAL if kind == "eseal" else OID_QC_TYPE_ESIGN
    now = _dt.datetime.now(_dt.timezone.utc)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca.cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _dt.timedelta(minutes=1))
        .not_valid_after(now + _dt.timedelta(days=valid_days))
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=False,
                content_commitment=True,  # nonRepudiation
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False
        )
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca.key.public_key()),
            critical=False,
        )
        .add_extension(_qc_statements_extension(qc_type_oid), critical=False)
        .sign(ca.key, hashes.SHA256())
    )
    return LeafKey(cert=cert, key=key, cert_type=kind)


def issue_esign_cert(
    ca: CaKey,
    subject_cn: str,
    rnopp: str,
    *,
    valid_days: int = 365,
    dstu: bool = False,
) -> LeafKey:
    """Випустити тестовий КЕП-сертифікат фізособи (eSign)."""
    return _issue_leaf(
        ca,
        common_name=subject_cn,
        kind="esign",
        organization="",
        identifier=rnopp,
        valid_days=valid_days,
        dstu=dstu,
    )


def issue_eseal_cert(
    ca: CaKey,
    org_name: str,
    edrpou: str,
    *,
    valid_days: int = 365,
    dstu: bool = False,
) -> LeafKey:
    """Випустити тестовий сертифікат печатки юрособи/ФОП (eSeal)."""
    identifier = f"NTRUA-{edrpou}"  # EEA-схема: NTR + ЄДРПОУ
    return _issue_leaf(
        ca,
        common_name=org_name,
        kind="eseal",
        organization=org_name,
        identifier=identifier,
        valid_days=valid_days,
        dstu=dstu,
    )


def to_pkcs12(cert: x509.Certificate, key: object, password: str, label: str) -> bytes:
    """Серiалізувати cert+key у PKCS#12 (сумісний з EUSign/openssl/UAPKI).

    password="" дає незашифрований контейнер (деякі тести). CA-сертифікат
    включається як friend-сертифікат, коли він є частиною ``cert``-ланцюга
    (викликач передає CA окремо через friend_certs, див. ``to_pkcs12_chain``).
    """
    return _pkcs12.serialize_key_and_certificates(
        name=label.encode("utf-8"),
        key=key,  # type: ignore[arg-type]
        cert=cert,
        cas=None,
        encryption_algorithm=serialization.BestAvailableEncryption(password.encode("utf-8"))
        if password
        else serialization.NoEncryption(),
    )


def to_pkcs12_chain(
    leaf: LeafKey, ca: CaKey, password: str, label: str
) -> bytes:
    """PKCS#12 leaf-сертифіката з включеним CA (ланцюг)."""
    return _pkcs12.serialize_key_and_certificates(
        name=label.encode("utf-8"),
        key=leaf.key,  # type: ignore[arg-type]
        cert=leaf.cert,
        cas=[ca.cert],
        encryption_algorithm=serialization.BestAvailableEncryption(password.encode("utf-8"))
        if password
        else serialization.NoEncryption(),
    )


def cert_to_der(cert: x509.Certificate) -> bytes:
    return cert.public_bytes(serialization.Encoding.DER)


def cert_to_pem(cert: x509.Certificate) -> bytes:
    return cert.public_bytes(serialization.Encoding.PEM)


def private_key_to_pem(key: object, password: str = "") -> bytes:
    enc = (
        serialization.BestAvailableEncryption(password.encode("utf-8"))
        if password
        else serialization.NoEncryption()
    )
    return key.private_bytes(  # type: ignore[union-attr]
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=enc,
    )


def write_bundle(
    out_dir: str | os.PathLike[str],
    *,
    password: str = "testpassword",
    ca_cn: str = "Тестовий КНЕДП Діловод",
    person_cn: str = "Тестовий Підписувач КЕП",
    person_rnopp: str = "1234512345",
    org_name: str = "ТОВ Тестова Юридична Особа",
    org_edrpou: str = "43213421",
    dstu: bool = False,
) -> dict[str, str]:
    """Згенерувати повний набір тестових сертифікатів у каталог ``out_dir``.

    Створює:
      ``ca.cer``, ``ca.p12``,
      ``person_esign.cer``, ``person_esign.p12``,
      ``org_eseal.cer``, ``org_eseal.p12``.

    Повертає словник {роль: шлях до p12}. Зручна точка входу для CLI та фікстур.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)

    ca = generate_test_ca(ca_cn, dstu=dstu)
    person = issue_esign_cert(ca, person_cn, person_rnopp, dstu=dstu)
    org = issue_eseal_cert(ca, org_name, org_edrpou, dstu=dstu)

    (out / "ca.cer").write_bytes(ca.cert_pem)
    (out / "ca.p12").write_bytes(to_pkcs12(ca.cert, ca.key, password, "test-ca"))

    (out / "person_esign.cer").write_bytes(person.cert_pem)
    (out / "person_esign.p12").write_bytes(
        to_pkcs12_chain(person, ca, password, "test-person-esign")
    )

    (out / "org_eseal.cer").write_bytes(org.cert_pem)
    (out / "org_eseal.p12").write_bytes(
        to_pkcs12_chain(org, ca, password, "test-org-eseal")
    )

    return {
        "ca": str(out / "ca.p12"),
        "esign": str(out / "person_esign.p12"),
        "eseal": str(out / "org_eseal.p12"),
    }


# --- утиліта: підписати довільні дані лист-ключем (для тестів підпису) ----

def sign_data_with_leaf(leaf: LeafKey, data: bytes, *, detached: bool = True) -> bytes:
    """Згенерувати CMS-підпис даних лист-ключем (для тестів cert-парсера/verify).

    Повертає DER-контейнер PKCS#7 з вбудованим сертифікатом підписувача, що його
    приймає ``cert_info_from_cms`` і ``verify_signature``. ``cryptography`` формує
    RFC 5652 CMS (не повний CAdES-X-Long, який робить EUSign/UAPKI), але сертифікат
    підписувача вбудовується — ``openssl pkcs7 -print_certs`` його витягне.

    ``detached`` зарезервовано на майбутнє; зараз формує attached (найпростіший
    шлях отримати cert у контейнері), що сумісний з існуючим парсером.
    """
    from cryptography.hazmat.primitives.serialization import pkcs7

    options = [pkcs7.PKCS7Options.DetachedSignature] if detached else []
    return (
        pkcs7.PKCS7SignatureBuilder()
        .set_data(data)
        .add_signer(leaf.cert, leaf.key, hashes.SHA256())  # type: ignore[arg-type]
        .sign(serialization.Encoding.DER, options)
    )
