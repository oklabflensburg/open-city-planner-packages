# Issue #50: Package Hub – Umsetzungs- und Prüfbericht

## Stand

API-Migration, Layout, Deployment-Konfiguration und Tests sind umgesetzt.
Der Footer ist gemäß Freigabe vom 6. September 2026 vollständig: Bluesky, LinkedIn
und RSS sind sichtbare, nicht interaktive SVG-Symbole in nicht fokussierbaren
`span`-Elementen mit `aria-disabled="true"`. Es gibt keine Dummy-Links, erfundenen
URLs oder Click-Handler; die Symbole behalten die Navy-Farbe der Vorlage.
Es wurde kein Deploy, keine Promotion und keine Änderung an Production-Daten ausgeführt.
Offene Fragen: keine. Der Abschlusscommit wird in der Abschlussmeldung angegeben.

## Änderungen

- Weißer kompakter Header mit Logo-Nachzeichnung, Suche und freigegebenen
  sichtbaren deaktivierten Bedienelementen; dunkler GIS-Hero mit fünf SVG-Layern.
- Breadcrumb und drei Detailspalten mit dynamischer Modulnavigation,
  sieben Tastatur-bedienbaren Tabs, Schnellstart und rechten Informationskarten.
- Stable-Pointer und zugehörige unveränderliche Versionsressource; Digest-Abgleich
  vor Anzeige eines Downloads. Weitere Channels nur bei vorhandenen API-Pointern.
- Echte Lizenz, Kompatibilität, Veröffentlichungsdatum und Provenance. Fehlende
  Downloads, Stars und Aktualisierungsdaten bleiben „Nicht verfügbar“.
- Reproduzierbare CLI-Installation mit `install-registry`, Version und SHA-256.
- Vollständige paginierte v2-Suche/Publisher-Daten und API-basierte Kennzahlen.
- SSR/SEO, Canonical/OpenGraph, tatsächliche HTTP-404/503, Clipboard-Fehlerzustände,
  sichtbarer Tastaturfokus und Fokusbegrenzung in der Suchpalette.
- Unabhängiger Ansible-v2-Schalter (Rollen-Default false; Production-Override true),
  normalisierte Booleans und Entfernung deaktivierter Flags aus der Prozessumgebung.
- Regulärer Deploy installiert das gelockte `registry-db`-Extra und prüft die
  Promotion-CLI direkt in der erzeugten `.venv`. Keine editable Installation.
- Gebaute SSR-Integrationstests laufen zusätzlich in CI und Deployment.

## API-Migration

| Bisher | Jetzt |
| --- | --- |
| `/api/v1/packages` | `/api/v1/modules` |
| `/api/v1/packages/{id}` | `/api/v1/modules/{id}` |
| Eingebettete Legacy-Versionsliste | Paginierte `/api/v1/modules/{id}/versions` |
| Legacy-Versionsdetail | `/api/v1/modules/{id}/versions/{version}` |
| `latest_version` / `latest_channel` | Explizit `channels.stable.version` / `.sha256` |
| Array historischer Channel-Labels | Aktuelle Channel-Pointer; separater v2-Channel-Client vorhanden |
| Legacy-Suche und Publisher-DTOs | Gemeinsame Endpunkte mit zentralem `Accept: application/vnd.ocp.registry.v2+json` |
| Legacy `requires` | Versions-`compatibility` und `dependencies` |
| Alte Provenance-Projektion | Echte Versions-`source`, `provenance`, `artifact`, `published_at` |

Die UI importiert keine Registry-JSON-Dateien. Test-Fixtures liegen ausschließlich
unter `web/frontend/tests` und werden nicht vom Anwendungscode importiert.

## Promotion ohne Frontend-Rebuild

