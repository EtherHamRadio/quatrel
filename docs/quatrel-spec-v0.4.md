# QuaTrel — Specification

**Version:** 0.4
**Date:** 2026-10-21
**Author:** Tom Salzer, KJ7T
**Implemented by:** QuaTrel 0.1.2
**Pronunciation:** KWAH-trel (from *quaternary* + *relational*)

---

## 1. Purpose

QuaTrel is a small, single-file database for documenting equipment and what happens to it. Every record can be found and ordered along four independent facets: **WHAT** it is, **WHY** it exists, **WHERE** it is, and **WHEN** something happened to it. A separate **status** shows whether each thing is in service, set aside, or gone.

It is meant to complement a wiki, not replace one. QuaTrel holds the structured facts; a wiki (e.g., DokuWiki) holds the prose. Each thing can link to its own wiki page.

Design goals:

- Simple enough for one person to install, understand, and back up.
- One SQLite file holds all the data.
- A small web app written in Python with Flask, run on one computer or as a service on a home network.
- Useful to other people without modification: the four facets are fixed, but every user defines their own vocabulary within them.
- Easy to start: a spreadsheet of existing gear can be imported in one step.
- The complete history of every thing is preserved and easy to see.
- Unused equipment is as easy to find as equipment in service, because a spare is valuable precisely because it *could* be used.

## 2. Core concepts

### 2.1 The four facets

| Facet | Interface label | Meaning | Examples | Values per thing |
|---|---|---|---|---|
| **What** | WHAT (thing) | The kind of hardware | router, Raspberry Pi, PC, hotspot | One |
| **Why** | WHY (role) | What it is used for | networking, AllStar, M17, transcription | One or more |
| **Where** | WHERE (location) | Location | lake house, Portland, office | One (current) |
| **When** | WHEN (date or timestamp) | When an event happened | 2026-09-14, or 2026-09-14 19:30 | One per event |

WHAT describes the hardware, not its job. A Raspberry Pi running an AllStar node is WHAT = Raspberry Pi, WHY = AllStar. Keeping the two apart lets "show me my AllStar nodes" (filter WHY) and "do I have a spare Raspberry Pi?" (filter WHAT) both work.

### 2.2 Status

Status is not a fifth facet. It is a filter that works alongside the picker (section 4.3). Every thing has exactly one current status. The default list:

| Status | Meaning |
|---|---|
| **In service** | Doing its job. |
| **Spare** | Works; set aside on purpose as a backup for a specific job. |
| **Surplus** | Works, but not needed; available to repurpose, lend, or sell. |
| **Broken** | Needs repair or diagnosis. |
| **Retired** | Gone for good (sold, given away, scrapped). Kept only for history. |

The difference between **spare** and **surplus** is intent: a spare is held for something; surplus is available for anything.

The status list can be changed in Settings (section 7), including which statuses are hidden by default. New things default to **In service**.

### 2.3 Name is a label, not a facet

Each thing has a **name** (e.g., "ASL node 588416," "Deco"). The name identifies the thing, breaks ties in sorting, and links to the thing's history page and, optionally, its wiki page. It is not searched as a facet.

### 2.4 Things and events

QuaTrel stores two kinds of records:

- A **thing** is a piece of equipment. It has a name, one type (WHAT), one or more roles (WHY), a current location (WHERE), and a current status.
- An **event** is something that happened to a thing at a date or timestamp (WHEN): purchased, put in service, updated, moved, repaired, repurposed, retired.

A thing has many events, and every thing has at least one: the starting event created when the thing is added or imported. History is never overwritten; it accumulates as events.

### 2.5 User-defined vocabularies

Types, roles, and locations start empty and are entered by each user, either in Settings, directly on the Add thing form, or automatically by a starter CSV import (section 6.1). Event kinds and statuses start from default lists that the user can change in Settings. This is what lets one ham's "lake house / AllStar" and another user's "county EOC / ARES" use the same software.

## 3. Data model

