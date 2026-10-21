"""QuaTrel: a four-facet equipment log (WHAT, WHY, WHERE, WHEN).

Version 0.1.3. Built from QuaTrel spec v0.4.
0.1.1: WHEN accepts YYYYMMDD, YYYY-MM-DD, or M/D/YYYY, with an optional time.
0.1.2: Rejects changes that don't come from QuaTrel's own pages; wiki links must be
       http/https; JSON restore accepts only known columns; import is re-checked on
       confirm; random secret key; optional password (QUATREL_PASSWORD); runs on
       the waitress server when it is installed.
0.1.3: Generic example rows in the starter template; correct count when WHY lists a thing once per role.
Run with:  python app.py   then open http://127.0.0.1:5000
"""
import csv
import io
import json
import os
import secrets
import sqlite3
from datetime import date, datetime, timedelta
from urllib.parse import urlsplit

from flask import (Flask, Response, abort, flash, g, redirect,
                   render_template, request, url_for)

APP_VERSION = "0.1.3"
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.abspath(os.environ.get("QUATREL_DB", os.path.join(BASE_DIR, "quatrel.db")))
DATA_DIR = os.path.dirname(DB_PATH)
PASSWORD = os.environ.get("QUATREL_PASSWORD", "")


def load_secret_key():
    """Use QUATREL_SECRET if set; otherwise a random key kept next to the database."""
    if os.environ.get("QUATREL_SECRET"):
        return os.environ["QUATREL_SECRET"]
    path = os.path.join(DATA_DIR, ".quatrel-secret")
    try:
        with open(path, encoding="utf-8") as f:
            key = f.read().strip()
        if key:
            return key
    except OSError:
        pass
    key = secrets.token_hex(32)
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(key)
        os.chmod(path, 0o600)
    except OSError:
        pass
    return key


os.makedirs(DATA_DIR, exist_ok=True)
app = Flask(__name__)
app.secret_key = load_secret_key()
app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 * 1024  # 10 MB uploads


def same_origin():
    """True when a form submission came from a QuaTrel page on this same host."""
    source = request.headers.get("Origin") or request.headers.get("Referer")
    if not source or source == "null":
        return False
    return urlsplit(source).netloc.lower() == request.host.lower()


@app.before_request
def guard():
    if PASSWORD:
        auth = request.authorization
        given = (auth.password or "") if auth else ""
        if not secrets.compare_digest(given.encode(), PASSWORD.encode()):
            return Response("QuaTrel needs a password.", 401,
                            {"WWW-Authenticate": 'Basic realm="QuaTrel", charset="UTF-8"'})
    if request.method == "POST" and not same_origin():
        return Response("QuaTrel refused this change because it didn't come from a "
                        "QuaTrel page. Go back, reload the page, and try again.", 403,
                        {"Content-Type": "text/plain; charset=utf-8"})


def clean_url(value):
    """Return an http(s) URL or "", or raise ValueError for any other kind of link."""
    u = (value or "").strip()
    if not u:
        return ""
    parts = urlsplit(u)
    if parts.scheme.lower() not in ("http", "https") or not parts.netloc:
        raise ValueError(f'"{u}" isn\'t a web link. Wiki links must start with http:// or https://')
    return u


@app.template_filter("safe_url")
def safe_url(value):
    try:
        return clean_url(value)
    except ValueError:
        return ""

DEFAULT_EVENT_KINDS = ["purchased", "in service", "updated", "configured",
                       "moved", "repaired", "repurposed", "retired"]
DEFAULT_STATUSES = [("In service", 0), ("Spare", 0), ("Surplus", 0),
                    ("Broken", 0), ("Retired", 1)]

FACETS = {
    "what": ("WHAT", "thing"),
    "why": ("WHY", "role"),
    "where": ("WHERE", "location"),
    "when": ("WHEN", "date or timestamp"),
}

# Vocabulary tables. Table names come only from this dict, so they are
# safe to place in SQL strings.
VOCABS = {
    "types": {"title": "Types", "facet": "WHAT (thing)",
              "usage": [("things", "type_id")]},
    "roles": {"title": "Roles", "facet": "WHY (role)",
              "usage": [("thing_roles", "role_id"),
                        ("event_role_changes", "role_id")]},
    "locations": {"title": "Locations", "facet": "WHERE (location)",
                  "usage": [("things", "location_id"),
                            ("events", "location_id")]},
    "event_kinds": {"title": "Event kinds", "facet": "",
                    "usage": [("events", "kind_id")], "sortable": True},
    "statuses": {"title": "Statuses", "facet": "",
                 "usage": [("things", "status_id"), ("events", "status_id")],
                 "sortable": True, "hideable": True},
}

STARTER_COLUMNS = ["name", "what", "why", "where", "status", "when",
                   "wiki_url", "notes"]


# ---------------------------------------------------------------- database

def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DB_PATH)
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db


