# Keep given content as a document snapshot

`POST /api/2.0/documents/<id>/snapshots/`, for the data dashboard's sync spec 2.

## Why

The sync design (data-dashboard `docs/superpowers/specs/2026-10-28-server-backed-documents-design.md`,
"Never lose a teacher's edits") says "Use the other version" and "Keep mine" both keep the version
they replace as a server snapshot, so either choice can be undone through "Restore an earlier
version".

"Keep mine" already works: its save sends `snapshot: "conflict"` and the server snapshots the stored
version it overwrites. "Use the other version" can't: the version it throws away exists only on
this device, so nothing on the server can snapshot it. The dashboard needs one request that hands
the server that content and has it kept as a `conflict` snapshot.

## Decided with the user (2026-11-02)

- **A separate endpoint, not a save option.** The first idea was an extra field on
  `PUT documents/<id>/` sent on a save that changes nothing. That save is accepted today, but it
  bumps `version` (other devices see a "new version" with no changes), writes an empty change-log
  entry, counts against the save rate limit, and re-uploads the server's own body (up to 1 MB)
  just to carry the snapshot. The only callers (`use-other`, and `discard` on deleted-elsewhere,
  which works like it) don't otherwise need to save. So `PUT` is unchanged and the snapshot list
  path gains a `POST`.

## Wire shape

Sent to `data-dashboard-ef` and `sdk-js-1d` on 2026-11-02.

```
POST /api/2.0/documents/<id>/snapshots/
{
  "base_version":   int >= 0,                 // the stored version the client set this aside against
  "schema_version": int >= 1,
  "name":           string (<= 100) | null,
  "body":           JSON object (no NaN/Infinity),
  "account_id":     string (<= 64),
  "build_id":       string (<= 64)
}

201 { "data": { "id", "version", "schema_version", "reason": "conflict", "created_at" } }
```

- Every field is required. This is a new endpoint, so no older client sends it.
- `version` is `base_version`. `reason` is always the existing `conflict`, so the reason
  enum is unchanged.
- The response keys are exactly those of a `GET .../snapshots/` row.
- The document is untouched: no `version` bump, no change-log entry, `updated_at` unchanged.
- Unknown request fields are ignored, as on a save.

### Refusals

The existing codes and payload shapes, checked in this order. Nothing is written before every
check passes.

| # | Code | Status | When | Payload |
|---|---|---|---|---|
| 1 | `invalid` | 400 | the URL id or any field fails validation (same messages as the save's) | `{fields: {...}}` |
| 2 | `too_large` | 413 | `measure(body) > DOCUMENTS_MAX_BODY`, or the request is over the signed-in request cap | — |
| 3 | `build_blocked` | 409 | `build_id` is a `BlockedBuild` | — |
| 4 | `account_mismatch` | 403 | `account_id` isn't the signed-in account | `{signed_in_as}` |
| 5 | `rate_limited` | 429 | over `DOCUMENTS_SAVES_PER_MINUTE`, counted on the same per-account counter as saves | — |
| 6 | `gone` / `not_found` | 410 / 404 | via `refuse_absent`: the caller's own purged id → `gone`; missing or someone else's → `not_found`, byte-identical | — |
| 7 | `stale_base` | 409 | `base_version != doc.version` | the save's `{version, schema_version, changes, document}` |

Not refused:
- a `schema_version` older or newer than the document's (snapshots can hold any schema; restore
  is the client's job)
- a trashed document (`deleted_at` set)
- the snapshot storage cap: `snapshots.trim` drops the owner's oldest snapshots instead
- the document storage cap, which counts documents only

## How it fits in

- **Shared validation.** Use the save's field checks (`check_field`, `check_id`, `is_json`,
  `measure`) and the save's account, blocked-build and rate-limit checks, not copies of them.
- **Row lock.** Run the ownership and version checks and the insert in one transaction, holding
  the document row lock (`locked_row`), so a concurrent save can't slip between the version
  check and the insert.
- **Snapshot write.** Store the given content, not the stored document. `snapshots.take` copies
  `doc`'s own fields, so add a sibling (or generalize `take`) that stores the given `name`, `body`,
  `schema_version`, `size = measure(body)` and `version = base_version`, then calls `trim`.
  `reason_for` is not involved.
