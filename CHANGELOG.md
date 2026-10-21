# Changelog

## 0.1.3 (2026-10-21)

- Starter template example rows are generic.
- When sorting by WHY with no filter, the count now says how many things are listed, not just how many rows.
- First public release on GitHub, with an MIT license.

## 0.1.2 (2026-10-21)

- Changes are refused unless they come from QuaTrel's own pages, so a web page in another browser tab can't make changes behind your back.
- Wiki links must be `http://` or `https://`; any other link is shown as plain text.
- JSON restore accepts only QuaTrel's real columns, checked before anything is deleted.
- Starter CSV imports are re-checked when confirmed.
- Random secret key, created on first run and stored next to the database.
- Optional shared password (`QUATREL_PASSWORD`).
- Runs on the waitress web server when it is installed.
- `deploy` folder with a systemd service file and example settings.

## 0.1.1 (2026-10-21)

- WHEN accepts `20261021`, `2026-10-21`, or `10/21/2026`, with an optional time such as `1430` or `14:30`.

## 0.1.0 (2026-10-21)

- First version: four-facet search with primary, secondary, and tertiary slots; status filter; thing history pages with automatic move, role, and status events; starter CSV import with preview; CSV and JSON export; JSON restore; Settings for every list.