Jede neue SSR-Anfrage liest aktuelle API-Daten. Es gibt keine vorgerenderten
Registry-Seiten, keine ISR/SWR-Regel und keinen serverseitig behaltenen Registry-
Snapshot. HTTP-Antworten und Fetches verwenden Cache-Revalidierung. Nach einem
DB-Commit liefert die bestehende API neue Pointer; dieselbe laufende Nuxt-Build-
Instanz zeigt sie beim nächsten Abruf an. Ein SSR-Test ändert den Fixture-API-Pointer
von 0.4.0 auf 0.5.0 und prüft diese Darstellung ohne Neustart/Neubuild.
Die vorhandenen PostgreSQL-Tests prüfen echte Transaktionen und Pointer-/ETag-Wechsel.
Ein bereits geöffnetes Browserfenster benötigt einen erneuten Abruf; Live-Push
oder ein Polling-Dienst wurden nicht hinzugefügt.

## Prüfungen

Die finale Suite wurde nach Fertigstellung des Footers am 6. September 2026
erneut ausgeführt. Die neuen Footer-Tests prüfen fehlende Links, fehlende
Fokusziele, Accessible Names und `aria-disabled`.

| Prüfung | Ergebnis |
| --- | --- |
| Nuxt TypeScript-Typecheck | bestanden |
| Nuxt Production-Build einschließlich Typecheck | bestanden |
| Vitest | 38 bestanden |
| Gebautes SSR: Metadaten, v2-Negotiation, Pointer-Wechsel, 404, 503 | 5 bestanden |
| Registry-/Backend-/Ansible-Pytests | 305 bestanden |
| PostgreSQL 18.6 in eigener lokaler Testinstanz | 173 bestanden, 4 übersprungen |
| Neue unabhängige `.venv`: gefrorener Sync, SQLAlchemy/psycopg/Alembic-Imports, Promotion-CLI `--help` | bestanden |
| Ruff | bestanden |
| Ansible Deploy-Syntaxcheck | bestanden |
| Legacy-Suche im Frontend nach den drei vorgegebenen Mustern | keine Treffer |
| `git diff --check` | bestanden |
| Browserprüfung 1312, 1024, 768, 375 Pixel | kein horizontaler Seitenüberlauf; keine Hydration-/Laufzeitfehler |

Die vier übersprungenen DB-Tests benötigen einen externen Host-Verifier-Checkout
mit exakt dem projektspezifischen Pin samt dessen Laufzeitumgebung. Dieser wurde
nicht verändert oder neu provisioniert. Eine vorhandene Starlette/httpx-
Deprecation-Warnung und Nuxt-Test-Instrumentierungswarnungen sind keine Testfehler.
Die erste lokale DB-Testinitialisierung hatte SQL_ASCII statt UTF-8; nach Neuanlage
der isolierten UTF-8-Testdatenbank war die vollständige DB-Suite erfolgreich.

## Visuelle Prüfung

[Desktop](screenshots/package-hub/desktop.png) ·
[Mobile](screenshots/package-hub/mobile.png) ·
[Tablet](screenshots/package-hub/tablet.png)

Bei 1312 Pixeln Breite: Header 62 Pixel, Hero 308 Pixel, Breadcrumb 44 Pixel;
linke Navigation 245 Pixel, mittlere Spalte 676 Pixel, rechte Spalte 241 Pixel;
Spaltenabstände 27 Pixel. Reihenfolge und Position der Hauptregionen entsprechen
der Vorlage. Header, Hero-Aufteilung, Headline, Buttons, Kennzahlen, Breadcrumb,
Navigation, Tabs, Versions-/Repository-/Lizenzkarten, Codeblöcke und Footer wurden
im Browser gegenüber der Vorlage geprüft.

Bewusste, in der Aufgabenbeschreibung vorgesehene bzw. freigegebene Unterschiede:

- Schematische SVG-Nachzeichnung der GIS-Layer und des Logos statt identischer
  Rastergrafik; keine neue Bildquelle oder externe Schriftabhängigkeit.
