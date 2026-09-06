# Security mail templates and SMTP transport adapted from open-city-planner 2238e18.
import asyncio
import logging
import smtplib
from dataclasses import dataclass
from email.headerregistry import Address
from email.message import EmailMessage
from typing import Literal

from jinja2 import Environment, StrictUndefined
from sqlalchemy.ext.asyncio import AsyncSession

from web.backend.app.auth.config import get_settings
from web.backend.app.auth.models.user import User

logger = logging.getLogger(__name__)
TemplateCategory = Literal["Sicherheit", "Konto", "Kontakt", "Kommunikation / System"]


@dataclass(frozen=True)
class EmailTemplateDefinition:
    key: str
    name: str
    description: str
    category: TemplateCategory
    default_subject: str
    default_html: str
    default_text: str
    allowed_variables: frozenset[str]
    required_variables: frozenset[str] = frozenset()
    is_security_sensitive: bool = False
    is_active: bool = True


@dataclass(frozen=True)
class RenderedEmail:
    subject: str
    html: str
    text: str


EMAIL_TEMPLATE_REGISTRY: dict[str, EmailTemplateDefinition] = {
    "verify_email": EmailTemplateDefinition(
        "verify_email",
        "E-Mail-Adresse bestätigen",
        "Bestätigung einer neu hinterlegten E-Mail-Adresse.",
        "Sicherheit",
        "E-Mail-Adresse bestätigen - OK Lab Flensburg",
        (
            "<p>Hallo {{ name }},</p><p>Vielen Dank für Ihre Registrierun"
            "g. Bitte bestätigen Sie Ihre E-Mail-Adresse:</p><p><a class="
            '"email-button" href="{{ verification_url }}">E-Mail-Adresse '
            "bestätigen</a></p><p>Der Link ist nur begrenzt gültig. Wenn "
            "Sie kein Konto erstellt haben, können Sie diese Nachricht ig"
            "norieren.</p>"
        ),
        (
            "Hallo {{ name }},\n\nvielen Dank für Ihre Registrierung.\n\nBitt"
            "e bestätigen Sie Ihre E-Mail-Adresse:\n{{ verification_url }}"
            "\n\nDer Link ist nur begrenzt gültig. Wenn Sie kein Konto erst"
            "ellt haben, können Sie diese Nachricht ignorieren."
        ),
        frozenset({"name", "verification_url"}),
        frozenset({"verification_url"}),
        True,
    ),
    "password_reset": EmailTemplateDefinition(
        "password_reset",
        "Passwort zurücksetzen",
        "Sicherer Link zum Zurücksetzen eines Passworts.",
        "Sicherheit",
        "Passwort zurücksetzen - OK Lab Flensburg",
        (
            "<p>Hallo {{ name }},</p><p>Für Ihr Package Hub-Konto wurde d"
            'as Zurücksetzen des Passworts angefordert.</p><p><a class="e'
            'mail-button" href="{{ reset_url }}">Passwort zurücksetzen</a'
            "></p><p>Der Link ist {{ expires_minutes }} Minuten gültig. W"
            "enn Sie die Anfrage nicht gestellt haben, ist keine Aktion e"
            "rforderlich.</p>"
        ),
        (
            "Hallo {{ name }},\n\nfür Ihr Package Hub-Konto wurde das Zurüc"
            "ksetzen des Passworts angefordert.\n\nPasswort zurücksetzen:\n{"
            "{ reset_url }}\n\nDer Link ist {{ expires_minutes }} Minuten g"
            "ültig. Wenn Sie die Anfrage nicht gestellt haben, ist keine "
            "Aktion erforderlich."
        ),
        frozenset({"name", "reset_url", "expires_minutes"}),
        frozenset({"reset_url"}),
        True,
    ),
    "password_changed": EmailTemplateDefinition(
        "password_changed",
        "Passwort geändert",
        "Sicherheitshinweis nach einer Passwortänderung.",
        "Sicherheit",
        "Passwort geändert - OK Lab Flensburg",
        (
            "<p>Hallo {{ name }},</p><p>Ihr Passwort wurde geändert.</p><"
            "p>Wenn Sie diese Änderung nicht ausgelöst haben, kontaktiere"
            "n Sie bitte das OK Lab Flensburg.</p>"
        ),
        (
            "Hallo {{ name }},\n\nIhr Passwort wurde geändert.\n\nWenn Sie di"
            "ese Änderung nicht ausgelöst haben, kontaktieren Sie bitte d"
            "as OK Lab Flensburg."
        ),
        frozenset({"name"}),
        is_security_sensitive=True,
    ),
    "mfa_security": EmailTemplateDefinition(
        "mfa_security",
        "MFA- und Passkey-Sicherheit",
        "Hinweise zu MFA, Wiederherstellungscodes und Passkeys.",
        "Sicherheit",
        "{{ security_event_title }} - OK Lab Flensburg",
        (
            "<p>Hallo {{ name }},</p><h1>{{ security_event_title }}</h1><"
            "p>{{ security_event_message }}</p><p>Falls Sie diese Änderun"
            "g nicht selbst vorgenommen haben, ändern Sie bitte umgehend "
            "Ihr Passwort und wenden Sie sich an den Support.</p>"
        ),
        (
            "Hallo {{ name }},\n\n{{ security_event_title }}\n\n{{ security_e"
            "vent_message }}\n\nFalls Sie diese Änderung nicht selbst vorge"
            "nommen haben, ändern Sie bitte umgehend Ihr Passwort und wen"
            "den Sie sich an den Support."
        ),
        frozenset({"name", "security_event_title", "security_event_message"}),
        is_security_sensitive=True,
    ),
}


