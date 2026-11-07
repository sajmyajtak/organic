"""Most do KLAPKY: fronta obsahu (content/*) → Airtable tabulka „SM Obsah“.

KLAPKA (~/Projects/firststep) ukazuje v SM Automation → Obsah frontu z tohoto
automatu a Simon v ní schvaluje koncepty. Tohle je jediné místo v igbotu, které
o KLAPCE ví:

    igbot  ──fronta──▶   KLAPKA   (koncepty, plán, publikováno, chyby)
    igbot  ◀─rozhodnutí─ KLAPKA   (schválit / zamítnout koncept)

Pravidla:

1. **Sync sahá jen na své řádky**, poznává je podle PostId (= id položky)
   a účtu. Co v tabulce vznikne jinak, zůstane nedotčené.
2. **Rozhodnutí patří člověku.** Sync ho jen čte; po provedení ho vymaže,
   jinak na něj nesahá.
3. **Co Simon v KLAPCE smaže, se nevrátí.** Když řádek zmizí, položka dostane
   značku `gone` a už se nikdy neposílá.
4. **Posílají se jen změny.** Každá položka si v YAML pamatuje (`klapka:`),
   jaký řádek jí patří a co se naposled odeslalo. Ta paměť cestuje se souborem
   mezi složkami i přes git, takže lokální běh a GitHub Actions nepotřebují
   společný stavový soubor (a nehádají se o něj při rebase).
5. **Tep automatu.** Technický řádek s PostId `__automat__` (založila ho
   KLAPKA) dostává při každém odeslání čas běhu, větu o stavu fronty a poslední
   chybu. Podle něj KLAPKA ukazuje „Automat Naturizz běží“ (okno 26 h), i když
   se ve frontě nic nemění. Sync ho jinak ignoruje: nemaže ho, nedává mu `gone`.
6. **Rozpočet volání.** Airtable free má ~1 000 volání měsíčně pro celý
   workspace (sdílené s leady a autoclippingem). Automatický běh po publikaci
   (každých 30 minut) proto posílá změny jen ve dvou časech denně, chyby hned;
   rozhodnutí čte jen když existují koncepty, nanejvýš 4× denně; z publikovaných
   drží v tabulce posledních 30. Cíl: do ~150 volání měsíčně.
"""

from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import requests

from . import content
from .config import env, load_config

API = "https://api.airtable.com/v0"
BASE = "appGpk4fkNBGoMyBN"
TABLE = "tblTI4L89U3s9ek48"  # SM Obsah

F_POST_ID = "fldyYc1YdatWWT4sj"
F_TITLE = "fldV8Sf6NX41Qj7V1"
F_ACCOUNT = "fld6JBUBpbsIWUEVD"
F_STATE = "fldVfqODpnXmDzo8k"
F_KIND = "fldkmKazBLzL14Ydp"
F_CAPTION = "fldBE0JPrHRxhO1ZV"
F_SLIDES = "fldVwFnZIe7il6WtB"
F_PLANNED = "fldKOO3mUu2TL7YjE"
F_PUBLISHED = "fldhCjNXBLiF0cE5S"
F_MEDIA_IDS = "fldMWAi1JRO4mC8fh"
F_ERROR = "fldyUPw5nNcMhMw9u"
F_CHANGED = "fldXluE8c6Oz8OlDp"
F_PREVIEW = "fldKg2cDaYiqZlBv9"
F_DECISION = "fldwwq94Hgty34Frw"  # lidské pole, jen čteme a po provedení mažeme

STATE_NAMES = {"drafts": "koncept", "approved": "schváleno", "published": "publikováno", "failed": "chyba"}
KIND_NAMES = {"carousel": "karusel", "image": "obrázek", "story": "story", "reel": "reel"}

BATCH = 10               # Airtable bere max 10 záznamů na request
KEEP_PUBLISHED = 30
PUSH_HOURS_UTC = (1, 13)          # automatické odeslání změn (~21:00 a 9:00 v New Yorku)
READ_HOURS_UTC = (1, 7, 13, 19)   # čtení rozhodnutí, jen když existují koncepty
KEY = "klapka"           # paměť syncu v YAML položky
HEARTBEAT_POST_ID = "__automat__"
HEARTBEAT_RECORD = "recKqXpfurb4jkWmD"  # založila KLAPKA; když zmizí, založíme nový
CZ_DAYS = ("po", "út", "st", "čt", "pá", "so", "ne")


