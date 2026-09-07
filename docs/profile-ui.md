# Package Hub profile layout

The `/profil` page follows the reading-width, stacked-card structure of the
[Open City Planner profile](https://github.com/oklabflensburg/open-city-planner/blob/main/frontend/app/pages/profil/index.vue)
and its separate
[danger zone](https://github.com/oklabflensburg/open-city-planner/blob/main/frontend/app/components/profile/AccountDangerZone.vue),
using the Package Hub's existing colours, typography, buttons and CSS tokens.

The page orders profile image, linked accounts and personal information before
password, MFA, passkeys and sessions. Account deletion is the final rose-coloured
section. Password changes and MFA management use disclosures; passkey naming and
deletion confirmation appear only after selecting the corresponding action.

Package Hub differences are intentional:

- GitHub and Google only. There is no Mastodon integration.
- Existing avatars are displayed with a safe HTTPS URL and initials fallback.
  No upload button, storage service or migration is introduced.
- `has_local_password` is a derived, read-only boolean; the hash is never exposed.
  OAuth-only accounts can set up a password through the existing reset flow.
- Provider avatars are added to the existing authenticated metadata response;
  profile dates and account avatars were already available in the Auth API.
- The editable profile remains the display name. No new personal-data fields.
- Sessions retain the existing all-devices logout. No device details are invented.
- Account deletion requires `LÖSCHEN` and, where applicable, the local password.
  No account-deactivation action is added.
- The existing mutation, CSRF, recent-auth, WebAuthn, cookie and caching contracts
  remain authoritative. Sensitive MFA material is still client-only.

## Visual checks

Screenshots use the locally built application with a real disposable PostgreSQL
account. GitHub metadata and the avatar are synthetic browser fixtures, not a real
linked external account. They contain no authentication credentials.

- [Desktop, 1440 px](screenshots/profile-desktop.png)
- [Tablet, 768 px](screenshots/profile-tablet.png)
- [Mobile, 390 px](screenshots/profile-mobile.png)

The profile E2E verifies vertical card order and absence of horizontal overflow at
all three widths, plus SSR `no-store`, `noindex, nofollow` and cookie-value absence.
To regenerate screenshots during the existing local Auth E2E runner, set
`PROFILE_SCREENSHOT_DIR` to an absolute output directory. Without it, screenshots
are written to the ignored frontend `test-results` directory.