@app.teardown_appcontext
def close_db(exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def init_db():
    db = sqlite3.connect(DB_PATH)
    with open(os.path.join(BASE_DIR, "schema.sql"), encoding="utf-8") as f:
        db.executescript(f.read())
    if db.execute("SELECT COUNT(*) FROM event_kinds").fetchone()[0] == 0:
        db.executemany("INSERT INTO event_kinds(label, sort_order) VALUES (?, ?)",
                       [(k, i) for i, k in enumerate(DEFAULT_EVENT_KINDS)])
    if db.execute("SELECT COUNT(*) FROM statuses").fetchone()[0] == 0:
        db.executemany("INSERT INTO statuses(label, sort_order, hidden_by_default) "
                       "VALUES (?, ?, ?)",
                       [(s, i, h) for i, (s, h) in enumerate(DEFAULT_STATUSES)])
    db.commit()
    db.close()


def vocab(name):
    order = "sort_order, label COLLATE NOCASE" if VOCABS[name].get("sortable") \
        else "label COLLATE NOCASE"
    return get_db().execute(f"SELECT * FROM {name} ORDER BY {order}").fetchall()


def find_label(table, label):
    row = get_db().execute(f"SELECT id FROM {table} WHERE label = ? COLLATE NOCASE",
                           (label.strip(),)).fetchone()
    return row["id"] if row else None


def get_or_create(table, label):
    label = (label or "").strip()
    if not label:
        return None
    found = find_label(table, label)
    if found:
        return found
    db = get_db()
    if VOCABS[table].get("sortable"):
        nxt = db.execute(f"SELECT COALESCE(MAX(sort_order), -1) + 1 FROM {table}").fetchone()[0]
        cur = db.execute(f"INSERT INTO {table}(label, sort_order) VALUES (?, ?)", (label, nxt))
    else:
        cur = db.execute(f"INSERT INTO {table}(label) VALUES (?)", (label,))
    return cur.lastrowid


def usage_count(table, row_id):
    db = get_db()
    return sum(db.execute(f"SELECT COUNT(*) FROM {t} WHERE {c} = ?", (row_id,)).fetchone()[0]
               for t, c in VOCABS[table]["usage"])


def first_kind_id():
    row = get_db().execute("SELECT id FROM event_kinds ORDER BY sort_order LIMIT 1").fetchone()
    return row["id"] if row else None


def kind_id_for(*labels):
    for label in labels:
        found = find_label("event_kinds", label)
        if found:
            return found
    return first_kind_id()


def thing_roles_map():
    rows = get_db().execute(
        "SELECT tr.thing_id, r.label FROM thing_roles tr JOIN roles r ON r.id = tr.role_id "
        "ORDER BY r.label COLLATE NOCASE").fetchall()
    out = {}
    for r in rows:
        out.setdefault(r["thing_id"], []).append(r["label"])
    return out


# ---------------------------------------------------------------- helpers

def to_int(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def today():
    return date.today().isoformat()


DATE_INPUT_FORMATS = ["%Y-%m-%d", "%Y%m%d", "%m/%d/%Y", "%m/%d/%y"]
TIME_INPUT_FORMATS = ["%H:%M", "%H%M", "%H:%M:%S"]
WHEN_HELP = ("Use YYYYMMDD (20261021), YYYY-MM-DD, or M/D/YYYY, "
             "optionally followed by a time such as 1430 or 14:30.")


def clean_when(value):
    """Accept several date and time spellings; return YYYY-MM-DD or YYYY-MM-DD HH:MM.

    Raises ValueError for anything that isn't a real date.
    """
    s = (value or "").strip().replace("T", " ")
    if not s:
        return today()
    parts = s.split()
    bad = ValueError(f'"{value}" is not a date. {WHEN_HELP}')
    if len(parts) > 2:
        raise bad
    dpart = parts[0]
    d = None
    for fmt in DATE_INPUT_FORMATS:
        if fmt == "%Y%m%d" and not (len(dpart) == 8 and dpart.isdigit()):
            continue
        try:
            d = datetime.strptime(dpart, fmt).date()
            break
        except ValueError:
            continue
    if d is None:
        raise bad
    out = d.isoformat()
    if len(parts) == 2:
        tpart = parts[1]
        t = None
        for fmt in TIME_INPUT_FORMATS:
            if fmt == "%H%M" and not (len(tpart) == 4 and tpart.isdigit()):
                continue
            try:
                t = datetime.strptime(tpart, fmt).time()
                break
            except ValueError:
                continue
        if t is None:
            raise bad
        out += " " + t.strftime("%H:%M")
    return out


def next_day(value):
    d = datetime.strptime(value[:10], "%Y-%m-%d").date()
    return (d + timedelta(days=1)).isoformat()


def split_roles(cell):
    return [r.strip() for r in (cell or "").split(";") if r.strip()]


@app.context_processor
def inject_globals():
    return {"APP_VERSION": APP_VERSION, "FACETS": FACETS}


# ---------------------------------------------------------------- search

@app.route("/")
def index():
    db = get_db()
    args = request.args
    statuses = vocab("statuses")

    slots, used = [], set()
    for n in ("1", "2", "3"):
        facet = args.get(f"f{n}", "")
        if facet not in FACETS or facet in used:
            slots.append({"n": n, "facet": "", "value": "", "dir": "", "from": "", "to": ""})
            continue
        used.add(facet)
        d = args.get(f"d{n}", "")
        if d not in ("asc", "desc"):
            d = ""
        slots.append({"n": n, "facet": facet, "value": args.get(f"v{n}", ""), "dir": d,
                      "from": args.get(f"from{n}", ""), "to": args.get(f"to{n}", "")})

    if "go" in args:
        st_ids = [i for i in (to_int(x) for x in args.getlist("st")) if i is not None]
    else:
        st_ids = [s["id"] for s in statuses if not s["hidden_by_default"]]

    active = [s for s in slots if s["facet"]]
    event_view = any(s["facet"] == "when" for s in active)
    why_slot = next((s for s in active if s["facet"] == "why"), None)
    why_index = bool(why_slot and not to_int(why_slot["value"]))

    where, params, joins, order = [], [], [], []
    loc_alias = "el" if event_view else "l"
    sort_expr = {"what": "ty.label COLLATE NOCASE",
                 "why": "COALESCE(r.label, '') COLLATE NOCASE",
                 "where": f"COALESCE({loc_alias}.label, '') COLLATE NOCASE",
                 "when": "e.event_when"}
    errors = []

    if why_slot:
        joins.append("LEFT JOIN thing_roles tr ON tr.thing_id = t.id "
                     "LEFT JOIN roles r ON r.id = tr.role_id")

    for s in active:
        f, v = s["facet"], to_int(s["value"])
        if f == "what" and v:
            where.append("t.type_id = ?"); params.append(v)
        elif f == "why" and v:
            where.append("r.id = ?"); params.append(v)
        elif f == "where" and v:
            where.append(f"{loc_alias}.id = ?"); params.append(v)
        elif f == "when":
            try:
                if s["from"].strip():
                    where.append("e.event_when >= ?"); params.append(clean_when(s["from"])[:10])
                if s["to"].strip():
                    where.append("e.event_when < ?"); params.append(next_day(clean_when(s["to"])))
            except ValueError as exc:
                errors.append(str(exc))
        default_dir = "desc" if f == "when" else "asc"
        order.append(f"{sort_expr[f]} {(s['dir'] or default_dir).upper()}")

    if st_ids:
        where.append(f"t.status_id IN ({','.join('?' * len(st_ids))})")
        params.extend(st_ids)
    else:
        where.append("0")

    order.append("t.name COLLATE NOCASE ASC")
    why_col = ", r.label AS why_label" if why_slot else ""
    where_sql = " AND ".join(where) if where else "1"

    if event_view:
        order.append("e.event_when DESC, e.id DESC")
        sql = (f"SELECT e.id AS event_id, e.event_when, e.description, t.id, t.name, t.wiki_url, "
               f"k.label AS kind, el.label AS location, es.label AS status{why_col} "
               f"FROM events e JOIN things t ON t.id = e.thing_id "
               f"JOIN types ty ON ty.id = t.type_id "
               f"JOIN event_kinds k ON k.id = e.kind_id "
               f"LEFT JOIN locations el ON el.id = e.location_id "
               f"LEFT JOIN statuses es ON es.id = e.status_id "
               f"{' '.join(joins)} WHERE {where_sql} ORDER BY {', '.join(order)}")
    else:
        sql = (f"SELECT t.id, t.name, t.wiki_url, ty.label AS type, l.label AS location, "
               f"s.label AS status, "
               f"(SELECT MAX(event_when) FROM events WHERE thing_id = t.id) AS last_event{why_col} "
               f"FROM things t JOIN types ty ON ty.id = t.type_id "
               f"LEFT JOIN locations l ON l.id = t.location_id "
               f"JOIN statuses s ON s.id = t.status_id "
               f"{' '.join(joins)} WHERE {where_sql} ORDER BY {', '.join(order)}")

    rows = [] if errors else db.execute(sql, params).fetchall()
    for e in errors:
        flash(e, "error")

    return render_template(
        "index.html", slots=slots, rows=rows, event_view=event_view,
        why_index=why_index, roles_map=thing_roles_map(),
        types=vocab("types"), roles=vocab("roles"), locations=vocab("locations"),
        statuses=statuses, st_ids=set(st_ids),
        thing_count=db.execute("SELECT COUNT(*) FROM things").fetchone()[0])


# ---------------------------------------------------------------- things

def blank_thing():
    in_service = find_label("statuses", "In service")
    return {"name": "", "type_id": None, "location_id": None,
            "status_id": in_service, "role_ids": set(), "wiki_url": "", "notes": ""}


def read_thing_form():
    """Read the thing form. May create new vocabulary rows (caller commits or rolls back)."""
    f = request.form
    data = {
        "name": f.get("name", "").strip(),
        "type_id": to_int(f.get("type_id")),
        "location_id": to_int(f.get("location_id")),
        "status_id": to_int(f.get("status_id")),
        "role_ids": {i for i in (to_int(x) for x in f.getlist("role_ids")) if i},
        "wiki_url": f.get("wiki_url", "").strip(),
        "notes": f.get("notes", "").strip(),
    }
    if f.get("new_type", "").strip():
        data["type_id"] = get_or_create("types", f["new_type"])
    if f.get("new_location", "").strip():
        data["location_id"] = get_or_create("locations", f["new_location"])
    for r in f.get("new_roles", "").replace(",", ";").split(";"):
        if r.strip():
            data["role_ids"].add(get_or_create("roles", r))
    errors = []
    try:
        data["wiki_url"] = clean_url(data["wiki_url"])
    except ValueError as exc:
        errors.append(str(exc))
    if not data["name"]:
        errors.append("Give the thing a name.")
    if not data["type_id"]:
        errors.append("Choose or add a WHAT (thing) type.")
    if not data["status_id"]:
        errors.append("Choose a status.")
    return data, errors


def thing_form_context(t, ev, mode, thing_id=None):
    return dict(t=t, ev=ev, mode=mode, thing_id=thing_id, types=vocab("types"),
                roles=vocab("roles"), locations=vocab("locations"),
                statuses=vocab("statuses"), kinds=vocab("event_kinds"))


def insert_event(thing_id, when, kind_id, location_id, status_id, description,
                 added=(), removed=()):
    db = get_db()
    cur = db.execute("INSERT INTO events(thing_id, event_when, kind_id, location_id, "
                     "status_id, description) VALUES (?, ?, ?, ?, ?, ?)",
                     (thing_id, when, kind_id, location_id, status_id, description or None))
    for rid in added:
        db.execute("INSERT INTO event_role_changes VALUES (?, ?, 'added')", (cur.lastrowid, rid))
    for rid in removed:
        db.execute("INSERT INTO event_role_changes VALUES (?, ?, 'removed')", (cur.lastrowid, rid))
    return cur.lastrowid


@app.route("/thing/new", methods=["GET", "POST"])
def thing_new():
    db = get_db()
    if request.method == "POST":
        try:
            when = clean_when(request.form.get("event_when"))
        except ValueError as exc:
            when, err = None, str(exc)
        data, errors = read_thing_form()
        if when is None:
            errors.append(err)
        if errors:
            db.rollback()
            for e in errors:
                flash(e, "error")
            ev = {"kind_id": to_int(request.form.get("event_kind_id")),
                  "when": request.form.get("event_when", ""),
                  "description": request.form.get("event_description", "")}
            return render_template("thing_form.html", **thing_form_context(data, ev, "new"))
        cur = db.execute("INSERT INTO things(name, type_id, location_id, status_id, wiki_url, notes) "
                         "VALUES (?, ?, ?, ?, ?, ?)",
                         (data["name"], data["type_id"], data["location_id"], data["status_id"],
                          data["wiki_url"] or None, data["notes"] or None))
        tid = cur.lastrowid
        for rid in data["role_ids"]:
            db.execute("INSERT INTO thing_roles VALUES (?, ?)", (tid, rid))
        kind = to_int(request.form.get("event_kind_id")) or kind_id_for("in service")
        insert_event(tid, when, kind, data["location_id"], data["status_id"],
                     request.form.get("event_description", "").strip(), added=data["role_ids"])
        db.commit()
        flash(f'Added "{data["name"]}".', "ok")
        if request.form.get("another"):
            return redirect(url_for("thing_new"))
        return redirect(url_for("thing_view", thing_id=tid))
    ev = {"kind_id": kind_id_for("in service"), "when": today(), "description": ""}
    return render_template("thing_form.html", **thing_form_context(blank_thing(), ev, "new"))


def load_thing(thing_id):
    row = get_db().execute("SELECT * FROM things WHERE id = ?", (thing_id,)).fetchone()
    if row is None:
        abort(404)
    return row


def auto_kind(roles_changed, loc_changed, st_changed, old_status_id, new_status_id):
    db = get_db()
    if roles_changed:
        return kind_id_for("repurposed", "updated")
    if loc_changed:
        return kind_id_for("moved", "updated")
    if st_changed:
        new = db.execute("SELECT * FROM statuses WHERE id = ?", (new_status_id,)).fetchone()
        old = db.execute("SELECT * FROM statuses WHERE id = ?", (old_status_id,)).fetchone()
        if new and new["hidden_by_default"]:
            return kind_id_for("retired", "updated")
        if old and old["label"].lower() == "broken":
            return kind_id_for("repaired", "updated")
        if new and new["label"].lower() == "in service":
            return kind_id_for("in service", "updated")
    return kind_id_for("updated")


@app.route("/thing/<int:thing_id>/edit", methods=["GET", "POST"])
def thing_edit(thing_id):
    db = get_db()
    old = load_thing(thing_id)
    old_roles = {r["role_id"] for r in
                 db.execute("SELECT role_id FROM thing_roles WHERE thing_id = ?", (thing_id,))}
    if request.method == "POST":
        try:
            when = clean_when(request.form.get("event_when"))
        except ValueError as exc:
            when, err = None, str(exc)
        data, errors = read_thing_form()
        if when is None:
            errors.append(err)
        if errors:
            db.rollback()
            for e in errors:
                flash(e, "error")
            ev = {"kind_id": to_int(request.form.get("event_kind_id")),
                  "when": request.form.get("event_when", ""),
                  "description": request.form.get("event_description", "")}
            return render_template("thing_form.html",
                                   **thing_form_context(data, ev, "edit", thing_id))
        db.execute("UPDATE things SET name = ?, type_id = ?, location_id = ?, status_id = ?, "
                   "wiki_url = ?, notes = ? WHERE id = ?",
                   (data["name"], data["type_id"], data["location_id"], data["status_id"],
                    data["wiki_url"] or None, data["notes"] or None, thing_id))
        added = data["role_ids"] - old_roles
        removed = old_roles - data["role_ids"]
        for rid in removed:
            db.execute("DELETE FROM thing_roles WHERE thing_id = ? AND role_id = ?", (thing_id, rid))
        for rid in added:
            db.execute("INSERT INTO thing_roles VALUES (?, ?)", (thing_id, rid))
        loc_changed = data["location_id"] != old["location_id"]
        st_changed = data["status_id"] != old["status_id"]
        desc = request.form.get("event_description", "").strip()
        if loc_changed or st_changed or added or removed or desc:
            kind = to_int(request.form.get("event_kind_id")) or auto_kind(
                bool(added or removed), loc_changed, st_changed,
                old["status_id"], data["status_id"])
            insert_event(thing_id, when, kind, data["location_id"], data["status_id"],
                         desc, added, removed)
            flash("Saved, and recorded the change as an event.", "ok")
        else:
            flash("Saved.", "ok")
        db.commit()
        return redirect(url_for("thing_view", thing_id=thing_id))
    t = dict(old)
    t["role_ids"] = old_roles
    ev = {"kind_id": None, "when": today(), "description": ""}
    return render_template("thing_form.html", **thing_form_context(t, ev, "edit", thing_id))


@app.route("/thing/<int:thing_id>")
def thing_view(thing_id):
    db = get_db()
    t = db.execute("SELECT t.*, ty.label AS type, l.label AS location, s.label AS status "
                   "FROM things t JOIN types ty ON ty.id = t.type_id "
                   "LEFT JOIN locations l ON l.id = t.location_id "
                   "JOIN statuses s ON s.id = t.status_id WHERE t.id = ?",
                   (thing_id,)).fetchone()
    if t is None:
        abort(404)
    roles = thing_roles_map().get(thing_id, [])
    events = db.execute("SELECT e.*, k.label AS kind, l.label AS location, s.label AS status "
                        "FROM events e JOIN event_kinds k ON k.id = e.kind_id "
                        "LEFT JOIN locations l ON l.id = e.location_id "
                        "LEFT JOIN statuses s ON s.id = e.status_id "
                        "WHERE e.thing_id = ? ORDER BY e.event_when, e.id",
                        (thing_id,)).fetchall()
    changes = {}
    for rc in db.execute("SELECT erc.event_id, erc.change, r.label FROM event_role_changes erc "
                         "JOIN roles r ON r.id = erc.role_id JOIN events e ON e.id = erc.event_id "
                         "WHERE e.thing_id = ? ORDER BY r.label COLLATE NOCASE", (thing_id,)):
        sign = "+" if rc["change"] == "added" else "\u2212"
        changes.setdefault(rc["event_id"], []).append(f"{sign} {rc['label']}")

    timeline, prev = [], None
    for e in events:
        notes = []
        if prev is not None:
            if e["location_id"] != prev["location_id"]:
                notes.append(f"moved: {prev['location'] or '(none)'} \u2192 {e['location'] or '(none)'}")
            if e["status_id"] != prev["status_id"]:
                notes.append(f"status: {prev['status'] or '(none)'} \u2192 {e['status'] or '(none)'}")
        if e["id"] in changes:
            notes.append("roles: " + ", ".join(changes[e["id"]]))
        timeline.append({"e": e, "notes": notes})
        prev = e
    order = request.args.get("order", "desc")
    if order != "asc":
        timeline.reverse()
    return render_template("thing.html", t=t, roles=roles, timeline=timeline, order=order,
                           kinds=vocab("event_kinds"), locations=vocab("locations"),
                           statuses=vocab("statuses"), now=today())


@app.route("/thing/<int:thing_id>/event", methods=["POST"])
def event_add(thing_id):
    db = get_db()
    t = load_thing(thing_id)
    try:
        when = clean_when(request.form.get("event_when"))
    except ValueError as exc:
        flash(str(exc), "error")
        return redirect(url_for("thing_view", thing_id=thing_id))
    kind = to_int(request.form.get("kind_id")) or first_kind_id()
    loc = to_int(request.form.get("location_id"))
    st = to_int(request.form.get("status_id")) or t["status_id"]
    latest = db.execute("SELECT MAX(event_when) FROM events WHERE thing_id = ?",
                        (thing_id,)).fetchone()[0]
    insert_event(thing_id, when, kind, loc, st, request.form.get("description", "").strip())
    if latest is None or when >= latest:
        db.execute("UPDATE things SET location_id = ?, status_id = ? WHERE id = ?",
                   (loc, st, thing_id))
        flash("Event recorded.", "ok")
    else:
        flash("Event recorded. It is older than the latest event, so the thing's current "
              "location and status were left as they were.", "ok")
    db.commit()
    return redirect(url_for("thing_view", thing_id=thing_id))


@app.route("/event/<int:event_id>/delete", methods=["POST"])
def event_delete(event_id):
    db = get_db()
    e = db.execute("SELECT thing_id FROM events WHERE id = ?", (event_id,)).fetchone()
    if e is None:
        abort(404)
    db.execute("DELETE FROM event_role_changes WHERE event_id = ?", (event_id,))
    db.execute("DELETE FROM events WHERE id = ?", (event_id,))
    db.commit()
    flash("Event deleted. The thing's current details were not changed.", "ok")
    return redirect(url_for("thing_view", thing_id=e["thing_id"]))


@app.route("/thing/<int:thing_id>/delete", methods=["POST"])
def thing_delete(thing_id):
    db = get_db()
    t = load_thing(thing_id)
    db.execute("DELETE FROM event_role_changes WHERE event_id IN "
               "(SELECT id FROM events WHERE thing_id = ?)", (thing_id,))
    db.execute("DELETE FROM events WHERE thing_id = ?", (thing_id,))
    db.execute("DELETE FROM thing_roles WHERE thing_id = ?", (thing_id,))
    db.execute("DELETE FROM things WHERE id = ?", (thing_id,))
    db.commit()
    flash(f'Deleted "{t["name"]}" and its history.', "ok")
    return redirect(url_for("index"))


# ---------------------------------------------------------------- settings

@app.route("/settings")
def settings():
    lists = []
    for name, cfg in VOCABS.items():
        rows = [dict(r, uses=usage_count(name, r["id"])) for r in vocab(name)]
        lists.append({"name": name, "cfg": cfg, "rows": rows})
    return render_template("settings.html", lists=lists)


def check_vocab(name):
    if name not in VOCABS:
        abort(404)
    return VOCABS[name]


@app.route("/settings/<name>/add", methods=["POST"])
def vocab_add(name):
    check_vocab(name)
    label = request.form.get("label", "").strip()
    if not label:
        flash("Enter a label to add.", "error")
    elif find_label(name, label):
        flash(f'"{label}" is already in the list.', "error")
    else:
        get_or_create(name, label)
        get_db().commit()
        flash(f'Added "{label}".', "ok")
    return redirect(url_for("settings") + f"#{name}")


@app.route("/settings/<name>/<int:row_id>/update", methods=["POST"])
def vocab_update(name, row_id):
    cfg = check_vocab(name)
    db = get_db()
    label = request.form.get("label", "").strip()
    other = find_label(name, label) if label else None
    if not label:
        flash("A label can't be empty.", "error")
    elif other and other != row_id:
        flash(f'"{label}" is already in the list.', "error")
    else:
        db.execute(f"UPDATE {name} SET label = ? WHERE id = ?", (label, row_id))
        if cfg.get("sortable"):
            db.execute(f"UPDATE {name} SET sort_order = ? WHERE id = ?",
                       (to_int(request.form.get("sort_order")) or 0, row_id))
        if cfg.get("hideable"):
            db.execute(f"UPDATE {name} SET hidden_by_default = ? WHERE id = ?",
                       (1 if request.form.get("hidden") else 0, row_id))
        db.commit()
        flash("Saved.", "ok")
    return redirect(url_for("settings") + f"#{name}")


@app.route("/settings/<name>/<int:row_id>/delete", methods=["POST"])
def vocab_delete(name, row_id):
    check_vocab(name)
    db = get_db()
    if usage_count(name, row_id):
        flash("That value is in use, so it can be renamed but not deleted.", "error")
    elif name in ("event_kinds", "statuses") and \
            db.execute(f"SELECT COUNT(*) FROM {name}").fetchone()[0] <= 1:
        flash("This list needs at least one value.", "error")
    else:
        db.execute(f"DELETE FROM {name} WHERE id = ?", (row_id,))
        db.commit()
        flash("Deleted.", "ok")
    return redirect(url_for("settings") + f"#{name}")


# ---------------------------------------------------------------- import / export

def csv_response(filename, header, rows):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(header)
    w.writerows(rows)
    return Response("\ufeff" + buf.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment; filename={filename}"})


@app.route("/import-export")
def import_export():
    return render_template("import_export.html")


@app.route("/export/quatrel-things.csv")
def export_things_csv():
    db = get_db()
    roles = thing_roles_map()
    rows = []
    for t in db.execute("SELECT t.*, ty.label AS type, l.label AS location, s.label AS status, "
                        "(SELECT MIN(event_when) FROM events WHERE thing_id = t.id) AS first_when "
                        "FROM things t JOIN types ty ON ty.id = t.type_id "
                        "LEFT JOIN locations l ON l.id = t.location_id "
                        "JOIN statuses s ON s.id = t.status_id ORDER BY t.name COLLATE NOCASE"):
        rows.append([t["name"], t["type"], "; ".join(roles.get(t["id"], [])),
                     t["location"] or "", t["status"], t["first_when"] or "",
                     t["wiki_url"] or "", t["notes"] or ""])
    return csv_response("quatrel-things.csv", STARTER_COLUMNS, rows)


@app.route("/export/quatrel-events.csv")
def export_events_csv():
    db = get_db()
    rc = {}
    for r in db.execute("SELECT erc.event_id, erc.change, r.label FROM event_role_changes erc "
                        "JOIN roles r ON r.id = erc.role_id"):
        rc.setdefault((r["event_id"], r["change"]), []).append(r["label"])
    rows = []
    for e in db.execute("SELECT e.*, t.name, k.label AS kind, l.label AS location, "
                        "s.label AS status FROM events e JOIN things t ON t.id = e.thing_id "
                        "JOIN event_kinds k ON k.id = e.kind_id "
                        "LEFT JOIN locations l ON l.id = e.location_id "
                        "LEFT JOIN statuses s ON s.id = e.status_id "
                        "ORDER BY e.event_when, e.id"):
        rows.append([e["name"], e["event_when"], e["kind"], e["location"] or "",
                     e["status"] or "", e["description"] or "",
                     "; ".join(rc.get((e["id"], "added"), [])),
                     "; ".join(rc.get((e["id"], "removed"), []))])
    return csv_response("quatrel-events.csv",
                        ["thing", "when", "kind", "where", "status", "description",
                         "roles_added", "roles_removed"], rows)


JSON_TABLES = ["types", "roles", "locations", "event_kinds", "statuses",
               "things", "thing_roles", "events", "event_role_changes"]


@app.route("/export/quatrel.json")
def export_json():
    db = get_db()
    data = {"app": "QuaTrel", "version": APP_VERSION,
            "exported": datetime.now().isoformat(timespec="seconds")}
    for table in JSON_TABLES:
        data[table] = [dict(r) for r in db.execute(f"SELECT * FROM {table}")]
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    return Response(json.dumps(data, indent=2), mimetype="application/json",
                    headers={"Content-Disposition":
                             f"attachment; filename=quatrel-backup-{stamp}.json"})


@app.route("/import/json", methods=["POST"])
def import_json():
    if not request.form.get("confirm"):
        flash("Tick the box to confirm that the backup will replace everything.", "error")
        return redirect(url_for("import_export"))
    upload = request.files.get("file")
    try:
        data = json.loads(upload.read().decode("utf-8-sig"))
        if data.get("app") != "QuaTrel" or any(t not in data for t in JSON_TABLES):
            raise ValueError
    except Exception:
        flash("That file isn't a QuaTrel JSON backup.", "error")
        return redirect(url_for("import_export"))
    db = get_db()
    # Accept only the columns QuaTrel's tables really have, checked before anything is deleted.
    for table in JSON_TABLES:
        allowed = {r[1] for r in db.execute(f"PRAGMA table_info({table})")}
        rows = data[table]
        if not isinstance(rows, list) or any(
                not isinstance(row, dict) or not row or set(row) - allowed for row in rows):
            flash(f'That backup has unexpected data in "{table}", so nothing was restored.', "error")
            return redirect(url_for("import_export"))
    try:
        for table in reversed(JSON_TABLES):
            db.execute(f"DELETE FROM {table}")
        for table in JSON_TABLES:
            for row in data[table]:
                cols = list(row.keys())  # already checked against the table's real columns
                db.execute(f"INSERT INTO {table} ({', '.join(cols)}) "
                           f"VALUES ({', '.join('?' * len(cols))})",
                           [row[c] for c in cols])
        db.commit()
    except sqlite3.Error as exc:
        db.rollback()
        flash(f"Restore failed, nothing was changed: {exc}", "error")
        return redirect(url_for("import_export"))
    flash(f"Restored {len(data['things'])} things and {len(data['events'])} events.", "ok")
    return redirect(url_for("index"))


@app.route("/import/quatrel-starter-template.csv")
def starter_template():
    return csv_response("quatrel-starter-template.csv", STARTER_COLUMNS, [
        ["shack router", "router", "networking", "shack", "", "", "", ""],
        ["AllStar node 1", "Raspberry Pi", "AllStar; DVSwitch", "shack", "In service",
         "20260315", "", "Pi 4 with a USB radio interface"],
        ["old Pi 3B", "Raspberry Pi", "", "garage", "Spare", "", "", "Works; kept as a backup"],
    ])


def parse_starter_csv(text):
    """Parse a starter CSV. Returns (rows, errors)."""
    reader = csv.DictReader(io.StringIO(text))
    if reader.fieldnames is None:
        return [], ["The file is empty."]
    headers = {h.strip().lower(): h for h in reader.fieldnames if h}
    missing = [c for c in ("name", "what") if c not in headers]
    if missing:
        return [], [f"The file needs these column headers: {', '.join(missing)}. "
                    "Download the template to see the expected layout."]
    rows, errors = [], []
    for line, raw in enumerate(reader, start=2):
        cell = {c: (raw.get(headers[c]) or "").strip() if c in headers else ""
                for c in STARTER_COLUMNS}
        if not any(cell.values()):
            continue
        try:
            rows.append(validate_starter_row(cell))
        except ValueError as exc:
            errors.append(f"Row {line}: {exc}")
    return rows, errors


def validate_starter_row(cell):
    """Check and normalize one starter row; raise ValueError if it can't be imported."""
    cell = {c: str(cell.get(c) or "").strip() for c in STARTER_COLUMNS}
    if not cell["name"] or not cell["what"]:
        raise ValueError("name and what are both required.")
    cell["when"] = clean_when(cell["when"])
    cell["wiki_url"] = clean_url(cell["wiki_url"])
    cell["status"] = cell["status"] or "In service"
    cell["roles"] = split_roles(cell["why"])
    return cell


@app.route("/import/starter", methods=["POST"])
def import_starter():
    upload = request.files.get("file")
    if not upload or not upload.filename:
        flash("Choose a CSV file to import.", "error")
        return redirect(url_for("import_export"))
    raw = upload.read()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp1252", errors="replace")
    rows, errors = parse_starter_csv(text)
    if errors:
        return render_template("import_preview.html", rows=rows, errors=errors,
                               new={}, payload="")

    def new_values(table, values):
        seen, out = set(), []
        for v in values:
            if v and v.lower() not in seen and not find_label(table, v):
                seen.add(v.lower())
                out.append(v)
        return out

    new = {
        "WHAT (thing) types": new_values("types", [r["what"] for r in rows]),
        "WHY (role) roles": new_values("roles", [x for r in rows for x in r["roles"]]),
        "WHERE (location) locations": new_values("locations", [r["where"] for r in rows]),
        "Statuses": new_values("statuses", [r["status"] for r in rows]),
    }
    return render_template("import_preview.html", rows=rows, errors=[], new=new,
                           payload=json.dumps(rows))


@app.route("/import/starter/confirm", methods=["POST"])
def import_starter_confirm():
    # The preview page sends the rows back; check them again rather than trusting them.
    try:
        raw_rows = json.loads(request.form.get("payload", "[]"))
        if not isinstance(raw_rows, list) or not all(isinstance(r, dict) for r in raw_rows):
            raise ValueError
        rows = [validate_starter_row(r) for r in raw_rows]
    except ValueError:
        flash("That import couldn't be confirmed. Please import the CSV file again.", "error")
        return redirect(url_for("import_export"))
    db = get_db()
    for r in rows:
        type_id = get_or_create("types", r["what"])
        loc_id = get_or_create("locations", r["where"]) if r["where"] else None
        st_id = get_or_create("statuses", r["status"])
        cur = db.execute("INSERT INTO things(name, type_id, location_id, status_id, wiki_url, notes) "
                         "VALUES (?, ?, ?, ?, ?, ?)",
                         (r["name"], type_id, loc_id, st_id, r["wiki_url"] or None,
                          r["notes"] or None))
        tid = cur.lastrowid
        role_ids = {get_or_create("roles", x) for x in r["roles"]}
        for rid in role_ids:
            db.execute("INSERT INTO thing_roles VALUES (?, ?)", (tid, rid))
        hidden = db.execute("SELECT hidden_by_default FROM statuses WHERE id = ?",
                            (st_id,)).fetchone()[0]
        kind = kind_id_for("retired") if hidden else kind_id_for("in service")
        insert_event(tid, r["when"], kind, loc_id, st_id, "Imported from starter CSV",
                     added=role_ids)
    db.commit()
    flash(f"Imported {len(rows)} things. Each has a starting event, so you can record "
          "the next thing that happens to it.", "ok")
    return redirect(url_for("index"))


# ---------------------------------------------------------------- main

init_db()

if __name__ == "__main__":
    host = os.environ.get("QUATREL_HOST", "127.0.0.1")
    port = int(os.environ.get("QUATREL_PORT", "5000"))
    local_only = host in ("127.0.0.1", "localhost", "::1")
    where = (f"http://{host}:{port}" if local_only
             else f"http://<this computer's address>:{port} from other computers on your network")
    print(f"QuaTrel {APP_VERSION} - open {where}. Press Ctrl+C to stop.", flush=True)
    print(f"Data: {DB_PATH}", flush=True)
    if not local_only and not PASSWORD:
        print("Note: no QUATREL_PASSWORD is set, so anyone on your network can make changes.",
              flush=True)
    try:
        from waitress import serve
    except ImportError:
        serve = None
    if serve:
        serve(app, host=host, port=port, threads=4)
    else:
        app.run(host=host, port=port, debug=False)
