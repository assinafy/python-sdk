"""Assinafy Python SDK.

Synchronous client for the Assinafy digital-signature API
(https://api.assinafy.com.br/v1/docs).
"""

from .client import AssinafyClient
from .errors import ApiError, AssinafyError, NetworkError, ValidationError
from .resources.assignments import AssignmentResource
from .resources.authentication import AuthenticationResource
from .resources.documents import DocumentResource
from .resources.fields import FieldResource
from .resources.signer_documents import SignerDocumentResource
from .resources.signers import SignerResource
from .resources.tags import TagResource
from .resources.templates import TemplateResource
from .resources.webhooks import WebhookResource
from .support.webhook_verifier import WebhookVerifier
from .types import (
    AssignmentMethod,
    DocumentArtifactName,
    DocumentStatus,
    Logger,
    SignerReference,
    WebhookEventType,
)

__version__ = "1.3.0"

__all__ = [
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
    "SignerDocumentResource",
    "SignerReference",
    "SignerResource",
    "TagResource",
    "TemplateResource",
    "ValidationError",
    "WebhookEventType",
    "WebhookResource",
    "WebhookVerifier",
    "__version__",
]
