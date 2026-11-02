# Keep Given Content as a Document Snapshot: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `POST /api/2.0/documents/<id>/snapshots/`, which stores content the client sends as a
`conflict` snapshot of an owned document without touching the document. Also stop `conflict`
snapshots from suppressing the day's `daily` snapshot.

**Architecture:** Validation lives in `camp/api/v2/documents/save.py` and reuses the save's
field checks. The request-level checks (blocked build, account, rate limit) move out of
`apply_save` into a shared `check_caller`. The new storing helper lives in
`camp/apps/documents/snapshots.py`. `DocumentSnapshotList` gains `post`. The signed-in request cap
that `PUT` uses is generalized into a mixin so `POST` gets it too.

**Tech Stack:** Django 5.2, django-resticus, PostgreSQL, pytest + `django.test.TestCase`.

**Spec:** `docs/superpowers/specs/2026-11-02-document-snapshot-post-design.md`

## Global Constraints

- Wire shape exactly as in the spec's "Wire shape" section. The 201 data keys are exactly
  `{'id', 'version', 'schema_version', 'reason', 'created_at'}`.
- Refusal codes and order exactly as in the spec's table. No new codes, reasons, settings, or
  migrations.
- `PUT documents/<id>/` behaves exactly as before. Every existing test passes unchanged.
- `Cache-Control: no-store` on every answer. Someone else's id answers byte-identically to a
  missing one. `DocumentSnapshot` stays unregistered in the admin.
- Tests: `django.test.TestCase` with plain `assert`, per CLAUDE.md.
- Commands run under `podman-compose`, not `docker compose`.
- No AI attribution in commits or the PR.

## Review Focus

1. **A concurrent save between the version check and the insert.** The row lock must be held
   across both. Task 3 runs them in one `transaction.atomic()` with `select_for_update`.
   Concurrency isn't unit-tested; review it by reading.
2. **The `stale_base` payload needs the full document, body included, while the happy path
   defers the body.** Expected: `stale_base` carries the body; success never reads it. Pinned
   in Task 3 (`test_stale_base_payload_matches_save`, `test_success_never_reads_document_body`).
3. **`name` absent vs `name: null`.** Absent → `invalid` (required); null → accepted. Pinned in
   Task 3 (`test_missing_field_is_invalid`, `test_null_name_accepted`).
4. **`base_version: true`.** A bool isn't an int → `invalid`. Pinned in Task 3
   (`test_base_version_must_be_int`).
5. **A non-object request (a JSON list or string).** → `invalid` with `fields.request`, as the
   save does. Pinned in Task 3 (`test_non_object_request_is_invalid`).

---

### Task 1: The daily check ignores `conflict` snapshots

**Files:**
- Modify: `camp/apps/documents/snapshots.py` (`reason_for`)
- Test: `camp/apps/documents/tests/test_snapshots.py` (`SnapshotTests`)

- [ ] **Step 1: Write the failing tests** in `SnapshotTests`:

```python
def test_conflict_snapshot_does_not_suppress_daily(self):
    self.put()
    self.put(base_version=1, snapshot='conflict')  # first save of the day: conflict
    self.put(base_version=2)                       # still takes the daily
    reasons = list(DocumentSnapshot.objects.order_by('pk').values_list('reason', flat=True))
    assert reasons == ['conflict', 'daily']
    assert DocumentSnapshot.objects.get(reason='daily').version == 2

def test_schema_snapshot_still_suppresses_daily(self):
    self.put()
    self.put(base_version=1, schema_version=2)
    self.put(base_version=2, schema_version=2)
    assert list(DocumentSnapshot.objects.values_list('reason', flat=True)) == ['schema']
```

- [ ] **Step 2: Run them.** `podman-compose run --rm test pytest camp/apps/documents/tests/test_snapshots.py -v`
  Expected: `test_conflict_snapshot_does_not_suppress_daily` FAILS (only `['conflict']`); the
  schema test passes.

- [ ] **Step 3: Implement.** In `reason_for`, the today-exists query excludes
  `reason=DocumentSnapshot.Reason.CONFLICT`. Update the docstring to say which snapshots count.

- [ ] **Step 4: Run the file again.** Expected: all PASS, existing tests included.

- [ ] **Step 5: Commit** `git commit -m "Don't let conflict snapshots stand in for the daily one"`

### Task 2: A helper that stores given content as a snapshot

**Files:**
- Modify: `camp/apps/documents/snapshots.py`
- Test: `camp/apps/documents/tests/test_snapshots.py` (new `KeepTests(TestCase)`)

**Interfaces:**
- Produces: `snapshots.keep(doc, *, version: int, schema_version: int, name: str | None, body: dict, size: int) -> DocumentSnapshot`.
  Creates a `conflict` snapshot owned by `doc.owner_id` with exactly those values, then calls
  `trim(doc.owner_id)`. Make `take` call it (`version=doc.version` and so on, with its own
  reason) so the two can't drift: give `keep` a keyword `reason=DocumentSnapshot.Reason.CONFLICT`.