- **Large bodies.** Signed-in requests use `DOCUMENTS_MAX_REQUEST_BYTES` instead of Django's
  `DATA_UPLOAD_MAX_MEMORY_SIZE`, via `read_save_body`, exactly as `DocumentDetail.dispatch` does
  for `PUT`. A 1 MB body can be up to 4 MB of UTF-8.
- **Hard rules kept.**
  - Login required; session CSRF enforced, as on `PUT`.
  - `NoStoreMixin` on every answer.
  - Someone else's id answers like a missing one.
  - No personal fields in the answer.
  - `DocumentSnapshot` stays unregistered in the admin, so no staff page ever shows its `body`.
- **Performance.** Constant work per call: one indexed blocked-build lookup, one row lock (body
  deferred), the rate-limit cache hit, one insert, and the existing `trim` aggregate. Loading the
  locked row with the body deferred matters only for the `stale_base` answer, which needs the full
  document; load it there, not on the happy path.

## Tests

Beside the existing ones, in `camp/api/v2/documents/tests/test_snapshots_api.py` (endpoint) and
`camp/apps/documents/tests/test_snapshots.py` (the new store helper), plus a CSRF case in
`test_csrf.py`. Cover:

- the 201 answer, its exact keys, `version == base_version`, `reason == "conflict"`, and the
  stored row's name, body, schema_version and size
- the document's `version`, `updated_at` and change log unchanged
- the new row appears in the GET list
- `Cache-Control: no-store` on success and on refusals
- each refusal in the table, plus the order: an invalid and blocked request is `invalid`; an
  oversized one from a blocked build is `too_large`; and so on
- someone else's id and a missing id give byte-identical answers; your own purged id gives `gone`
- `stale_base` payload matches the save's
- not refused: older schema_version, trashed document
- an owner over the snapshot cap still gets 201, and the oldest snapshots are trimmed
- it counts against and is limited by the shared saves-per-minute counter
- session CSRF: refused without a token, accepted with one
- a body bigger than Django's default cap but under the documents cap is accepted for a signed-in
  user
- a posted snapshot doesn't stop the day's first save from taking its `daily` snapshot, and
  neither does a `snapshot: "conflict"` save's snapshot. A `schema` or `daily` snapshot from
  today still suppresses it (see "Daily snapshots").

Test style follows CLAUDE.md (`django.test.TestCase`, plain `assert`), even where neighbours use
`assertEqual`.

## Open for the builder

- The validation's exact factoring (a `validate_snapshot` in `save.py` or a small new module),
  provided the field messages stay identical to the save's.
- Whether to generalize `snapshots.take` or add a sibling.

## Calls made by the designer (check these)

- `stale_base` is refused, mirroring the save, rather than storing the snapshot against an old
  version. The dashboard re-resolves against the new version.
- The rate limit is shared with saves (one counter), not separate.
- `too_large` for a request over the signed-in byte cap comes before `invalid`, because that cap
  is checked before the body is parsed. The `measure(body)` check stays in position 2.
- `base_version` can't be null here, so its message is `Must be an integer >= 0.`. Every other
  field uses the save's message.
- Missing and not-yours ids answer through `refuse_absent` (`not_found`), like the reads. The save
  answers `id_taken`, but that's because a save can create.

## Daily snapshots (decided with the user, 2026-11-02)

`reason_for` takes a `daily` snapshot on the day's first save unless the document already has a
snapshot from today. Today any reason counts. That breaks with this endpoint. Say "Use the other
version" posts the device's content at version 5 and the device then saves. The day's first save
sees the posted snapshot and skips `daily`, so the stored version 5 is never kept, and nothing is
kept for the rest of the day.

**The fix ships in this PR:** the daily check ignores `conflict` snapshots and counts only
`daily` and `schema` ones. There's no schema change.

Side effect, accepted by the user: after a "Keep mine" save, a later save that day also takes a
`daily` snapshot, of a newer version. That's at most one extra row (up to 1 MB) on days with a
conflict, which `trim` caps. It also gives the teacher a later restore point that day.

Rejected: a column marking posted snapshots. It's more precise but needs a migration. Also
rejected: matching on `version`. Every posted snapshot's version equals the stored version, so
it can't tell them apart.

## Non-goals

- No change to `PUT documents/<id>/` or the `snapshot` field.
- No new snapshot reason, refusal code, or setting.
- No restore endpoint (restoring is spec 4's).
- No SDK or dashboard changes here. sdk-js-1d and data-dashboard-ef make those.
