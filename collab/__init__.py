"""Shared infrastructure for the Collab command-line tools."""

from .github import GitHubClient, GitHubError, RequestIdentity, ResponseEnvelope

__all__ = ["GitHubClient", "GitHubError", "RequestIdentity", "ResponseEnvelope"]
