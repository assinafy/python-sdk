"""Public type aliases and the ``Logger`` protocol.

These mirror the documented enums at https://api.assinafy.com.br/v1/docs and
are kept here so consumers can import them directly: ``from assinafy import
DocumentStatus``.
"""

from __future__ import annotations

from typing import Any, Literal, Protocol, get_args

DocumentStatus = Literal[
    "uploading",
    "uploaded",
    "metadata_processing",
    "metadata_ready",
    "pending_signature",
    "expired",
    "certificating",
    "certificated",
    "rejected_by_signer",
    "rejected_by_user",
    "failed",
]

DocumentArtifactName = Literal["original", "certificated", "certificate-page", "pades", "bundle"]
DOCUMENT_ARTIFACT_NAMES = frozenset(get_args(DocumentArtifactName))

AssignmentMethod = Literal["virtual", "collect"]

WebhookEventType = Literal[
    "document_uploaded",
    "document_metadata_ready",
    "document_prepared",
    "assignment_created",
    "document_ready",
    "signature_requested",
    "signer_created",
    "signer_email_verified",
    "signer_whatsapp_verified",
    "signer_data_confirmed",
    "signer_viewed_document",
    "signer_signed_document",
    "signer_rejected_document",
    "user_rejected_document",
    "document_processing_failed",
    "template_created",
    "template_processed",
    "template_processing_failed",
]

SignerReference = str | dict[str, Any]

NotificationPreferenceCode = Literal[
    "DocumentCompleted",
    "SignerDeclined",
    "DocumentCancelled",
    "DocumentAboutToExpire",
    "DocumentExpired",
    "DocumentExpirationReset",
    "DocumentProcessingFailed",
    "TemplateProcessingFailed",
    "SignerWhatsappFailed",
]
NOTIFICATION_PREFERENCE_CODES = frozenset(get_args(NotificationPreferenceCode))


class Logger(Protocol):
    """Structural type for ``logger`` on :class:`~assinafy.client.AssinafyClient`.

    Any object exposing ``debug``/``info``/``warning``/``error`` methods that
    accept ``(message, context)`` qualifies. The stdlib ``logging.Logger`` is
    *not* a drop-in match because its methods don't take a dict context; wrap
    it with a thin adapter if you want to forward through.
    """

    def debug(self, message: str, context: dict[str, Any] | None = None) -> None: ...
    def info(self, message: str, context: dict[str, Any] | None = None) -> None: ...
    def warning(self, message: str, context: dict[str, Any] | None = None) -> None: ...
    def error(self, message: str, context: dict[str, Any] | None = None) -> None: ...