```sql
-- Vocabularies (user-defined)
CREATE TABLE types       (id INTEGER PRIMARY KEY, label TEXT UNIQUE NOT NULL);
CREATE TABLE roles       (id INTEGER PRIMARY KEY, label TEXT UNIQUE NOT NULL);
CREATE TABLE locations   (id INTEGER PRIMARY KEY, label TEXT UNIQUE NOT NULL);
CREATE TABLE event_kinds (id INTEGER PRIMARY KEY, label TEXT UNIQUE NOT NULL,
                          sort_order INTEGER NOT NULL DEFAULT 0);
CREATE TABLE statuses    (id INTEGER PRIMARY KEY, label TEXT UNIQUE NOT NULL,
                          sort_order INTEGER NOT NULL DEFAULT 0,
                          hidden_by_default INTEGER NOT NULL DEFAULT 0);  -- 1 for Retired

-- Things
CREATE TABLE things (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    type_id     INTEGER NOT NULL REFERENCES types(id),
    location_id INTEGER REFERENCES locations(id),          -- current location
    status_id   INTEGER NOT NULL REFERENCES statuses(id),  -- current status
    wiki_url    TEXT,                                      -- http:// or https:// only
    notes       TEXT
);

-- A thing can have several roles (many-to-many)
CREATE TABLE thing_roles (
    thing_id INTEGER NOT NULL REFERENCES things(id),
    role_id  INTEGER NOT NULL REFERENCES roles(id),
    PRIMARY KEY (thing_id, role_id)
);

-- Events
CREATE TABLE events (
    id          INTEGER PRIMARY KEY,
    thing_id    INTEGER NOT NULL REFERENCES things(id),
    event_when  TEXT NOT NULL,       -- stored as YYYY-MM-DD or YYYY-MM-DD HH:MM
    kind_id     INTEGER NOT NULL REFERENCES event_kinds(id),
    location_id INTEGER REFERENCES locations(id),   -- where the thing was after this event
    status_id   INTEGER REFERENCES statuses(id),    -- the thing's status after this event
    description TEXT
);

-- Role changes recorded with an event (for repurposing history)
CREATE TABLE event_role_changes (
    event_id INTEGER NOT NULL REFERENCES events(id),
    role_id  INTEGER NOT NULL REFERENCES roles(id),
    change   TEXT NOT NULL CHECK (change IN ('added', 'removed')),
    PRIMARY KEY (event_id, role_id)
);
```

Notes on the model:

- **WHEN input and storage.** WHEN can be typed as `20261021`, `2026-10-21`, `10/21/2026`, or `10/21/26`, optionally followed by a time such as `1430` or `14:30`. A blank WHEN means today. QuaTrel always stores the normalized form (`2026-10-21` or `2026-10-21 14:30`), so dates sort correctly as text and a date-only entry sorts before timed entries on the same day. YYYYMMDD is recommended in spreadsheets, which never reformat it.
- **"Today" comes from the server's clock**, so the computer or container running QuaTrel must be set to the user's time zone.
- **Location, status, and role history all work the same way.** The thing holds the current value; each event records the value after that event happened.
- **Role changes** are recorded with one row in `event_role_changes` for each role added or removed. `thing_roles` always holds the current roles. A thing's starting event records all its initial roles as added.

## 4. Search: the picker

The search page shows the four facets with their labels and prompts:

> **WHAT** (thing) · **WHY** (role) · **WHERE** (location) · **WHEN** (date or timestamp)

### 4.1 Slots

The user arranges the facets into three ordered slots: **primary**, **secondary**, and **tertiary**. Each slot is configured with:

1. **Facet**: WHAT, WHY, WHERE, or WHEN. A facet can be used in only one slot; a repeat is ignored.
2. **Filter** (optional): a single value, or "any." For WHEN, the filter is a from/to date range, inclusive of the whole "to" day.
3. **Order**: default, A→Z / oldest first, or Z→A / newest first. The defaults are newest first for WHEN and A→Z for the others.

Results are filtered by every slot that has a filter and by the status filter, then ordered by primary, then secondary, then tertiary. Ties are broken by thing name, A to Z. **Reset** clears all slots and restores the default status filter; it never changes data.

Every search is expressed in the page's URL, so a search can be bookmarked and reopened later.

### 4.2 Choosing the view

- **Event view** (one row per event): used when WHEN is chosen in any slot. Columns: WHEN, thing, kind, WHERE, status, description. WHERE and status are as of that event.
- **Thing view** (one row per thing): used when WHEN is not chosen. Columns: thing, WHAT, WHY, WHERE, status, last event.

In both views, the name links to the thing's history page (section 5). A small "wiki" link beside the name opens the wiki page when one is set.

### 4.3 Status filter

Below the slots, a row of checkboxes, one per status. By default every status is checked except those marked hidden by default (initially just **Retired**). The checkboxes filter on the thing's **current** status in both views.

Example: "Do I have a spare Raspberry Pi?" Primary: WHAT, filtered to Raspberry Pi. Secondary: WHERE. Status: only **Spare** and **Surplus** checked.

### 4.4 Filtering and sorting by WHY

