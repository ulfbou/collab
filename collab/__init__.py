"""Shared infrastructure for the Collab command-line tools."""

from .github import GitHubClient, GitHubError, RequestIdentity, ResponseEnvelope

__all__ = ["GitHubClient", "GitHubError", "RequestIdentity", "ResponseEnvelope"]

from .development_intent import (
    AUTHORITY_SET_SCHEMA,
    INTENT_SCHEMA,
    Diagnostic as IntentDiagnostic,
    ResolutionResult,
    derive_issue_intent,
    derive_operational_intent,
    resolve_authority_set,
)