class KlapkaError(RuntimeError):
    def __init__(self, message: str, status: int = 0, kind: str = ""):
        super().__init__(message)
        self.status, self.kind = status, kind

    @property
    def missing_row(self) -> bool:
        """The record no longer exists (deleted in KLAPKA), not a bad request."""
        return self.status == 404 or self.kind in ("ROW_DOES_NOT_EXIST", "NOT_FOUND", "MODEL_ID_NOT_FOUND")


class Airtable:
    """Minimal Airtable REST client that counts its calls."""

    def __init__(self, token: str, base: str = BASE, table: str = TABLE):
        self.url = f"{API}/{base}/{table}"
        self.headers = {"Authorization": f"Bearer {token}"}
        self.calls = 0

    def _request(self, method: str, params=None, body=None) -> tuple[int, dict]:
        time.sleep(0.22)  # 5 požadavků/s na base
        resp = requests.request(method, self.url, headers=self.headers, params=params, json=body, timeout=45)
        try:
            data = resp.json() if resp.content else {}
        except ValueError:
            data = {"error": resp.text[:300]}
        return resp.status_code, data

    def call(self, method: str, params=None, body=None) -> dict:
        self.calls += 1
        status, data = self._request(method, params, body)
        if status >= 400:
            err = data.get("error")
            kind = err.get("type", "") if isinstance(err, dict) else str(err or "")
            raise KlapkaError(f"Airtable {method} {status}: {err}", status, kind)
        return data

    def rows(self, fields: list[str]) -> list[dict]:
        out, offset = [], None
        while True:
            params = {"returnFieldsByFieldId": "true", "pageSize": 100, "fields[]": fields}
            if offset:
                params["offset"] = offset
            page = self.call("GET", params=params)
            out += page.get("records", [])
            offset = page.get("offset")
            if not offset:
                return out

    def create(self, records: list[dict]) -> list[dict]:
        body = {"records": [{"fields": f} for f in records], "returnFieldsByFieldId": True}
        return self.call("POST", body=body).get("records", [])

    def update(self, records: list[dict]) -> list[dict]:
        body = {"records": records, "returnFieldsByFieldId": True}
        return self.call("PATCH", body=body).get("records", [])

    def delete(self, ids: list[str]) -> None:
        self.call("DELETE", params={"records[]": ids})


def _chunks(seq: list, n: int = BATCH):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


def _slot(now: datetime, hours: tuple[int, ...]) -> bool:
    """True in the first half of the given UTC hours (the publish cron runs at :07 and :37)."""
    now = now.astimezone(timezone.utc)
    return now.hour in hours and now.minute < 30


_reachable: dict[str, bool] = {}


def _is_public(url: str) -> bool:
    """Airtable downloads an attachment URL once; a 404 then stays an empty
    preview for good, because the fingerprint says it was sent. So a preview
    goes out only when the file is really online (pushed); until then the
    field is left out and the next sync sends it."""
    if url not in _reachable:
        try:
            _reachable[url] = requests.head(url, timeout=10, allow_redirects=True).status_code == 200
        except requests.RequestException:
            _reachable[url] = False
    return _reachable[url]


def _preview_url(item: dict) -> str | None:
    for m in item.get("media") or []:
        m = str(m)
        if m.startswith("https://") and not m.lower().split("?")[0].endswith((".mp4", ".mov")):
            return m if _is_public(m) else None
    return None


def fields_for(item: dict, state: str, tz: str, account: str) -> dict:
    """Row fields for one queue item (without F_CHANGED, which is set on send)."""
    slides = item.get("slides") or []
    title = ((slides[0].get("title") if slides else "") or (item.get("script") or {}).get("hook_on_screen")
             or item["id"])
    error = item.get("error") or ("; ".join(item["problems"]) if item.get("problems") else None)
    fields = {
        F_POST_ID: item["id"],
        F_TITLE: str(title)[:250],
        F_ACCOUNT: account,
        F_STATE: STATE_NAMES[state],
        F_KIND: KIND_NAMES.get(item.get("kind")),
        F_CAPTION: content.full_caption(item) or None,
        F_SLIDES: len(item.get("media") or slides),
        F_PLANNED: content.scheduled_at(item, tz).isoformat(),
        F_PUBLISHED: _iso(item.get("published_at")),
        F_MEDIA_IDS: ",".join(str(m) for m in item.get("media_ids") or []) or None,
        F_ERROR: error,
    }
    preview = _preview_url(item)
    if preview:
        fields[F_PREVIEW] = [{"url": preview}]
    return fields