def send_email(
    to_email: str,
    subject: str,
    html: str,
    text: str,
    *,
    to_name: str | None = None,
    reply_to: str | None = None,
    headers: dict[str, str] | None = None,
) -> None:
    settings = get_settings()
    if settings.email_backend == "console":
        logger.info("Console email prepared subject=%s body_bytes=%d", subject, len(text.encode()))
        return
    if settings.email_backend != "smtp":
        raise RuntimeError("Unsupported EMAIL_BACKEND")
    if not settings.smtp_host:
        raise RuntimeError("SMTP_HOST must be configured for smtp email backend")
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = Address(settings.smtp_from_name, addr_spec=settings.smtp_from_email)
    message["To"] = Address(to_name or "", addr_spec=to_email)
    if reply_to:
        message["Reply-To"] = Address(addr_spec=reply_to)
    for name, value in (headers or {}).items():
        message[name] = value
    message.set_content(text)
    message.add_alternative(html, subtype="html")
    with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=15) as smtp:
        if settings.smtp_use_tls:
            smtp.starttls()
        if settings.smtp_username:
            smtp.login(settings.smtp_username, settings.smtp_password or "")
        smtp.send_message(message)


async def send_rendered_email(
    to_email: str,
    rendered: RenderedEmail,
    *,
    to_name: str | None = None,
    reply_to: str | None = None,
    headers: dict[str, str] | None = None,
) -> None:
    await asyncio.to_thread(
        send_email,
        to_email,
        rendered.subject,
        rendered.html,
        rendered.text,
        to_name=to_name,
        reply_to=reply_to,
        headers=headers,
    )


def display_name(user: User) -> str:
    return (
        user.display_name
        or " ".join(part for part in [user.first_name, user.last_name] if part).strip()
        or user.email
    )


async def send_verification_email(session: AsyncSession, user: User, token: str) -> None:
    link = f"{get_settings().app_base_url.rstrip('/')}/email-bestaetigen?token={token}"
    rendered = await render_email_template(
        session, "verify_email", {"name": display_name(user), "verification_url": link}
    )
    await send_rendered_email(user.email, rendered)


async def send_password_reset_email(session: AsyncSession, user: User, token: str) -> None:
    settings = get_settings()
    link = f"{settings.app_base_url.rstrip('/')}/passwort-zuruecksetzen?token={token}"
    rendered = await render_email_template(
        session,
        "password_reset",
        {
            "name": display_name(user),
            "reset_url": link,
            "expires_minutes": settings.password_reset_expire_minutes,
        },
    )
    await send_rendered_email(user.email, rendered)


async def send_password_changed_email(session: AsyncSession, user: User) -> None:
    rendered = await render_email_template(
        session, "password_changed", {"name": display_name(user)}
    )
    await send_rendered_email(user.email, rendered)


_MFA_EVENTS = {
    "enabled": (
        "Zwei-Faktor-Authentifizierung aktiviert",
        "Die Zwei-Faktor-Authentifizierung Ihres Kontos wurde aktiviert.",
    ),
    "disabled": (
        "Zwei-Faktor-Authentifizierung deaktiviert",
        "Die Zwei-Faktor-Authentifizierung Ihres Kontos wurde deaktiviert.",
    ),
    "recovery_regenerated": (
        "Neue Wiederherstellungscodes erzeugt",
        (
            "Für Ihr Konto wurden neue Wiederherstellungscodes erzeugt. A"
            "lle bisherigen Codes sind ungültig."
        ),
    ),
    "recovery_used": (
        "Wiederherstellungscode verwendet",
        "Für die Anmeldung bei Ihrem Konto wurde ein Wiederherstellungscode verwendet.",
    ),
    "passkey_added": (
        "Passkey hinzugefügt",
        (
            "Für Ihr Konto wurde ein neuer Passkey hinzugefügt. Falls Sie"
            " diese Änderung nicht vorgenommen haben, prüfen Sie bitte um"
            "gehend Ihre Kontosicherheit."
        ),
    ),
    "passkey_removed": (
        "Passkey entfernt",
        (
            "Ein Passkey wurde aus Ihrem Konto entfernt. Falls Sie diese "
            "Änderung nicht vorgenommen haben, prüfen Sie bitte umgehend "
            "Ihre Kontosicherheit."
        ),
    ),
    "passkeys_removed": (
        "Alle Passkeys entfernt",
        (
            "Der letzte Passkey wurde aus Ihrem Konto entfernt. Falls Sie"
            " diese Änderung nicht vorgenommen haben, prüfen Sie bitte um"
            "gehend Ihre Kontosicherheit."
        ),
    ),
}


async def send_mfa_security_email(session: AsyncSession, user: User, event: str) -> None:
    title, message = _MFA_EVENTS[event]
    rendered = await render_email_template(
        session,
        "mfa_security",
        {
            "name": display_name(user),
            "security_event_title": title,
            "security_event_message": message,
        },
    )
    await send_rendered_email(user.email, rendered)


async def render_email_template(session, key, context):
    # Templates are repository-owned; no database-managed HTML or executable helpers.
    definition = EMAIL_TEMPLATE_REGISTRY[key]
    html_env = Environment(autoescape=True, undefined=StrictUndefined)
    text_env = Environment(autoescape=False, undefined=StrictUndefined)
    return RenderedEmail(
        text_env.from_string(definition.default_subject).render(**context),
        html_env.from_string(definition.default_html).render(**context),
        text_env.from_string(definition.default_text).render(**context),
    )
