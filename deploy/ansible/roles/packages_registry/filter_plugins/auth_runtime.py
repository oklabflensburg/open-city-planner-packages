"""Explicit secret contract shared by the GitHub builder and Ansible.

packages_auth_* deliberately bypasses the public packages_registry_* settings
forwarder. Never add secret variables to that public namespace.
"""

FIELDS = (
    "database_url",
    "secret",
    "oauth_state_secret",
    "mfa_recovery_pepper",
    "mfa_encryption_key",
    "redis_url",
    "smtp_host",
    "smtp_username",
    "smtp_password",
    "smtp_from_email",
    "github_client_id",
    "github_client_secret",
    "google_client_id",
    "google_client_secret",
)
REQUIRED = {
    "database_url",
    "secret",
    "oauth_state_secret",
    "mfa_recovery_pepper",
    "mfa_encryption_key",
    "redis_url",
    "smtp_host",
    "smtp_from_email",
}


def auth_extra_vars(variables, enabled):
    """Select only supported names; validate transport, leaving security to preflight."""
    if not enabled:
        return {}
    result = {}
    for field in FIELDS:
        name = f"packages_auth_{field}"
        value = variables.get(name, "")
        if not isinstance(value, str) or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError(f"{name} must be a single-line string without control characters")
        if field in REQUIRED and not value.strip():
            raise ValueError(f"Missing required auth value: {name}")
        result[name] = value
    for provider in ("github", "google"):
        client_id = result[f"packages_auth_{provider}_client_id"]
        client_secret = result[f"packages_auth_{provider}_client_secret"]
        if bool(client_id) != bool(client_secret) or (
            client_id and (not client_id.strip() or not client_secret.strip())
        ):
            raise ValueError(f"Configure both {provider} client fields or neither")
    return result


def environment_quote(value):
    """systemd EnvironmentFile double quotes; no shell or variable expansion."""
    if not isinstance(value, str) or any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("EnvironmentFile values must be single-line strings")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


class FilterModule:
    def filters(self):
        return {
            "packages_auth_extra_vars": auth_extra_vars,
            "packages_auth_environment_quote": environment_quote,
        }
