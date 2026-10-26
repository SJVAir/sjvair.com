# Workspace Hosting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the data dashboard during `invoke build` and serve it at `/workspace/*` from a bare Django template, beta-gated, with the contract's headers, CSP, and manifest.

**Architecture:** A shell script (modeled on `scripts/import-monitor-map.sh`) clones and builds data-dashboard into `dist/workspace/`, which `collectstatic` and the unchanged S3 sync pick up. A new `camp.apps.workspace` app holds the page view, manifest view, CSP builder (from a checked-in copy of the dashboard's `csp-hosts.json`), a dev-only `seed_beta_tester` command, and the template. The existing `beta_tools` gate is widened to `/workspace`.

**Tech Stack:** Django, django-waffle, bash, invoke, npm (Node 26 locally), podman-compose.

**Spec:** `docs/superpowers/specs/2026-10-26-workspace-hosting-design.md`. The authoritative contract is data-dashboard `docs/superpowers/specs/2026-10-26-foundations-5a-shipping-design.md` → "Hosting contract" (branch `foundations-5a-shipping`). Read both.

## Global Constraints

- Work in the worktree `/home/alex/workspace/sjvair/sjvair.com/.worktrees/workspace-hosting`, branch `feature/workspace-hosting`. PRs go into `develop`. Never merge to `main`, deploy, or touch Heroku.
- No AI attribution in commits or PR text.
- Run tests from the worktree (it has its own gitignored `.env`/`.env.test`): `podman-compose -p sjvaircom --profile test run --rm test pytest <path> -v`. Full suite: `... test pytest -n 4 --dist loadscope`. Never run two suites at once (shared test DB). Tee full suite output to a log.
- Tests: `django.test.TestCase`, pytest-style `assert`. Test settings have `BETA_TOOLS_GATE = False`; gate tests use `@override_settings(BETA_TOOLS_GATE=True)` and `cache.clear()` in `setUp`, as in `camp/utils/tests/test_beta_tools.py`. Django runs tests with `DEBUG=False`.
- Contract values (copy exactly): mount `<div id="SJVAirDataDashboard"></div>`; identity `json_script` id `sjvair-identity`, context variable `workspace_identity`; entry files `{% static 'workspace/app.css' %}` and `{% static 'workspace/app.js' %}` (module); manifest URL `/workspace/manifest.webmanifest`, content type `application/manifest+json`; `{static}` = `STATIC_URL + 'workspace/'`.
- Never put `api_token` or the phone number in the identity block.
- Do not edit or commit the main checkout's uncommitted `docker-compose.override.yml` (resticus fix); it is listed in `.git/info/exclude`.
- Do not change the S3 sync command, upload headers, or compression (deferred by the user).
- Node: the import must fail on a Node version outside data-dashboard's `engines` (`>=24 <27`).

## Review Focus

1. `/workspace?x=1` and deep paths with encoded characters (`/workspace/dashboards/a%20b`) → 200 with no redirect. (Task 2)
2. A `full_name` containing `</script>` → the identity block stays inside its `<script type="application/json">` (json_script escapes it); a user with `email=None` → `"email": null`. (Task 2)
3. `HEAD /workspace/` → 200; `POST /workspace/` → 405. (Task 2)
4. A signed-in user without the flag requesting `/workspace/manifest.webmanifest` → 404, same as the page. (Task 3)
5. The manifest file missing or not valid JSON → 404 with an error logged, never a 500; a later request after the file appears succeeds (misses aren't cached). (Task 5)

---

### Task 1: Import script, invoke task, Node pin

**Files:**
- Create: `scripts/import-data-dashboard.sh`
- Modify: `tasks.py` (new task beside `import_monitor_map`; call it from `build`)
- Modify: `package.json` (add `"engines": {"node": "26.x"}`)

**Interfaces:**
- Produces: `bash scripts/import-data-dashboard.sh [SOURCE] [REF]` (defaults `https://github.com/SJVAir/data-dashboard`, `main`); invoke task `import-data-dashboard --source --ref`; `build(ctx, mode='production', dashboard_source=..., dashboard_ref='main')`. Output: `dist/workspace/` with `app.js`, `app.css`, `version.json`, `assets/`.

- [ ] **Step 1: Write the script.** Behavior, in order:
  - `set -euo pipefail`; `DEST="$PWD/dist"`; a `mktemp -d` work dir removed by an `EXIT` trap.
  - `git clone --depth 1 --branch "$REF" "$SOURCE" "$WORK/data-dashboard"` (SOURCE may be a local repo path; that's how unpushed branches are tested; REF is a branch or tag).
  - Build with a scrubbed env: `env -u VITE_PROD_URL -u VITE_DEV_URL -u BUILD_ID -u GITHUB_SHA npm_config_engine_strict=true npm ci --include=dev`, then the same `env ... npm run build`. (`engine_strict` makes npm refuse the root package on a Node mismatch; verified 2026-10-26: `npm error notsup`.) `VITE_SENTRY_DSN`, `VITE_MAPTILER_KEY`, `VITE_NREL_KEY` pass through from the environment.
  - Fail with a clear message unless `dist/workspace/app.js` exists. Never copy `dist/index.html`.
  - `rm -rf "$DEST/workspace"`, `mkdir -p "$DEST"`, `cp -r dist/workspace "$DEST/workspace"`; echo the `buildId` from `version.json`.
- [ ] **Step 2: Add the invoke task** `import_data_dashboard(ctx, source='https://github.com/SJVAir/data-dashboard', ref='main')` running the script with `shlex.quote`d args; add `dashboard_source`/`dashboard_ref` params to `build()` and call it right after `import_monitor_map(ctx, mode)`.
- [ ] **Step 3: Pin Node** in `package.json`: `"engines": {"node": "26.x"}`.
- [ ] **Step 4: Verify against the dashboard's local branch** (the checkout isn't visible in the container, so mount it read-only):

  Run (from the worktree): `podman-compose -p sjvaircom --profile web run --rm -v /home/alex/workspace/sjvair/data-dashboard:/data-dashboard:ro,z web invoke import-data-dashboard --source /data-dashboard --ref foundations-5a-shipping`
  Expected: exit 0; `dist/workspace/{app.js,app.css,version.json}` and `dist/workspace/assets/` exist in the worktree; no `dist/workspace/index.html`; the printed buildId equals `git -C ../../../data-dashboard rev-parse foundations-5a-shipping`.
- [ ] **Step 5: Verify the failure paths.**
  - `--ref main` (no `dist/workspace/` on dashboard `main` today) → non-zero exit with the missing-output message, and an existing `dist/workspace/` is left untouched (the check runs before the `rm -rf`).
  - Node mismatch: in the container, `npm_config_engine_strict=true` with a temporary clone whose `engines` is edited to `<1` → `notsup` and non-zero exit. (A one-off check; don't commit a test fixture for it.)
- [ ] **Step 6: Commit** `feat(workspace): Import and build the data dashboard into dist/workspace`.

### Task 2: The `/workspace/*` page

**Files:**
- Create: `camp/apps/workspace/{__init__.py,apps.py,urls.py,views.py,identity.py}`, `camp/apps/workspace/templates/workspace/index.html`, `camp/apps/workspace/tests/{__init__.py,test_page.py}`
- Modify: `camp/settings/base.py` (INSTALLED_APPS `'camp.apps.workspace'`; settings below), `camp/urls.py` (include before the final catch-all)

**Interfaces:**
- Produces: `workspace_identity(user) -> dict` in `identity.py`; `WorkspacePage` view in `views.py`; URL patterns in `camp/apps/workspace/urls.py`, included in `camp/urls.py` as `path('', include('camp.apps.workspace.urls'))` placed before `re_path('^', views.PageTemplate...)`; settings `WORKSPACE_DIST_DIR = BASE_DIR.child('dist', 'workspace')`, `WORKSPACE_CSP_ENFORCE = bool(int(env('WORKSPACE_CSP_ENFORCE', int(DEBUG))))`, `WORKSPACE_CSP_REPORT_URI = env('WORKSPACE_CSP_REPORT_URI', '')` (the CSP settings are used in Task 4; define them here, after `DEBUG`). Check `camp/settings/heroku.py` doesn't force `DEBUG` on.
- Route: `re_path(r'^workspace(?:/.*)?$', WorkspacePage.as_view(), name='workspace')`.

- [ ] **Step 1: Write failing tests** in `test_page.py` (`WorkspacePageTests`, gate off via test settings):
  - `test_both_slash_forms_and_deep_paths_render`: for `/workspace`, `/workspace/`, `/workspace/dashboards/abc`, `/workspace/dashboards/a%20b`, `/workspace?x=1` → `status_code == 200`, no `Location` header.
  - `test_workspacefoo_is_not_the_workspace`: `resolve('/workspacefoo').func.view_class is not WorkspacePage` (and `/workspace` resolves to it).
  - `test_template_is_bare`: body contains `<div id="SJVAirDataDashboard"></div>`, `id="sjvair-identity"`, `<script type="module" src="/static/workspace/app.js">`, `href="/static/workspace/app.css"`, `href="/workspace/manifest.webmanifest"`, `<title>SJVAir Dashboard</title>`, `favicon.ico`; does not contain `googletagmanager`, `gtag`, `bulma`, `navbar`; every `<script` tag is either `type="module"` with `src` or `type="application/json"`.
  - `test_headers`: `'no-store' in response['Cache-Control']`; `response['X-Frame-Options'] == 'DENY'`; `'csrftoken' in response.cookies` on a fresh client; no `X-Robots-Tag` on `/workspace/`.
  - `test_shared_pages_are_noindex`: `/workspace/shared` and `/workspace/shared/abc` → `X-Robots-Tag: noindex`; `/workspace/sharedx` → none.
  - `test_methods`: `HEAD` → 200; `POST` (with `enforce_csrf_checks=False` client) → 405.
  - `test_identity_anonymous`: parsed `sjvair-identity` JSON `== {"v": 1, "user": None}`.
  - `test_identity_signed_in`: user with `full_name='Ana </script> B'`, `email=None`, `phone_verified=True` → `{"v": 1, "user": {"id": str(user.pk), "name": "Ana </script> B", "email": None, "emailVerified": False, "phoneVerified": True}}`; the raw HTML contains no `api_token` value and no phone digits, and contains `</script>` (json_script escaped the name).
  Parse the block with a regex on `<script id="sjvair-identity" type="application/json">(.*?)</script>` + `json.loads`.
- [ ] **Step 2: Run** `podman-compose -p sjvaircom --profile test run --rm test pytest camp/apps/workspace/tests/test_page.py -v` → fails (no app).
- [ ] **Step 3: Implement.** `WorkspacePage`: a `TemplateView` with `http_method_names = ['get', 'head', 'options']`, `method_decorator([ensure_csrf_cookie, never_cache], name='dispatch')`, template `workspace/index.html`, context `workspace_identity`; sets `X-Robots-Tag: noindex` when the path is `/workspace/shared` or starts with `/workspace/shared/`. Template exactly as contract section 3 (with `{% load static %}`). `workspace_identity` returns the contract shape; `id` is `str(user.pk)`, `email` is `user.email or None`, `emailVerified` always `False`.
- [ ] **Step 4: Run** the tests → pass. Also run `camp/utils/tests/` → pass (catch-all unaffected).
- [ ] **Step 5: Commit** `feat(workspace): Serve the dashboard page at /workspace`.

### Task 3: Beta gate, nav link, flag note

**Files:**
- Modify: `camp/utils/beta.py`, `camp/utils/middleware.py`, `camp/templates/page.html` (Data Tools dropdown and the footer's beta list), `camp/settings/base.py` (the BETA_TOOLS_GATE comment)
- Create: `camp/apps/workspace/migrations/{__init__.py,0001_beta_tools_flag_note.py}`, `camp/apps/workspace/tests/test_gate.py`

**Interfaces:**
- Produces: `is_beta_path(path: str) -> bool` in `camp/utils/beta.py`: true for paths starting with `/tools/`, for `/workspace`, and for paths starting with `/workspace/`. Replaces `BETA_TOOLS_PREFIX` (only the middleware uses it).

- [ ] **Step 1: Write failing tests** in `test_gate.py` (`@override_settings(BETA_TOOLS_GATE=True)`, user helper as in `test_beta_tools.py`):
  - `test_anonymous_gets_404`: `/workspace`, `/workspace/`, `/workspace/shared/x`, `/workspace/manifest.webmanifest` → 404.
  - `test_signed_in_without_flag_gets_404` for `/workspace/` and the manifest URL.
  - `test_beta_tester_gets_the_page`: group member → `/workspace/` 200.
  - `test_staff_get_the_page`.
  - `test_workspacefoo_is_not_gated`: `is_beta_path('/workspacefoo') is False`, `is_beta_path('/workspace') is True`, `is_beta_path('/tools/x') is True`.
  - `test_nav_link`: beta tester's `/about/` HTML has `href="/workspace/"` and `html.count('My Dashboard') == 2`; anonymous has 0.
  - `test_flag_note_mentions_workspace`: `'/workspace/' in Flag.objects.get(name='beta_tools').note`.
  - Existing `camp/utils/tests/test_beta_tools.py` must still pass unchanged.
- [ ] **Step 2: Run** → fails.
- [ ] **Step 3: Implement** `is_beta_path`; the middleware uses it. Add "My Dashboard" (with the same `Beta` tag and a Font Awesome icon from the site's kit) after the emissions explorer in both the navbar dropdown and the footer beta list. Data migration (depends on `('pesticides', '0002_beta_tools_flag')`) sets the note to: `Gates the data tools under /tools/ (the pesticides and emissions explorers), the dashboard under /workspace/, and their nav links; everyone else gets a 404. Add users to the "Beta testers" group to let them in; staff and superusers are on. Set Everyone to Yes to launch.` Reverse restores the old note (`FLAG_NOTE` in `pesticides/migrations/0002_beta_tools_flag.py`). Update the `BETA_TOOLS_GATE` comment in `base.py` to mention `/workspace/`.
- [ ] **Step 4: Run** `test_gate.py` and `camp/utils/tests/test_beta_tools.py` → pass.
- [ ] **Step 5: Commit** `feat(workspace): Gate /workspace behind beta_tools and link it from Data Tools`.

### Task 4: Content Security Policy

**Files:**
- Create: `camp/apps/workspace/csp-hosts.json`, `camp/apps/workspace/csp.py`, `camp/apps/workspace/tests/test_csp.py`
- Modify: `camp/apps/workspace/views.py` (set the header on `WorkspacePage` responses)

**Interfaces:**
- Produces: `build_policy(static_url: str, report_uri: str = '') -> str` (cached with `functools.lru_cache`); `policy_header_name(enforce: bool) -> str` returning `'Content-Security-Policy'` or `'Content-Security-Policy-Report-Only'`.

- [ ] **Step 1: Write `csp-hosts.json`** from contract section 5's table, in table order, e.g. `{"default-src": ["'none'"], "script-src": ["'self'", "{static}"], ..., "form-action": ["'none'"]}`. If data-dashboard's `csp-hosts.json` exists on `foundations-5a-shipping` by now (its Task 6), copy it byte for byte instead and note the commit in the commit message.
- [ ] **Step 2: Write failing tests** in `test_csp.py`:
  - `test_policy_matches_the_host_list`: `build_policy('https://bucket.example/static/')` parsed (`;`-split, whitespace-split) equals the JSON with `{static}` → `https://bucket.example/static/workspace/`, same directive order.
  - `test_bare_static_path_is_dropped`: `build_policy('/static/')` has no `/static/` and no `{static}`; `script-src` is exactly `'self'`; `font-src` is `'self'`.
  - `test_report_uri_only_when_set`: with `'https://r.example/x'` the policy ends with `report-uri https://r.example/x`; with `''` there's no `report-uri`.
  - `test_view_enforces_when_set` / `test_view_reports_only_by_default_when_off`: `override_settings(WORKSPACE_CSP_ENFORCE=True/False)` → `/workspace/` carries the matching header name and not the other.
  - `test_no_csp_outside_workspace`: `/about/` has neither header.
- [ ] **Step 3: Run** → fails.
- [ ] **Step 4: Implement.** `{static}` is substituted only when `static_url` starts with `http://` or `https://`; otherwise that source is dropped. Directives serialize as `name src src` joined by `; `. The view reads `settings.STATIC_URL`, `WORKSPACE_CSP_REPORT_URI`, and `WORKSPACE_CSP_ENFORCE` per request (`build_policy` caches the string).
- [ ] **Step 5: Run** → pass. **Commit** `feat(workspace): Send the dashboard's CSP on /workspace`.

### Task 5: Manifest

**Files:**
- Create: `camp/apps/workspace/manifest.py`, `camp/apps/workspace/tests/test_manifest.py`
- Modify: `camp/apps/workspace/urls.py` (manifest route listed **before** the page route), `views.py`

**Interfaces:**
- Produces: `load_manifest(path: str, static_base: str) -> dict | None` (successful loads cached per `(path, static_base)` in a module dict; misses and invalid JSON return `None`, logged with `logger.error`, not cached); view `WorkspaceManifest` at `path('workspace/manifest.webmanifest', ..., name='workspace-manifest')`, `never_cache`, GET/HEAD only.

- [ ] **Step 1: Write failing tests** (use a temp dir and `override_settings(WORKSPACE_DIST_DIR=tmp)`; clear the module cache in `setUp`):
  - `test_serves_manifest_with_static_icon_urls`: a manifest with icons `assets/icon-192-abc.png` and `https://cdn.example/x.png` → 200, `Content-Type` `application/manifest+json`, first icon `src == '/static/workspace/assets/icon-192-abc.png'`, the absolute one unchanged, other keys (`start_url`, `scope`) untouched.
  - `test_missing_manifest_is_404` and `test_invalid_json_is_404` (assert logged with `assertLogs`).
  - `test_miss_is_not_cached`: 404, then write the file, then 200.
  - `test_not_shadowed_by_page_route`: `resolve('/workspace/manifest.webmanifest').url_name == 'workspace-manifest'`.
- [ ] **Step 2: Run** → fails. **Step 3: Implement** (`static_base` is `static('workspace/')`; rewrite only icon `src` values with no scheme and no leading `/`). **Step 4: Run** → pass.
- [ ] **Step 5: Commit** `feat(workspace): Serve the web app manifest from Django`.

### Task 6: `seed_beta_tester` command

**Files:**
- Create: `camp/apps/workspace/management/__init__.py`, `management/commands/__init__.py`, `management/commands/seed_beta_tester.py`, `camp/apps/workspace/tests/test_seed_beta_tester.py`

**Interfaces:**
- Produces: `manage.py seed_beta_tester [--identifier X] [--password Y]`, defaulting to env `WORKSPACE_E2E_IDENTIFIER` / `WORKSPACE_E2E_PASSWORD`. The dashboard's embedding suite signs in with these at `/account/login/` (fields `identifier`, `password`).

- [ ] **Step 1: Write failing tests:**
  - `test_refuses_without_debug`: default test settings (`DEBUG=False`) → `CommandError`, no user created.
  - `test_creates_non_staff_beta_tester_by_email` (`override_settings(DEBUG=True)`): identifier `e2e@example.com` → one user, `is_staff is False`, `is_superuser is False`, in group `Beta testers`, password checks.
  - `test_creates_by_phone`: identifier `559-555-0198` → user with that phone, `email is None`.
  - `test_is_idempotent`: run twice with a new password → one user, new password works, still non-staff.
  - `test_missing_values_error`: no identifier → `CommandError`.
  - `test_seeded_user_can_open_workspace` (`BETA_TOOLS_GATE=True`, `DEBUG=True`): seed, `client.post('/account/login/', {'identifier': ..., 'password': ...})`, then `/workspace/` → 200.
- [ ] **Step 2: Run** → fails.
- [ ] **Step 3: Implement.** Email identifiers (contain `@`) set `email` and the fixed fictional phone `+15595550199` (the model requires a unique phone); phone identifiers set `phone` and leave `email` empty. `full_name='Workspace E2E'`, `is_active=True`, and `is_staff`/`is_superuser` forced `False` on every run. Check that `User.save` / signals send no SMS on create (Twilio is unconfigured locally; if a signal would send, set what's needed to skip it and say so).
- [ ] **Step 4: Run** → pass. **Commit** `feat(workspace): Add a dev-only seed_beta_tester command for browser tests`.

### Task 7: Docs, full suite, and the embedding check on the local stack

**Files:**
- Modify: `CLAUDE.md` (new section "Data Dashboard (`/workspace/`)": the import command for a branch or local checkout, `seed_beta_tester` and its env vars, `WORKSPACE_CSP_ENFORCE` / `WORKSPACE_CSP_REPORT_URI`, the beta gate, and the account work list from the spec's "What the user does" section, with the note that CSP and Sentry host changes come from data-dashboard's `csp-hosts.json`)

- [ ] **Step 1: Write the CLAUDE.md section.** Commit `docs: Data dashboard hosting notes`.
- [ ] **Step 2: Full suite** from the worktree, teed to a log in the session scratchpad. Expected: all pass (baseline 3753 on develop `9e3a8496`, plus this branch's tests).
- [ ] **Step 3: Serve the worktree on the local stack — ask the user first** (it replaces the running web container). Copy the main checkout's `docker-compose.override.yml` into the worktree (it's covered by the shared `.git/info/exclude`; confirm with `git status`), make sure `dist/` has the site's built CSS (`invoke styles` in the container, or copy the main checkout's `dist/css`), then from the worktree `podman-compose -p sjvaircom --profile web up -d web`. Restore afterwards with the same command from the main checkout.
- [ ] **Step 4: Seed** `WORKSPACE_E2E_IDENTIFIER` / `WORKSPACE_E2E_PASSWORD` into the worktree's `.env` (local values) and run `seed_beta_tester` in the web container.
- [ ] **Step 5: Run data-dashboard's embedding suite** against `http://localhost:8000` (ask the spec 5 session `data-dashboard-c9` for the exact command and env if it isn't in that repo's docs). Expected: all checks pass with the CSP enforced (`WORKSPACE_CSP_ENFORCE` defaults on under `DEBUG`). Known gaps until the dashboard's Tasks 7/9: the manifest and notices files are absent, so the manifest check fails with 404; record it, don't work around it.
- [ ] **Step 6: Manual browser check** (Chrome, signed in as the seeded tester): `/workspace` and `/workspace/` load without a redirect; a deep link loads; "My Dashboard" shows in Data Tools; no CSP errors in the console; signed out or as a non-beta user `/workspace/` is 404.
- [ ] **Step 7: Report** results to the user and to `data-dashboard-c9`. Opening a PR into `develop` needs the user's go-ahead.

## Follow-ups this plan expects (from the spec 5 session)

- The dashboard's Task 6 adds `csp-hosts.json`: re-copy it byte for byte if Task 4 ran first, and re-run `test_csp.py`.
- The dashboard's Tasks 7 and 9 add `THIRD-PARTY-NOTICES.txt` and `manifest.webmanifest`: re-import and re-run the embedding suite's manifest check.
