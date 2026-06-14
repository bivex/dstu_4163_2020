"""Доменна модель ДСТУ 4163:2020."""

from .approval import Agreement, ApprovalGrant, Visa
from .content import DocumentContent
from .document import Document
from .enums import (
    BlankType,
    CertificateStatus,
    DateStyle,
    PaperFormat,
    PrintSide,
    RequisiteAlignment,
    StorageTerm,
)
from .signature import ElectronicSignatureMark
from .qr_payload import (
    QR_PAYLOAD_PREFIX,
    QR_PAYLOAD_VERSION,
    build_signature_qr_payload,
)
from .value_objects import (
    BlankSpec,
    DateSpec,
    FormattingSpec,
    Geometry,
    LeftIndents,
    LineSpacing,
    PageMargins,
    PageNumbering,
    RequisiteSet,
    SymbolDimensions,
    Typography,
)

__all__ = [
    "Document",
    "DocumentContent",
    "Agreement",
    "ApprovalGrant",
    "Visa",
    "ElectronicSignatureMark",
    "build_signature_qr_payload",
    "QR_PAYLOAD_VERSION",
    "QR_PAYLOAD_PREFIX",
    "BlankType",
    "CertificateStatus",
    "DateStyle",
    "PaperFormat",
    "PrintSide",
    "RequisiteAlignment",
    "StorageTerm",
    "BlankSpec",
    "DateSpec",
    "FormattingSpec",
    "Geometry",
    "LeftIndents",
    "LineSpacing",
    "PageMargins",
    "PageNumbering",
    "RequisiteSet",
    "SymbolDimensions",
    "Typography",
]