- The WHY filter selects **one role at a time**. It returns every thing that has that role, even if it also has others. Searching for combinations of roles is not supported.
- In thing view, the WHY column shows all of a thing's current roles.
- When WHY is used for sorting with no filter, a thing with several roles is listed once under each of its roles, like the entries in a book index.

## 5. Things and their history

### 5.1 Adding a thing

The Add thing form takes a name, WHAT, WHY (checkboxes), WHERE, status, an optional wiki URL, and notes. New WHAT, WHY, and WHERE values can be typed directly on the form; several new roles can be entered at once, separated by semicolons or commas. The form also records the **starting event**: its WHEN (default today), kind (default "in service"), and an optional description. "Save and add another" returns to a blank form.

### 5.2 The thing's history page

Every thing has its own page:

- **Header:** name, WHAT, WHY, WHERE, status, wiki link, and notes.
- **Record an event:** WHEN (default today), kind (default "updated"), WHERE after this, status after this, and a description.
- **History:** every event, newest first by default, with a link to show oldest first. Each entry shows WHEN, kind, WHERE, status, and description, with changes highlighted where they happened:
  - "moved: Portland → lake house"
  - "status: In service → Broken"
  - "roles: + AllStar, − radio lab computer"

### 5.3 Rules for changes

- **Editing a thing** (Edit button) that changes its WHERE, WHY, or status records an event automatically. Its kind is chosen automatically unless the user picks one: repurposed (roles changed), moved (location changed), retired (new status hidden by default), repaired (status changed from Broken), in service (status changed to In service), otherwise updated. Edits to the name, WHAT, wiki URL, or notes alone do not create an event.
- **A backdated event** (older than the thing's latest event) is added to history but does not change the thing's current WHERE or status.
- **Deleting an event** removes it from history without changing the thing's current values.
- **Deleting a thing** removes it and its entire history, after confirmation. Setting the status to Retired is the way to keep the history.

## 6. Import and export

### 6.1 Starter CSV

The easy on-ramp for new users: build a list of existing gear in any spreadsheet, one row per thing, save it as CSV, and import it.

| Column | Required? | Contents |
|---|---|---|
| name | yes | The thing's name |
| what | yes | WHAT (thing) |
| why | no | WHY (role); several roles in one cell separated by semicolons, e.g. `AllStar; DVSwitch` |
| where | no | WHERE (location) |
| status | no | Blank means In service |
| when | no | Date of the starting event, in any WHEN format; blank means today |
| wiki_url | no | Link to the thing's wiki page (http:// or https:// only) |
| notes | no | Anything else |

Rules:

- Column headers are matched without regard to case; columns can be in any order; extra columns are ignored; blank rows are skipped.
- Files saved as UTF-8 (including Excel's "CSV UTF-8") or Windows-1252 are accepted.
- Any WHAT, WHY, WHERE, or status value QuaTrel hasn't seen is added to its list automatically, so a new user's vocabulary builds itself from the spreadsheet.
- Before anything is saved, QuaTrel shows a **preview**: every row, plus the new vocabulary values the import will create, so near-duplicates such as "Lake House" and "lake house" can be caught. If any row has a problem, the preview lists the problems by row number and nothing is imported.
- Each row becomes a thing with a starting event ("in service," or "retired" for a hidden status), described as "Imported from starter CSV."
- The Import / export page offers a downloadable template with the headers and example rows.

### 6.2 Export

- `quatrel-things.csv`: one row per thing, in the starter CSV layout, so it can be re-imported elsewhere.
- `quatrel-events.csv`: every event, oldest first, including roles added and removed.
- **JSON backup** (`quatrel-backup-YYYYMMDD-HHMM.json`): everything, for a full restore.

### 6.3 Restore

A JSON backup can be restored from the Import / export page. It replaces everything and requires a confirmation checkbox. The SQLite database file itself can also be copied as a backup while QuaTrel is stopped.

## 7. Settings

The Settings page manages every list: types, roles, locations, event kinds, and statuses. Any value can be renamed, and the change appears everywhere. A value that is in use can be renamed but not deleted; Settings shows how many times each value is used. Event kinds and statuses have an order number; statuses also have a "hidden by default" setting. Event kinds and statuses must keep at least one value.

Default event kinds: purchased, in service, updated, configured, moved, repaired, repurposed, retired.

## 8. Security

QuaTrel is built for a single computer or a trusted home network. It must never be exposed directly to the internet; for access away from home, use a VPN such as Tailscale or WireGuard.

- **No user accounts.** An optional shared password (`QUATREL_PASSWORD`) makes the browser ask for a password before showing anything. Any user name is accepted. Over plain HTTP, the password crosses the network lightly encoded rather than encrypted; over a VPN, the whole connection is encrypted.
- **Same-origin changes only.** Every change (any form submission) is refused unless it comes from one of QuaTrel's own pages, so a web page open in another browser tab cannot make changes behind the user's back.
- **Database safety.** Every value is passed to SQLite as a parameter, never pasted into SQL text. Table names in SQL come only from QuaTrel's own fixed list. A JSON restore is checked against each table's real columns before anything is deleted.
- **Page safety.** Every value is escaped when displayed. Wiki links must be `http://` or `https://`; anything else is rejected on entry and shown as plain text, never as a link.
- **Import safety.** Rows are checked when previewed and checked again when the import is confirmed, since they pass back through the browser in between.
- **Uploads** are limited to 10 MB.
- **Secret key.** A random secret key is created on first run and stored next to the database, readable only by the account running QuaTrel.

## 9. Running QuaTrel

### 9.1 Technology

- Python 3.9 or newer, Flask, and SQLite through Python's built-in `sqlite3` module.
- The waitress web server when it is installed; otherwise Flask's built-in server.
- Server-rendered HTML templates, with a few lines of JavaScript on the search page to show the right filter for each slot.
- Pages adapt to phone width and to the browser's light or dark mode.

### 9.2 Settings (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `QUATREL_DB` | `quatrel.db` next to `app.py` | Database location; its folder also holds the secret key |
| `QUATREL_HOST` | `127.0.0.1` | `0.0.0.0` to accept connections from other computers |
| `QUATREL_PORT` | `5000` | Port |
| `QUATREL_PASSWORD` | (none) | Shared password; strongly recommended whenever `QUATREL_HOST` is not `127.0.0.1` |

### 9.3 Deployment patterns

- **Single computer.** Run `python app.py` in a Python virtual environment; QuaTrel is reachable only from that computer. The program folder should not be inside a cloud-synced folder such as OneDrive, since syncing a live SQLite file can damage it.
- **Home network service.** Run QuaTrel on a small Linux server or container (e.g., a Debian 13 LXC on Proxmox) under its own unprivileged service account, with the program in `/opt/quatrel`, data in `/var/lib/quatrel`, and settings in `/etc/quatrel.env`. The `deploy` folder provides a systemd service file and an example settings file. The server should have a fixed address and the user's time zone.
- **Upgrades** replace the program files and reinstall the Python packages; the data folder is never touched.

## 10. Out of scope for this version

- A fifth facet, *who* (lending equipment, shared ownership).
- Multiple users, logins, or permissions.
- Searching for combinations of roles.
- Editing an existing event (it can be deleted and re-entered).
- File attachments and photos (link to the wiki page instead).
- HTTPS within QuaTrel itself (use a VPN, or a reverse proxy that provides HTTPS).
- Automatic syncing with a wiki or other inventory systems.

## 11. Open questions

1. **Sample vocabulary for GitHub.** Ship a sample set (ham radio, homelab) to show new users how the facets work, built from real entries that have worked well.
2. **Assemblies.** Some things are made of other things (e.g., an AllStar node built from an Arduino UNO Q, a USB hub, and a radio interface). Should parts be tracked as their own things, linked to the assembly, so spare interfaces can be found?
3. **Event editing.** Is delete-and-re-enter enough, or should events be editable?
4. **Event kinds from starter CSV.** Should the starter CSV allow a "kind" column for the starting event (e.g., "purchased" with a purchase date)?

## 12. Revision history

| Version | Date | Notes |
|---|---|---|
| 0.1 | 2026-10-21 | First draft: four facets, two-table model, picker behavior. |
| 0.2 | 2026-10-21 | Interface labels with prompts; Flask chosen; WHEN accepts date or timestamp; single-role WHY filter; event kinds editable in Settings; thing history page with automatic role-change tracking; CSV and JSON import/export. |
| 0.3 | 2026-10-21 | Added status (in service, spare, surplus, broken, retired) as a filter alongside the picker, with history tracked like location; Retired hidden by default; vocabularies start empty; sample set deferred to GitHub publication. |
| 0.4 | 2026-10-21 | Matches QuaTrel 0.1.2. Name spelled QuaTrel; WHAT labeled "(thing)" and defined as hardware, not role; starter CSV import with preview and template; WHEN accepts YYYYMMDD, YYYY-MM-DD, or M/D/YYYY with optional time; rules for automatic events, backdated events, and deletions; searches bookmarkable by URL; security section (optional password, same-origin changes, link and restore checks, re-checked imports, upload limit, random secret key); deployment patterns and settings; assemblies and other new open questions. |
