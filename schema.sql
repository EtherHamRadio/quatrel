-- QuaTrel database schema (matches spec v0.3)
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS types       (id INTEGER PRIMARY KEY, label TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS roles       (id INTEGER PRIMARY KEY, label TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS locations   (id INTEGER PRIMARY KEY, label TEXT UNIQUE NOT NULL);
CREATE TABLE IF NOT EXISTS event_kinds (id INTEGER PRIMARY KEY, label TEXT UNIQUE NOT NULL,
                                        sort_order INTEGER NOT NULL DEFAULT 0);
CREATE TABLE IF NOT EXISTS statuses    (id INTEGER PRIMARY KEY, label TEXT UNIQUE NOT NULL,
                                        sort_order INTEGER NOT NULL DEFAULT 0,
                                        hidden_by_default INTEGER NOT NULL DEFAULT 0);

CREATE TABLE IF NOT EXISTS things (
    id          INTEGER PRIMARY KEY,
    name        TEXT NOT NULL,
    type_id     INTEGER NOT NULL REFERENCES types(id),
    location_id INTEGER REFERENCES locations(id),
    status_id   INTEGER NOT NULL REFERENCES statuses(id),
    wiki_url    TEXT,
    notes       TEXT
);

CREATE TABLE IF NOT EXISTS thing_roles (
    thing_id INTEGER NOT NULL REFERENCES things(id),
    role_id  INTEGER NOT NULL REFERENCES roles(id),
    PRIMARY KEY (thing_id, role_id)
);

CREATE TABLE IF NOT EXISTS events (
    id          INTEGER PRIMARY KEY,
    thing_id    INTEGER NOT NULL REFERENCES things(id),
    event_when  TEXT NOT NULL,
    kind_id     INTEGER NOT NULL REFERENCES event_kinds(id),
    location_id INTEGER REFERENCES locations(id),
    status_id   INTEGER REFERENCES statuses(id),
    description TEXT
);

CREATE TABLE IF NOT EXISTS event_role_changes (
    event_id INTEGER NOT NULL REFERENCES events(id),
    role_id  INTEGER NOT NULL REFERENCES roles(id),
    change   TEXT NOT NULL CHECK (change IN ('added', 'removed')),
    PRIMARY KEY (event_id, role_id)
);

CREATE INDEX IF NOT EXISTS idx_events_thing ON events(thing_id);
CREATE INDEX IF NOT EXISTS idx_events_when  ON events(event_when);
