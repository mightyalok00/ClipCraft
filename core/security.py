"""Security utilities: input sanitization, path traversal prevention, SSRF guards, and secret masking."""
from __future__ import annotations

import ipaddress
import re
import shutil
from pathlib import Path
from urllib.parse import urlparse

# Allowed video extensions for local ingestion
SAFE_VIDEO_EXTENSIONS = {".mp4", ".mkv", ".mov", ".webm", ".avi", ".flv"}

# Dangerous schemes blocked outright
BLOCKED_SCHEMES = {"file", "gopher", "ftp", "data", "javascript", "vbscript", "ldap", "dict"}

# Disallowed hostnames for SSRF protection
BLOCKED_HOSTNAMES = {"localhost", "127.0.0.1", "0.0.0.0", "metadata.google.internal"}  # nosec B104


def is_private_ip(hostname: str) -> bool:
    """Check if a hostname resolves to a private, loopback, or cloud-metadata IP."""
    try:
        ip = ipaddress.ip_address(hostname)
        return (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_reserved
            or str(ip) == "169.254.169.254"
        )
    except ValueError:
        return False


def validate_source(source: str, allow_local: bool = True) -> tuple[bool, str]:
    """Validate a video source (URL or local path) against SSRF and injection attacks.

    Returns:
        (is_valid, error_message)
    """
    clean_src = source.strip().strip("'\"")
    if not clean_src:
        return False, "Source cannot be empty."

    # Check for URL
    if clean_src.startswith(("http://", "https://")):
        try:
            parsed = urlparse(clean_src)
        except Exception as e:
            return False, f"Malformed URL: {e}"

        if parsed.scheme.lower() in BLOCKED_SCHEMES:
            return False, f"URL scheme '{parsed.scheme}' is forbidden."

        hostname = (parsed.hostname or "").lower()
        if not hostname:
            return False, "URL hostname is missing."

        if hostname in BLOCKED_HOSTNAMES or is_private_ip(hostname):
            return False, f"Access to internal/private host '{hostname}' is blocked."

        return True, ""

    # Check for disallowed schemes (e.g. file:///etc/passwd)
    if ":" in clean_src and not (len(clean_src) > 1 and clean_src[1] == ":"):  # Allow Windows drive letters like C:\
        scheme = clean_src.split(":", 1)[0].lower()
        if scheme in BLOCKED_SCHEMES:
            return False, f"Scheme '{scheme}' is forbidden."

    # Validate local path
    if allow_local:
        local_path = Path(clean_src)
        if not local_path.exists():
            return False, f"Local media file not found: {clean_src}"
        if not local_path.is_file():
            return False, "Target local path is not a file."
        if local_path.suffix.lower() not in SAFE_VIDEO_EXTENSIONS:
            allowed = ", ".join(SAFE_VIDEO_EXTENSIONS)
            return False, f"Unsupported video extension '{local_path.suffix}'. Allowed: {allowed}"
        return True, ""

    return False, "Only HTTP/HTTPS URLs are allowed in web mode."


def sanitize_filename(filename: str) -> str:
    """Strip directory traversal sequences and invalid characters from filename."""
    # If the string contains path separators followed by valid filename, extract the last component
    parts = [p for p in re.split(r"[/\\]+", filename.strip()) if p and p != ".."]
    base = parts[-1] if parts else filename.strip()
    # Strip any characters that are not alphanumeric, dot, underscore, or hyphen
    cleaned = re.sub(r"[^a-zA-Z0-9._\-]", "_", base)
    return cleaned or "unnamed_file"


def safe_resolve_path(base_dir: Path, *sub_paths: str) -> Path:
    """Resolve sub_paths strictly within base_dir. Raises PermissionError on directory traversal."""
    resolved_base = base_dir.resolve()
    for p in sub_paths:
        if ".." in Path(p).parts or p.startswith(("/", "\\")):
            raise PermissionError(f"Directory traversal sequence detected in '{p}'")

    target = (resolved_base / Path(*sub_paths)).resolve()
    try:
        target.relative_to(resolved_base)
    except ValueError as e:
        raise PermissionError(f"Path traversal detected: {target} is outside {resolved_base}") from e

    return target


def mask_secret(secret: str | None) -> str:
    """Mask sensitive API keys for safe display in logs and web interfaces."""
    if not secret:
        return ""
    s = secret.strip()
    if len(s) <= 8:
        return "********"
    return f"{s[:4]}...{s[-4:]}"


def resolve_executable(name: str) -> str:
    """Resolve the absolute executable path using shutil.which to prevent path hijacking."""
    found = shutil.which(name)
    return str(Path(found).resolve()) if found else name