def _iso(value) -> str | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value)).isoformat(timespec="seconds")
    except ValueError:
        return str(value)


def _fingerprint(fields: dict) -> str:
    return hashlib.sha1(json.dumps(fields, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]


def _local() -> dict[str, tuple[str, dict]]:
    return {item["id"]: (state, item) for state in content.STATES for item in content.items(state)}


def _remember(item: dict, state: str, **memory) -> None:
    item[KEY] = {k: v for k, v in memory.items() if v is not None}
    content.save(item, state)


# --- tep automatu --------------------------------------------------------------

def _heartbeat_file() -> Path:
    # Lives in content/, which the publish workflow commits, so a recreated row
    # survives between runs. Normally it doesn't exist and the constant is used.
    return content.CONTENT_DIR / ".klapka-automat"


def _heartbeat_id() -> str:
    path = _heartbeat_file()
    return (path.read_text(encoding="utf-8").strip() if path.exists() else "") or HEARTBEAT_RECORD


def _set_heartbeat_id(record: str) -> None:
    if record != _heartbeat_id():
        path = _heartbeat_file()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(record + "\n", encoding="utf-8")


def _plural(n: int, one: str, few: str, many: str) -> str:
    return f"{n} {one if n == 1 else few if 2 <= n <= 4 else many}"


def status(local: dict[str, tuple[str, dict]], tz: str) -> tuple[str, str | None]:
    """One short Czech sentence about the queue, and the current error (or None)."""
    by_state: dict[str, list[dict]] = {}
    for state, item in local.values():
        by_state.setdefault(state, []).append(item)
    parts = []
    if by_state.get("drafts"):
        parts.append(_plural(len(by_state["drafts"]), "koncept", "koncepty", "konceptů"))
    approved = by_state.get("approved") or []
    if approved:
        parts.append(_plural(len(approved), "naplánovaný", "naplánované", "naplánovaných"))
        when = min(content.scheduled_at(i, tz) for i in approved)
        zone = "NY" if tz == "America/New_York" else tz.rsplit("/", 1)[-1]
        parts.append(f"další publikace {CZ_DAYS[when.weekday()]} {when:%H:%M} {zone}")
    else:
        parts.append("nic naplánováno")
    line = ", ".join(parts)
    failed = by_state.get("failed") or []
    error = None
    if failed:
        last = max(failed, key=lambda i: (i["date"], i["time"]))
        error = (f"{_plural(len(failed), 'položka selhala', 'položky selhaly', 'položek selhalo')}, "
                 f"poslední {last['id']}: {last.get('error') or 'bez popisu'}")[:500]
    return line[:1].upper() + line[1:], error


def _recreate_heartbeat(at: "Airtable", fields: dict, account: str) -> None:
    """The row is gone (deleted in KLAPKA): find another one with our PostId, else make it."""
    found = [r for r in at.rows([F_POST_ID]) if r["fields"].get(F_POST_ID) == HEARTBEAT_POST_ID]
    if found:
        record = found[0]["id"]
        at.update([{"id": record, "fields": fields}])
    else:
        record = at.create([{F_POST_ID: HEARTBEAT_POST_ID, F_ACCOUNT: account,
                             F_TITLE: "Automat Naturizz (technický řádek)",
                             **{k: v for k, v in fields.items() if v is not None}}])[0]["id"]
    _set_heartbeat_id(record)


def report_error(exc: Exception, now: datetime | None = None) -> None:
    """Best effort: show a failed sync as a red bar in KLAPKA."""
    token = env("AIRTABLE_TOKEN")
    if not token:
        return
    stamp = (now or datetime.now(timezone.utc)).isoformat(timespec="seconds").replace("+00:00", "Z")
    Airtable(token).update([{"id": _heartbeat_id(),
                             "fields": {F_CHANGED: stamp, F_ERROR: f"sync selhal: {exc}"[:500]}}])


@dataclass
class _Op:
    record: str
    fields: dict
    done: Callable[[], None]
    missing: Callable[[], None]


def sync(trigger: str = "cli", now: datetime | None = None, dry_run: bool = False,
         client: Airtable | None = None) -> dict:
    """Push queue changes to KLAPKA and apply its decisions. Returns a summary.

    trigger: "cli" (everything now), "generate"/"approve" (push now, a person is
    waiting for it), "publish" (automatic run every 30 min: push only in
    PUSH_HOURS_UTC or when there is a new error, read decisions in READ_HOURS_UTC).
    """
    token = env("AIRTABLE_TOKEN")
    if not token and client is None:
        return {"skipped": "chybí AIRTABLE_TOKEN"}
    now = now or datetime.now(timezone.utc)
    cfg = load_config()
    tz = cfg["account"]["timezone"]
    account = cfg["account"].get("handle") or "naturizz"
    at = client or Airtable(token)
    start = at.calls
    summary = {"created": 0, "updated": 0, "deleted": 0, "approved": 0, "rejected": 0, "gone": 0}

    automatic = trigger == "publish"
    local = _local()
    has_drafts = any(state == "drafts" for state, _ in local.values())
    # Right after generate/approve nobody has decided anything yet, so only the
    # CLI and the automatic run read decisions.
    read = not dry_run and (trigger == "cli" or (automatic and has_drafts and _slot(now, READ_HOURS_UTC)))
    clear_decision: set[str] = set()   # record ids whose decision we acted on
    to_delete: list[str] = []

    if read:
        listed = at.rows([F_POST_ID, F_ACCOUNT, F_DECISION])
        beats = [r["id"] for r in listed if r["fields"].get(F_POST_ID) == HEARTBEAT_POST_ID]
        if beats and _heartbeat_id() not in beats:
            _set_heartbeat_id(beats[0])
        # The heartbeat row is not a queue item: never adopted, deleted or decided on.
        rows = [r for r in listed if r["fields"].get(F_ACCOUNT) == account
                and r["fields"].get(F_POST_ID) not in (None, "", HEARTBEAT_POST_ID)]
        by_post: dict[str, list[dict]] = {}
        for r in rows:
            by_post.setdefault(r["fields"][F_POST_ID], []).append(r)
        record_ids = {r["id"] for r in rows}
        for post_id, (state, item) in local.items():
            memory = item.get(KEY) or {}
            if memory.get("gone"):
                continue
            if memory.get("record") and memory["record"] not in record_ids:
                _remember(item, state, gone="smazáno v KLAPCE")  # never send it again
                summary["gone"] += 1
            elif not memory.get("record") and post_id in by_post:
                _remember(item, state, record=by_post[post_id][0]["id"])  # adopt an existing row
        for post_id, dupes in by_post.items():  # extra rows for one PostId (e.g. lost memory)
            keep = (local.get(post_id, (None, {}))[1].get(KEY) or {}).get("record") or dupes[0]["id"]
            to_delete += [r["id"] for r in dupes if r["id"] != keep]

        for r in rows:
            decision = r["fields"].get(F_DECISION)
            decision = (decision.get("name") if isinstance(decision, dict) else decision or "").strip().lower()
            if not decision or r["id"] in to_delete:
                continue
            found = local.get(r["fields"][F_POST_ID])
            if not found:
                continue  # the item lives in another checkout; leave the decision for it
            state, item = found
            if decision == "schválit":
                if state == "drafts":
                    problems = content.validate(item)
                    if problems:
                        item["problems"] = problems
                        content.save(item, "drafts")
                    else:
                        item.pop("problems", None)
                        content.save(item, "approved")
                        summary["approved"] += 1
                clear_decision.add(r["id"])
            elif decision == "zamítnout":
                if state == "drafts":
                    Path(item["_path"]).unlink(missing_ok=True)
                    to_delete.append(r["id"])
                    summary["rejected"] += 1
                else:
                    clear_decision.add(r["id"])  # only drafts can be rejected; drop the request
        local = _local()

    # Published: keep only the newest KEEP_PUBLISHED rows.
    published = sorted((item for state, item in local.values() if state == "published"),
                       key=lambda i: i.get("published_at") or "", reverse=True)
    retire = [i for i in published[KEEP_PUBLISHED:] if not (i.get(KEY) or {}).get("gone")]
    retire_set = {i["id"] for i in retire}
    for item in [i for i in retire if not (i.get(KEY) or {}).get("record")]:
        _remember(item, "published", gone="starší publikované")  # never sent, never will be
    retire = [i for i in retire if (i.get(KEY) or {}).get("record")]
    # Deleting costs a call per 10 rows, so old rows wait for a full batch.
    if not (read or trigger == "cli" or len(retire) >= BATCH):
        retire = []
    to_delete += [i[KEY]["record"] for i in retire]

    creates: list[tuple[str, dict, dict, str]] = []
    updates: list[tuple[str, dict, dict, str, str]] = []
    for post_id, (state, item) in local.items():
        memory = item.get(KEY) or {}
        if memory.get("gone") or post_id in retire_set:
            continue
        fields = fields_for(item, state, tz, account)
        fp = _fingerprint(fields)
        record = memory.get("record")
        if not record:
            creates.append((state, item, fields, fp))
        elif fp != memory.get("sent") or record in clear_decision:
            updates.append((state, item, fields, fp, record))

    pending = bool(creates or updates or to_delete)
    urgent = any(state == "failed" for state, *_ in creates + updates)
    if automatic and pending and not (read or urgent or _slot(now, PUSH_HOURS_UTC)):
        summary["waiting"] = len(creates) + len(updates) + len(to_delete)
        summary["calls"] = at.calls - start
        return summary
    if dry_run:
        summary.update(created=len(creates), updated=len(updates), deleted=len(to_delete), dry_run=True)
        return summary

    stamp = now.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
    for chunk in _chunks(creates):
        made = at.create([{**{k: v for k, v in f.items() if v is not None}, F_CHANGED: stamp}
                          for _, _, f, _ in chunk])
        for (state, item, _, fp), rec in zip(chunk, made):
            _remember(item, state, record=rec["id"], sent=fp)
            summary["created"] += 1

    ops: list[_Op] = []
    for state, item, fields, fp, rec in updates:
        clear = {F_DECISION: None} if rec in clear_decision else {}

        def done(state=state, item=item, fp=fp, rec=rec):
            _remember(item, state, record=rec, sent=fp)
            summary["updated"] += 1

        def missing(state=state, item=item):
            _remember(item, state, gone="smazáno v KLAPCE")
            summary["gone"] += 1

        ops.append(_Op(rec, {**fields, F_CHANGED: stamp, **clear}, done, missing))

    # The heartbeat rides along in a PATCH: always in the push slots, for the CLI
    # and with a new error; otherwise only when it fits into a batch for free.
    beat_required = trigger == "cli" or (automatic and (urgent or _slot(now, PUSH_HOURS_UTC)))
    if beat_required or (ops and len(ops) % BATCH):
        line, error = status(local, tz)
        beat = {F_CHANGED: stamp, F_CAPTION: line, F_ERROR: error}

        def beat_done():
            summary["heartbeat"] = True

        def beat_missing():
            _recreate_heartbeat(at, beat, account)
            summary["heartbeat"] = True

        ops.append(_Op(_heartbeat_id(), beat, beat_done, beat_missing))

    for chunk in _chunks(ops):
        try:
            at.update([{"id": op.record, "fields": op.fields} for op in chunk])
            done_ops = chunk
        except KlapkaError:
            # One row deleted in KLAPKA fails the whole batch; find it one by one.
            done_ops = []
            for op in chunk:
                try:
                    at.update([{"id": op.record, "fields": op.fields}])
                    done_ops.append(op)
                except KlapkaError as exc:
                    if not exc.missing_row:
                        raise
                    op.missing()
        for op in done_ops:
            op.done()

    for chunk in _chunks(list(dict.fromkeys(to_delete))):
        at.delete(chunk)
        summary["deleted"] += len(chunk)
    for item in retire:
        _remember(item, "published", gone="starší publikované")
    summary["calls"] = at.calls - start
    return summary


def after(trigger: str) -> None:
    """Hook for generate/approve/publish: sync, but never break the caller."""
    try:
        result = sync(trigger)
    except Exception as exc:  # KLAPKA is a mirror; the queue in git is the source of truth
        print(f"KLAPKA: sync selhal ({exc})")
        # Tell KLAPKA, but from the automatic run only in the push slots (budget).
        if trigger != "publish" or _slot(datetime.now(timezone.utc), PUSH_HOURS_UTC):
            try:
                report_error(exc)
            except Exception:
                pass
        return
    if result.get("skipped"):
        if trigger != "publish":
            print(f"KLAPKA: přeskočeno ({result['skipped']})")
        return
    if result.get("calls"):
        print(f"KLAPKA: {describe(result)}")


def describe(result: dict) -> str:
    if result.get("skipped"):
        return f"přeskočeno ({result['skipped']})"
    parts = [f"{label} {result[key]}" for key, label in
             (("created", "nové"), ("updated", "změněné"), ("deleted", "smazané"), ("approved", "schválené"),
              ("rejected", "zamítnuté"), ("gone", "smazané v KLAPCE"), ("waiting", "čeká na odeslání"))
             if result.get(key)] + (["tep automatu"] if result.get("heartbeat") else [])
    calls = f"{result.get('calls', 0)} volání API"
    return (", ".join(parts) or "beze změn") + f" ({'nanečisto' if result.get('dry_run') else calls})"