- Echte Registry-Daten: drei Module, sieben Versionen, ein Publisher;
  echte englische Modulbeschreibung, AGPL-3.0-only, echte Host-/SDK-Anforderungen
  und Veröffentlichungsdatum vom 5. September 2026.
- Keine erfundenen Features, Dokumentation, weiteren Channels oder Metadaten;
  die dafür vorgesehenen Empty States bleiben sichtbar.
- Bestätigte CLI-Syntax `install-registry` statt der Kurzsyntax im Mockup.
- Deaktivierte Header-Funktionen wie ausdrücklich freigegeben.
- Kleine Status- und Metadatentexte mit ausreichendem Kontrast; mobile Copy-/
  Download-/Installationsbedienelemente mit mindestens 44 Pixeln Zielgröße.
- Bluesky, LinkedIn und RSS bleiben nach ausdrücklicher Freigabe vom
  6. September 2026 funktionslos und nicht fokussierbar, mit `aria-disabled="true"`.

## Grenzen und Risiken

- Der Deploy benötigt die vorhandene migrierte DB sowie das root-eigene
  DB-EnvironmentFile. Manuelle Aktivierungsflags sollten daraus entfernt werden;
  deaktivierte Schalter werden zusätzlich mit `UnsetEnvironment` entfernt.
- Vollständige Suche mit Filtern und Kennzahlen läuft bei der aktuellen kleinen
  Registry über paginierte API-Lesezugriffe. Bei wesentlich größeren Datenmengen
  sind kombinierte serverseitige Such-/Aggregationsendpunkte sinnvoll.
- Änderungen an Gesamtzahl oder doppelte Modul-IDs während der Pagination werden
  als Fehler behandelt; unbekannte Lizenz-Ausdrücke ergeben keine geschätzte Quote.
- GitHub-/Dokumentationslinks stammen aus API-Metadaten oder bekannten Projektzielen;
  es gibt keine implementierte Anmeldung, Übersetzungs- oder Theme-Funktion.
- Promotion-Semantik, DB-Transaktionsmodell, Artefakt-Policy, vorhandene Registry-
  Inhalte und Host-/Modulrepositories bleiben unverändert.

## Geänderte Dateien

