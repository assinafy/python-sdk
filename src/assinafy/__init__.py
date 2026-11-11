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
from .resources.contracts import ContractResource
from .resources.documents import DocumentResource
from .resources.embed import EmbedResource
from .resources.envelopes import EnvelopeResource
from .resources.fields import FieldResource
from .resources.oauth import OAuthResource
from .resources.signer_documents import SignerDocumentResource
from .resources.signers import SignerResource
from .resources.tags import TagResource
from .resources.templates import TemplateResource
from .resources.users import UserResource
from .resources.webhooks import WebhookResource
from .support.webhook_verifier import WebhookVerifier
from .types import (
    AssignmentMethod,
    ContractRelationType,
    ContractStatus,
    DocumentArtifactName,
    DocumentStatus,
    Logger,
    NotificationMethod,
    NotificationPolicyCode,
    NotificationPreferenceCode,
    OAuthGrantType,
    OAuthScope,
    OAuthTokenTypeHint,
    PushPreferenceCode,
    SignerReference,
    VerificationMethod,
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
    "ContractRelationType",
    "ContractResource",
    "ContractStatus",
    "DocumentArtifactName",
    "DocumentResource",
    "DocumentStatus",
    "EmbedResource",
    "EnvelopeResource",
    "FieldResource",
    "Logger",
    "NetworkError",
    "NotificationMethod",
    "NotificationPolicyCode",
    "NotificationPreferenceCode",
    "OAuthGrantType",
    "OAuthResource",
    "OAuthScope",
    "OAuthTokenTypeHint",
    "PushPreferenceCode",
    "SignerDocumentResource",
    "SignerReference",
    "SignerResource",
    "TagResource",
    "TemplateResource",
    "UserResource",
    "ValidationError",
    "VerificationMethod",
    "WebhookEventType",
    "WebhookResource",
    "WebhookVerifier",
    "__version__",
]