- [ ] **Step 1: Write the failing tests.** Seed a `SavedDocument` directly (as `seed` in
  `test_snapshots_api.py` does: version 2, body `{'a': 1}`).

```python
def test_keep_stores_given_content_not_stored(self):
    made = snapshots.keep(self.doc, version=2, schema_version=1, name='Mine', body={'b': 2}, size=7)
    made.refresh_from_db()
    assert (made.reason, made.version, made.schema_version, made.name, made.body, made.size,
            made.owner_id) == ('conflict', 2, 1, 'Mine', {'b': 2}, 7, self.alice.pk)
    self.doc.refresh_from_db()
    assert (self.doc.version, self.doc.body) == (2, {'a': 1})

@override_settings(DOCUMENTS_MAX_SNAPSHOT_STORAGE=20)
def test_keep_trims_oldest(self):
    first = snapshots.keep(self.doc, version=2, schema_version=1, name=None, body={}, size=10)
    snapshots.keep(self.doc, version=2, schema_version=1, name=None, body={}, size=10)
    snapshots.keep(self.doc, version=2, schema_version=1, name=None, body={}, size=10)
    assert not DocumentSnapshot.objects.filter(pk=first.pk).exists()
    assert DocumentSnapshot.objects.count() == 2
```

- [ ] **Step 2: Run them.** Expected: FAIL (`keep` doesn't exist).
- [ ] **Step 3: Implement `keep`** and route `take` through it.
- [ ] **Step 4: Run** `pytest camp/apps/documents/tests/test_snapshots.py -v`. Expected: all PASS.
- [ ] **Step 5: Commit** `git commit -m "Add snapshots.keep for storing given content"`

### Task 3: `POST documents/<id>/snapshots/`

**Files:**
- Modify: `camp/api/v2/documents/save.py`. Add `SNAPSHOT_FIELDS` and `validate_snapshot`,
  extract `check_caller`, and add `keep_snapshot`.
- Modify: `camp/api/v2/documents/endpoints.py`. Add `LargeBodyMixin`, and `post` on
  `DocumentSnapshotList`.
- Modify: `camp/api/v2/documents/tests/helpers.py`. Add `post_snapshot`.
- Test: `camp/api/v2/documents/tests/test_snapshots_api.py` (new `SnapshotPostTests`), and
  `test_csrf.py`.

**Interfaces:**
- Consumes: `snapshots.keep` (Task 2).
- Produces:
  - `save.SNAPSHOT_FIELDS = ('base_version', 'schema_version', 'name', 'body', 'account_id', 'build_id')`
  - `save.validate_snapshot(data, id) -> (cleaned: dict, errors: dict)`. Same shape as
    `validate`: the id check, the non-dict check, and missing → `REQUIRED`. Each field uses
    `check_field`, except `base_version`, where null or non-int (bools included) or <0 gives
    `'Must be an integer >= 0.'`.
  - `save.check_caller(user, cleaned) -> HttpResponse | None`: build_blocked, then
    account_mismatch, then rate_limited, moved verbatim out of `apply_save`, which now calls it.
  - `save.keep_snapshot(request, id, cleaned) -> HttpResponse`. In order: the size check
    (`measure(body) > DOCUMENTS_MAX_BODY` → `too_large()`), `check_caller`, then inside
    `transaction.atomic()` the row
    `SavedDocument.objects.select_for_update().defer('body').filter(pk=id, owner=request.user).first()`.
    None → `refuse_absent(request, id)`. Version mismatch → `stale(doc, base_version)`; the
    body loads on access, which is fine there. Otherwise `snapshots.keep(...)` with
    `version=base_version` and `size=measure(body)`, then `http.Http201({'data': {id, version, schema_version, reason, created_at}})`.
    `refuse_absent` lives in `endpoints.py`; move it and `not_found` to `responses.py` and
    import them in both, rather than importing `endpoints` from `save`.
  - `endpoints.LargeBodyMixin` with `large_body_methods = ()`. Its `dispatch` applies
    `read_save_body` when `request.method in large_body_methods and is_session_user(request)`.
    `DocumentDetail` uses it with `('PUT',)`, replacing its own `dispatch`. `DocumentSnapshotList`
    uses it with `('POST',)`. MRO: `NoStoreMixin, LargeBodyMixin, Endpoint`.
  - `helpers.post_snapshot(client, id, **overrides)`. Defaults: `base_version=1`,
    `schema_version=1`, `name='Mine'`, `body=body(1)`, the client's `account_id`,
    `build_id='test-build'`. Supports `MISSING` like `save`.

- [ ] **Step 1: Write the failing tests** in `SnapshotPostTests`. `setUp`: `cache.clear()`, alice
  signed in, bob, and a seeded doc `'d'` at version 1 (create it through `save()`, so that the
  version, `updated_at` and change log are real). Each test asserts `Cache-Control == 'no-store'`
  where it reads a response.

  | Test | Asserts |
  |---|---|
  | `test_keeps_given_content_as_conflict` | 201, data keys exactly the five, `reason=='conflict'`, `version==1`; stored row name `'Mine'`, body `body(1)`, size `measure(body(1))` |
  | `test_document_untouched` | the doc's version, `updated_at`, body, and `DocumentChange` count are the same before and after |
  | `test_listed_in_snapshot_list` | the GET list's first row `id` equals the POST's |
  | `test_missing_field_is_invalid` | `name=MISSING` → 400 `invalid`, `data.fields.name == ['This field is required.']` |
  | `test_null_name_accepted` | `name=None` → 201 |
  | `test_base_version_must_be_int` | each of `None`, `True`, `-1`, `'1'` → 400 with `fields.base_version == ['Must be an integer >= 0.']` |
  | `test_non_object_request_is_invalid` | a raw JSON list body → 400, `fields.request` present |
  | `test_body_must_be_json_object` | `body=[1]` → 400, `fields.body` |
  | `test_too_large` | `@override_settings(DOCUMENTS_MAX_BODY=10)` → 413 `too_large`; no snapshot stored |
  | `test_invalid_before_too_large_before_blocked` | an oversized body plus a bad `name` → `invalid`; a blocked build plus an oversized body → `too_large` |
  | `test_build_blocked` | `BlockedBuild(build_id='test-build')` → 409 `build_blocked` |
  | `test_account_mismatch` | `account_id='nope'` → 403, `data.signed_in_as` is alice's id |
  | `test_rate_limit_shared_with_saves` | `@override_settings(DOCUMENTS_SAVES_PER_MINUTE=2)` with a frozen clock (copy `frozen_clock` from `test_limits.py` into `helpers.py` and import it in both): inside the test a `save()` of a new id `'e'` is 1, one POST is 2, the next POST is 429 `rate_limited` (proving one counter) |
  | `test_not_found_and_not_yours_identical` | a missing id and bob's doc id give the same status (404), and identical `content` |
  | `test_own_purged_is_gone` | a `PurgedDocument(owner=alice)` → 410 `gone` |
  | `test_stale_base_payload_matches_save` | `base_version=0` → 409 `stale_base`, and `data` equals that of a `save()` sent with `base_version=0` |
  | `test_older_schema_and_trashed_accepted` | the doc at schema 2 and trashed (save it so), POST `schema_version=1` → 201 |
  | `test_over_snapshot_cap_still_201_and_trims` | `@override_settings(DOCUMENTS_MAX_SNAPSHOT_STORAGE=measure(body(1)) * 2)`, three POSTs all 201, two rows left, the oldest gone |
  | `test_success_never_reads_document_body` | `CaptureQueriesContext`, then `body_queries(captured)` holds no query reading `documents_saveddocument.body` |
  | `test_large_session_body_accepted` | `@override_settings(DATA_UPLOAD_MAX_MEMORY_SIZE=1000)`, `body=padded_body(2000)` (move `padded_body` from `test_save.py` into `helpers.py`) → 201 |
  | `test_posted_snapshot_does_not_suppress_daily` | after the POST, `save(base_version=1)` → the snapshots are `['conflict', 'daily']`, and the daily's version is 1 |
  | `test_signed_out_401` | `Client()` → 401 |

  In `test_csrf.py`, add `test_session_snapshot_post_without_csrf_refused` (403) and
  `..._with_csrf_accepted` (201, with the existing token recipe), seeding a doc first.

- [ ] **Step 2: Run them.** `podman-compose run --rm test pytest camp/api/v2/documents/tests/test_snapshots_api.py camp/api/v2/documents/tests/test_csrf.py -v`
  Expected: the new tests FAIL (405 or 404, since POST isn't routed).
- [ ] **Step 3: Implement** the Interfaces above.
- [ ] **Step 4: Run the documents tests.** `podman-compose run --rm test pytest camp/api/v2/documents camp/apps/documents -v`
  Expected: all PASS, every existing save test included (the `check_caller` extraction must not
  change `PUT`).
- [ ] **Step 5: Commit** `git commit -m "Add POST documents/<id>/snapshots/ to keep given content"`

### Task 4: Full suite and PR

- [ ] **Step 1:** `podman-compose run --rm test pytest -n 4 --dist loadscope 2>&1 | tee scratchpad/full-suite.log`
  Expected: 0 failures (check the log's last line).
- [ ] **Step 2:** Manual check against the podman stack with the `WORKSPACE_E2E_*` account. POST
  a snapshot to an owned dashboard → 201, and it appears in GET `snapshots/`. Record the result
  for the PR.
- [ ] **Step 3:** Push `feature/document-snapshot-post` and open a PR **into `develop`**. The
  body covers the wire shape, the daily-check change and its accepted side effect, and the
  manual-check result, with no AI attribution. Merging waits for the user's explicit yes.
- [ ] **Step 4:** After the merge (and only then), message `data-dashboard-ef` and `sdk-js-1d`
  (look the names up with `ListAgents`).