- [.github/workflows/registry.yml](../.github/workflows/registry.yml)
- [deploy/ansible/README.md](../deploy/ansible/README.md)
- [deploy/ansible/inventory/group_vars/packages_registry.yml](../deploy/ansible/inventory/group_vars/packages_registry.yml)
- [deploy/ansible/roles/packages_registry/defaults/main.yml](../deploy/ansible/roles/packages_registry/defaults/main.yml)
- [deploy/ansible/roles/packages_registry/tasks/main.yml](../deploy/ansible/roles/packages_registry/tasks/main.yml)
- [deploy/ansible/roles/packages_registry/templates/packages-registry-backend.service.j2](../deploy/ansible/roles/packages_registry/templates/packages-registry-backend.service.j2)
- [deploy/ansible/tests/test_registry_v2_deployment.py](../deploy/ansible/tests/test_registry_v2_deployment.py)
- [docs/package-hub-issue-50-review.md](../docs/package-hub-issue-50-review.md)
- [docs/screenshots/package-hub/desktop.png](../docs/screenshots/package-hub/desktop.png)
- [docs/screenshots/package-hub/mobile.png](../docs/screenshots/package-hub/mobile.png)
- [docs/screenshots/package-hub/tablet.png](../docs/screenshots/package-hub/tablet.png)
- [pyproject.toml](../pyproject.toml)
- [web/README.md](../web/README.md)
- [web/frontend/README.md](../web/frontend/README.md)
- [web/frontend/app/assets/css/main.css](../web/frontend/app/assets/css/main.css)
- [web/frontend/app/components/AppFooter.vue](../web/frontend/app/components/AppFooter.vue)
- [web/frontend/app/components/AppHeader.vue](../web/frontend/app/components/AppHeader.vue)
- [web/frontend/app/components/CopyValue.vue](../web/frontend/app/components/CopyValue.vue)
- [web/frontend/app/components/FilterPanel.vue](../web/frontend/app/components/FilterPanel.vue)
- [web/frontend/app/components/GlobalPackageSearch.vue](../web/frontend/app/components/GlobalPackageSearch.vue)
- [web/frontend/app/components/HubHero.vue](../web/frontend/app/components/HubHero.vue)
- [web/frontend/app/components/HubIcon.vue](../web/frontend/app/components/HubIcon.vue)
- [web/frontend/app/components/ModuleNavigation.vue](../web/frontend/app/components/ModuleNavigation.vue)
- [web/frontend/app/components/PackageCard.vue](../web/frontend/app/components/PackageCard.vue)
- [web/frontend/app/components/PackageIcon.vue](../web/frontend/app/components/PackageIcon.vue)
- [web/frontend/app/components/PackageListItem.vue](../web/frontend/app/components/PackageListItem.vue)
- [web/frontend/app/components/PackageMetadataRail.vue](../web/frontend/app/components/PackageMetadataRail.vue)
- [web/frontend/app/components/ProvenancePanel.vue](../web/frontend/app/components/ProvenancePanel.vue)
- [web/frontend/app/components/SearchCommandPalette.vue](../web/frontend/app/components/SearchCommandPalette.vue)
- [web/frontend/app/components/SearchResultList.vue](../web/frontend/app/components/SearchResultList.vue)
- [web/frontend/app/error.vue](../web/frontend/app/error.vue)
- [web/frontend/app/layouts/default.vue](../web/frontend/app/layouts/default.vue)
- [web/frontend/app/lib/api.ts](../web/frontend/app/lib/api.ts)
- [web/frontend/app/lib/modulePresentation.ts](../web/frontend/app/lib/modulePresentation.ts)
- [web/frontend/app/pages/about.vue](../web/frontend/app/pages/about.vue)
- [web/frontend/app/pages/docs.vue](../web/frontend/app/pages/docs.vue)
- [web/frontend/app/pages/index.vue](../web/frontend/app/pages/index.vue)
- [web/frontend/app/pages/packages/[moduleId]/[version].vue](../web/frontend/app/pages/packages/[moduleId]/[version].vue)
- [web/frontend/app/pages/packages/[moduleId]/index.vue](../web/frontend/app/pages/packages/[moduleId]/index.vue)
- [web/frontend/app/pages/packages/index.vue](../web/frontend/app/pages/packages/index.vue)
- [web/frontend/app/pages/publishers/[publisherId].vue](../web/frontend/app/pages/publishers/[publisherId].vue)
- [web/frontend/app/pages/publishers/index.vue](../web/frontend/app/pages/publishers/index.vue)
- [web/frontend/app/types/api.ts](../web/frontend/app/types/api.ts)
- [web/frontend/nuxt.config.ts](../web/frontend/nuxt.config.ts)
- [web/frontend/package.json](../web/frontend/package.json)
- [web/frontend/public/gis-layers.svg](../web/frontend/public/gis-layers.svg)
- [web/frontend/public/logo.svg](../web/frontend/public/logo.svg)
- [web/frontend/tests/api.test.ts](../web/frontend/tests/api.test.ts)
- [web/frontend/tests/fixtures.ts](../web/frontend/tests/fixtures.ts)
- [web/frontend/tests/fixtures/statistics-0.4.0.json](../web/frontend/tests/fixtures/statistics-0.4.0.json)
- [web/frontend/tests/fixtures/statistics.json](../web/frontend/tests/fixtures/statistics.json)
- [web/frontend/tests/pages.test.ts](../web/frontend/tests/pages.test.ts)
- [web/frontend/tests/ssr.mjs](../web/frontend/tests/ssr.mjs)
- [web/frontend/tests/ui.test.ts](../web/frontend/tests/ui.test.ts)
