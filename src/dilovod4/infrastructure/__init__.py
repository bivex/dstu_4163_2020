"""Інфраструктурний шар: адаптери, що реалізують доменні порти."""

from .config import AppConfig
from .document_mapper import MappingError, document_from_dict
from .docx_writer import DocxDocumentWriter
from .fonts import FontNotFoundError, FontPaths, resolve_times_new_roman
from .pdf_writer import PdfDocumentWriter
from .repository import InMemoryDocumentRepository
from .rule_set_provider import DefaultRuleSetProvider
from .uapki import (
    CertInfo,
    OcspStatus,
    SignResult,
    UapkiClient,
    UapkiError,
    UapkiLibraryNotFound,
    VerifyResult,
    check_cert_status_online,
    combine_signatures,
    sign_file_pkcs12,
    sign_file_auto,
    sign_file_with_remote_cert,
    verify_signature,
)
from .cmp import CmpError, CmpResponse, build_request, fetch_certificate
from .ca_registry import CaEndpoints, CaRegistryError, find_by_issuer_cn, list_providers
from .token_sign import (
    EuscpnmhClient,
    TokenError,
    TokenHostNotFound,
    TokenSignResult,
    sign_file_with_token,
)

__all__ = [
    "AppConfig",
    "MappingError",
    "document_from_dict",
    "DocxDocumentWriter",
    "PdfDocumentWriter",
    "FontPaths",
    "FontNotFoundError",
    "resolve_times_new_roman",
    "InMemoryDocumentRepository",
    "DefaultRuleSetProvider",
    "UapkiClient",
    "UapkiError",
    "UapkiLibraryNotFound",
    "SignResult",
    "CertInfo",
    "VerifyResult",
    "OcspStatus",
    "sign_file_pkcs12",
    "sign_file_auto",
    "sign_file_with_remote_cert",
    "verify_signature",
    "check_cert_status_online",
    "combine_signatures",
    "CmpError",
    "CmpResponse",
    "build_request",
    "fetch_certificate",
    "CaEndpoints",
    "CaRegistryError",
    "find_by_issuer_cn",
    "list_providers",
    "EuscpnmhClient",
    "TokenError",
    "TokenHostNotFound",
    "TokenSignResult",
    "sign_file_with_token",
]
