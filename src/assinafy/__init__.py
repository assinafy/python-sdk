"""Assinafy Python SDK.

Synchronous client for the Assinafy digital-signature API
(https://api.assinafy.com.br/v1/docs).
"""

from __future__ import annotations

from ._version import __version__
from .client import AssinafyClient
from .errors import ApiError, AssinafyError, NetworkError, ValidationError
from .resources.accounts import AccountResource
from .resources.assignments import AssignmentResource
from .resources.authentication import AuthenticationResource
from .resources.documents import DocumentResource
from .resources.fields import FieldResource
from .resources.signer_documents import SignerDocumentResource
from .resources.signers import SignerResource
from .resources.tags import TagResource
from .resources.templates import TemplateResource
from .resources.users import UserResource
from .resources.webhooks import WebhookResource
from .support.webhook_verifier import WebhookVerifier
from .types import (
    AssignmentMethod,
    DocumentArtifactName,
    DocumentStatus,
    Logger,
    NotificationPreferenceCode,
    SignerReference,
    WebhookEventType,
)

__all__ = [
    "AccountResource",
    "ApiError",
    "AssignmentMethod",
    "AssignmentResource",
    "AssinafyClient",
    "AssinafyError",
    "AuthenticationResource",
    "DocumentArtifactName",
    "DocumentResource",
    "DocumentStatus",
    "FieldResource",
    "Logger",
    "NetworkError",
    "NotificationPreferenceCode",
    "SignerDocumentResource",
    "SignerReference",
    "SignerResource",
    "TagResource",
    "TemplateResource",
    "ValidationError",
    "UserResource",
    "WebhookEventType",
    "WebhookResource",
    "WebhookVerifier",
    "__version__",
]
