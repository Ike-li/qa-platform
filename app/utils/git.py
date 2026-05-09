"""Shared git utilities."""

from urllib.parse import urlparse, urlunparse


def build_clone_url(git_url: str, credential: str | None) -> str:
    """Embed *credential* into *git_url* for HTTPS authentication.

    Returns the original URL when *credential* is ``None`` or the URL is not
    HTTPS.
    """
    if not credential or not git_url.startswith("https://"):
        return git_url

    parsed = urlparse(git_url)
    netloc = f"{credential}@{parsed.hostname}"
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return urlunparse(parsed._replace(netloc=netloc))
