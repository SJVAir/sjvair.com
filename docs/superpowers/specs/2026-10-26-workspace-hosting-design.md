# Hosting the data dashboard at `/workspace/` — design

Date: 2026-10-26. Branch: `feature/workspace-hosting` from `develop` (PRs into `develop`).

## Intent

SJVAir's new data dashboard (`SJVAir/data-dashboard`, a plain Vite + Svelte SPA) will be
served from sjvair.com at `www.sjvair.com/workspace/`, on the same origin as the site so
that signed-in users are signed in to the dashboard with the session cookie. This track is
the sjvair.com side: build the dashboard during the deploy, embed it in a Django page, and
serve that page safely.

Shipping should look like monitor-map's shipping as closely as possible: clone, build,
copy into `dist/`, `collectstatic`, and the existing S3 sync. Problems monitor-map already
has (no compression or cache headers on S3, upload order, the sync ignoring errors) are
accepted for both and solved together later.

Neither project ships until it is finished. This work merges into `develop` and stays
there. `develop` is merged into `main` only once data-dashboard Release 1 is done. Until
then everything is built and verified on the local podman stack. Production, Heroku, and
merges to `main` are out of scope for this track.

## Goals

1. An import script that builds data-dashboard and copies its output into `dist/`, run by
   `invoke build` on every Heroku deploy (like monitor-map), with a local mode for testing
   a dashboard branch or a local checkout.
2. A `/workspace/*` page in a dedicated template that does not extend `base.html` /
   `page.html`, embedding the built app and the user's identity block.
3. Correct response behavior: CSRF cookie always set, no trailing-slash redirect, page
   not cached, not frameable, `noindex` on shared pages, and a CSP.
4. The web app manifest served by Django.
5. A private preview for beta testers on production (when it eventually ships), behind the
   existing `beta_tools` flag, with a "My Dashboard" link in the Data Tools menu.

## Non-goals and deferrals

- **Compression, cache headers, ordered upload passes, a post-deploy header check, and
  making the S3 sync fail the release on error.** Deferred by the user (2026-10-26), to be
  solved together with monitor-map later. The dashboard is uploaded by today's
  `sync_staticfiles_s3`, unchanged, with no exclusion for its folder. data-dashboard
  records the deferral in its `DEFERRED.md` and handles stale fixed-name files in the
  app (its reload button re-fetches `app.js` / `app.css` with `cache: "reload"` first).
- No staging Heroku app, and no change to the S3 bucket's CORS rule (it already allows
  `https://www.sjvair.com`, which monitor-map's module script relies on).
- No server-backed documents, share-link API, sign-in flow, or email-only accounts: those
  are other tracks. This page only serves the app; a deleted or taken-down share is
  answered by the API, not the view.
- No version pinning of the dashboard: the deploy builds data-dashboard `main`.
- No production verification, Heroku config changes, or merges to `main` by the builder.

## Anti-goals

- The workspace page must never load site chrome or third-party tags: no Google Tag
  Manager/Analytics, Bulma, Raven, Translate widget, or inline scripts.
- The identity block must never contain `api_token` or the phone number.
- Nothing about `/workspace/` may become visible to non-beta users before go-live.
- Don't decide anything in the hosting contract (below) on this side.

## Coordination: the hosting contract

The data-dashboard spec 5 session owns the contract between the repos and records it in
its spec 5 design's "Hosting contract" section. Any change goes back to that session
(SendMessage `data-dashboard-c9`, or the user relays). The values below were agreed with it
on 2026-10-26 and are provisional until the user reviews that section; re-check them
against it before planning, and take the contract as authoritative where they differ.

- **Build:** `npm ci && npm run build` in the dashboard checkout. Output is
  `dist/workspace/`, copied to sjvair.com `dist/workspace/` (so it collects to
  `static/workspace/`). One build works everywhere (files find each other relative to the
  entry module; the API uses the page origin), so there is no separate local build mode.
  `engines` is `"node": ">=24 <27"`. The sjvair.com image (Node 26) stays as is.
- **Build env:** `VITE_SENTRY_DSN` (unset turns error reporting off), `VITE_MAPTILER_KEY`
  and `VITE_NREL_KEY` (used from Release 1 step 5; harmless before). Never set
  `VITE_PROD_URL` or `VITE_DEV_URL`. The build stamps its own release from `BUILD_ID`,
  then `GITHUB_SHA`, then `git rev-parse HEAD`, and fails if none works. The import must
  not pass Heroku's `SOURCE_VERSION` (that is sjvair.com's commit); the fresh clone's
  `.git` is enough.
- **Output layout:** top-level fixed-name files `app.js`, `app.css`, `version.json`,
  `manifest.webmanifest`, `THIRD-PARTY-NOTICES.txt`; everything under `assets/` is
  content-hashed. Plain files only (no `.br`/`.gz`), no source maps.
- **Entry tags:** `{% static 'workspace/app.css' %}` and a module script for
  `{% static 'workspace/app.js' %}`. No inline script, no `__cdnUrl` helper.
- **Identity block:** `{{ identity|json_script:"sjvair-identity" }}`.
  Anonymous: `{"v": 1, "user": null}`. Signed in:
  `{"v": 1, "user": {"id": "<user.pk as string>", "name": "<full_name>", "email": "<email or null>", "emailVerified": false, "phoneVerified": <bool>}}`.
  `emailVerified` stays `false` until the email-only accounts track adds the field.
- **Manifest:** Django reads `dist/workspace/manifest.webmanifest` from the slug and
  serves it at `/workspace/manifest.webmanifest` as `application/manifest+json`, rewriting
  each icon's relative `src` (e.g. `assets/icon-192-<hash>.png`) to
  `static('workspace/') + src`. Icons stay on S3. The catch-all must not shadow this URL.
- **`version.json`:** fetched by the app from the static origin with `no-store`. Nothing
  for sjvair.com to do (existing CORS rule).
- **CSP host list:** `csp-hosts.json` at data-dashboard's root, a JSON object mapping each
  directive to a list of sources, with `{static}` standing for `STATIC_URL + 'workspace/'`.
  sjvair.com keeps a copy beside the view; a test checks that the header the view builds
  matches that copy. When the dashboard's file changes, its PR says so and the matching
  sjvair.com change goes with it.
- **CSRF bootstrap:** the view is decorated with `ensure_csrf_cookie`.

## The design

### 1. Import script (`scripts/import-data-dashboard.sh`) and invoke task

Modeled on `scripts/import-monitor-map.sh`:

- Clone `https://github.com/SJVAir/data-dashboard` (anonymous, the repo is public) into a
  temp dir, `npm ci`, `npm run build`, copy `dist/workspace` to `$PWD/dist/workspace`
  (removing any previous copy first), and clean up the temp dir on exit.
- **Sources:** default is `main` (what the Heroku deploy uses). Local mode takes either a
  branch/ref (e.g. `foundations`) to clone, or a path to a local checkout to build in
  place of cloning. The user asked for "a local mode for testing a branch"; the exact
  CLI shape is the builder's call, but the deploy path must stay a plain `main` build.
- **Fail early, fail loudly:** `set -euo pipefail`; check `node --version` against the
  contract's range (`>=24 <27`) before building; fail if the build doesn't produce
  `dist/workspace/` (no skip mode: until data-dashboard `main` has the app, sjvair.com
  `main` doesn't get this work, so a missing build is always an error).
- **Env for the build:** pass through `VITE_SENTRY_DSN`, `VITE_MAPTILER_KEY`,
  `VITE_NREL_KEY` from the environment (Heroku config vars at deploy; `.env` locally).
  Explicitly unset `VITE_PROD_URL` / `VITE_DEV_URL` for the build in case they exist.
- **invoke:** an `import_data_dashboard(ctx, mode/source)` task beside
  `import_monitor_map`, called from `build()` next to it.
- **Local runs happen inside the web container** (`podman exec -w /app sjvaircom_web_1
  invoke import-data-dashboard ...`), as for monitor-map: on the host the build misses
  `.env`'s keys. Running it from the host is not supported.

### 2. Route

- Add routes before the final `PageTemplate` catch-all in `camp/urls.py`:
  - `workspace/manifest.webmanifest` → the manifest view (more specific, listed first).
  - `^workspace(/.*)?$` → the workspace view. It answers `/workspace` and
    `/workspace/<anything>` with no redirect (the dashboard's router shows the home route
    as `/workspace`; data-dashboard DEFERRED "`/workspace` without a trailing slash").
  - `/workspacefoo` must not match.
- `CommonMiddleware`'s `APPEND_SLASH` only redirects when the path doesn't resolve, so
  it won't touch these. Verify that in a test.
- **No CMS conflict:** sjvair.com has no database-backed pages (`prose` is only a
  rich-text editor); page content is template files under `camp/templates/pages/`, and
  none is named `workspace`. A test that `/workspace` and `/workspace/x` resolve to the new
  view (not `PageTemplate`) covers this.

### 3. The workspace view and template

- A class or function view with `ensure_csrf_cookie`, `never_cache` (Django's
  `Cache-Control: max-age=0, no-cache, no-store, must-revalidate, private`), and GET/HEAD
  only.
- **Framing:** `X-Frame-Options: DENY` (the global `XFrameOptionsMiddleware` already sets
  it; make sure it applies) plus the CSP's `frame-ancestors 'none'`, which is in the
  contract's host list.
- **`X-Robots-Tag: noindex`** on `/workspace/shared/*` (and the template's `<meta
  name="robots" content="noindex">` on those paths too is the builder's call).
- **Template** `camp/templates/workspace/index.html` (location is the builder's call),
  standalone, exactly as the contract gives it (settled 2026-10-26):
  - head: `<html lang="en">`, `<meta charset="utf-8">`,
    `<meta name="viewport" content="width=device-width, initial-scale=1">`,
    `<title>SJVAir Dashboard</title>` (a default; the app sets per-page titles),
    `<link rel="manifest" href="/workspace/manifest.webmanifest">`, sjvair.com's existing
    favicon (`{% static 'img/favicon/favicon.ico' %}`), `<link rel="stylesheet" href="{% static 'workspace/app.css' %}">`,
    `<script type="module" src="{% static 'workspace/app.js' %}"></script>`;
  - body: the mount element `<div id="SJVAirDataDashboard"></div>` (matching monitor-map's
    `SJVAirMonitorMap`; the app mounts into it and does not create it) and the identity `json_script` beside it;
  - no `theme-color` meta (the manifest carries it), no other scripts, no inline script,
    no `defer`. Nothing from `base.html`/`page.html`, no `{% include %}` of site partials.
- Identity built in the view from `request.user` per the contract's shape.

### 4. Manifest view

- Reads `dist/workspace/manifest.webmanifest` (path from settings/`BASE_DIR`, not from
  `STATIC_ROOT` in production terms; it's in the slug either way), rewrites icon `src`
  values, returns `application/manifest+json`.
- **Performance:** read and rewrite once per process (cache in memory, keyed on nothing;
  the file only changes with a deploy, which restarts dynos). A missing file is a 404
  with a logged error, not a 500.
- **Not behind the beta gate** (decided by the user 2026-10-26, after the final review): browsers
  fetch `<link rel="manifest">` without cookies, so a gated manifest 404s even for beta
  testers. It holds nothing private; it is sent `X-Robots-Tag: noindex`.

### 5. Content Security Policy

- Sent only on `/workspace/*` responses (the page; the manifest needs none), built in the
  view from the local copy of `csp-hosts.json` (kept beside the view, e.g.
  `camp/apps/workspace/csp-hosts.json` or wherever the view lives), substituting
  `{static}` with `STATIC_URL + 'workspace/'`. Locally `STATIC_URL` is `/static/`, so
  `{static}` becomes a path; make sure the result is a valid CSP source (an absolute URL
  built from the request host if needed, or `'self'` already covers it; builder's call,
  verified in the browser).
- **Directives (contract, settled 2026-10-26):** `csp-hosts.json` lists every directive the
  header has; sjvair.com adds none of its own:
  `default-src 'none'`; `script-src 'self' {static}`;
  `style-src 'self' {static} 'unsafe-inline'`; `font-src 'self' {static}`;
  `img-src 'self' {static} data: blob:`; `connect-src 'self' {static}` (the Sentry ingest
  host is added to both copies only after the user creates the project; no placeholder,
  and the spec 5 session says when); `worker-src 'self' blob:`; `manifest-src 'self'`;
  `frame-ancestors 'none'`; `base-uri 'none'`; `object-src 'none'`; `form-action 'none'`.
  MapTiler and NREL hosts are added to both copies when the map widget lands.
- Until the dashboard repo has `csp-hosts.json`, the local copy is written from the list
  above and re-checked against the real file when it appears.
- Locally `{static}` would be the bare path `/static/workspace/`, which isn't a valid CSP
  source, so it is dropped when `STATIC_URL` isn't absolute (`'self'` already covers
  it). Verified in the browser with enforcement on.
- Build the header string once per process; it doesn't vary by request.
- **Mode:** a setting `WORKSPACE_CSP_ENFORCE` (env var, boolean). Off →
  `Content-Security-Policy-Report-Only`; on → `Content-Security-Policy`. Production
  default is off (report-only for beta testers); the user flips it before public go-live
  with a config var, no deploy. **Local development enforces from the start** (the local
  `.env` / dev settings default it on), so problems show early.
- **Reports:** `WORKSPACE_CSP_REPORT_URI` setting (the dashboard Sentry project's security
  endpoint). If set, add `report-uri` (and `report-to` with a `Reporting-Endpoints`
  header if the builder wants); if unset, no report directive.
- **Test:** the header the view builds matches the local copy of `csp-hosts.json`, in
  both modes, with and without a report URI.

### 6. Beta gate and nav

- Extend `BetaToolsMiddleware` / `camp/utils/beta.py` so `/workspace` and everything
  under `/workspace/` (except the manifest; see section 4) is a 404 without the `beta_tools` flag,
  exactly as `/tools/` is. Generalize the single prefix into a list of gated prefixes;
  keep `/workspacefoo` ungated. `BETA_TOOLS_GATE=0` opens it, as today.
- Shared links (`/workspace/shared/...`) are gated too during the preview, so testers
  can only share with other testers (the builder's guess, confirmed by the user's
  "behind the beta-testers flag" decision).
- Add "My Dashboard" to the Data Tools dropdown in `camp/templates/page.html` (and the
  footer's beta list beside the explorers, for consistency), linking to `/workspace/`,
  with the same "Beta" tag. Icon is the builder's call (Font Awesome, matching the
  others).
- Update the `beta_tools` flag's note (it says it gates `/tools/`) to mention
  `/workspace/`, via a small data migration or by hand; builder's call.
- **A local beta tester for browser tests** (designer's call): a dev-only management
  command, e.g. `seed_beta_tester`, that creates or updates a non-staff user in the
  "Beta testers" group from env vars (e.g. `WORKSPACE_E2E_IDENTIFIER` (email or phone)
  and `WORKSPACE_E2E_PASSWORD`). It refuses to run when `DEBUG` is off and is idempotent.
  Non-staff, so the group path is what's exercised (staff and superusers get the flag
  anyway). The dashboard's embedding suite signs in through `/account/login/` (fields
  `identifier`, `password`) and then opens `/workspace/`. `BETA_TOOLS_GATE=0` stays
  available for quick manual checks.
- The dashboard's dev setup gets its `csrftoken` from a GET of `/account/login/` through
  its Vite proxy, not from `/workspace/` (the gate would 404 an unflagged dev user before
  `ensure_csrf_cookie` runs). Nothing to do here; production still relies on the view's
  `ensure_csrf_cookie` for flagged users.
- **Go-live later** (not this track): remove the prefix from the gate and move the link
  out of the beta-only menu.

### 7. Tests and verification

- Django tests (`django.test.TestCase`, pytest-style asserts, run via podman-compose):
  routing (both slash forms, deep paths, `/workspacefoo`, manifest not shadowed), the gate
  (404 without the flag, 200 with it, `BETA_TOOLS_GATE=0`), headers (`csrftoken` cookie
  set on first visit, `Cache-Control`, `X-Frame-Options`, `X-Robots-Tag` only under
  `shared/`), the identity block for anonymous and signed-in users (never `api_token` or
  phone), the template not loading site chrome (no GTM, Bulma), the manifest rewrite and
  content type, and the CSP header against `csp-hosts.json`. Tests must not depend on a
  real dashboard build: use a small fixture build directory.
- **No second static origin locally** (user's decision, 2026-10-26). Local setup matches
  monitor-map's: same-origin `/static/`. Cross-origin behavior (relative chunk loading
  from S3, fonts and `version.json` under the bucket's existing rule, the CSP's `{static}`)
  is first exercised in the beta preview on production, with the CSP report-only and
  errors in Sentry; data-dashboard's `DEFERRED.md` records it with a revisit trigger.
  Locally `{static}` is a bare path and is dropped from the header (`'self'` covers it).
- **The shared definition of "embedding works":** data-dashboard's hand-run Playwright
  embedding suite, run against the same-origin local stack with the CSP enforced. It covers: mount,
  no CSP violations, a lazy chunk and a font loaded from the static origin, `version.json`,
  a deep link and `/workspace` with no redirect, the manifest's icon URLs, identity without
  `api_token`, and the `csrftoken` cookie. It signs in as the seeded beta tester (section
  6). Manual checks below go alongside it.
- Script check: a run of the import in the web container against `foundations` (or the
  spec 5 branch once it emits `dist/workspace/`), then `collectstatic`.
- Browser check on the local stack, signed in as a beta tester: the dashboard loads at
  `/workspace` and `/workspace/`, a deep link loads, the identity block is right, no CSP
  violations with enforcement on, the manifest is valid in DevTools, the nav link shows
  only for beta testers, and a non-beta user gets 404.
- Note: the local stack serves the main checkout (`~/workspace/sjvair/sjvair.com`), not
  this worktree. The builder decides how to run the stack against this branch for
  verification (e.g. checking it out in the main checkout with the user's OK, or a
  compose override) and must not disturb the uncommitted resticus
  `docker-compose.override.yml` there.

## What the user does (account work, not the builder)

1. **Sentry:** create the dashboard's own project in the existing org (separate from the
   Django project; leave `SENTRY_DSN` / `SENTRY_DSN_CLIENT` alone). Note its browser DSN
   and its security-header (CSP report) endpoint.
2. **Heroku config vars on the production app** (only when shipping, after Release 1):
   - `VITE_SENTRY_DSN` — the new project's DSN.
   - `VITE_MAPTILER_KEY` — likely already set for monitor-map; the dashboard reads the
     same name. A separate key is possible but would need a different var name (contract
     change).
   - `VITE_NREL_KEY` — the NREL API key.
   - `WORKSPACE_CSP_REPORT_URI` — the Sentry security endpoint.
   - `WORKSPACE_CSP_ENFORCE` — leave unset (report-only) for the preview; set to `1`
     before public go-live.
   - Do **not** set `VITE_PROD_URL` or `VITE_DEV_URL`.
3. **Key restrictions:** restrict the MapTiler key to `www.sjvair.com` (and `sjvair.com`
   if wanted), with a separate key or extra allowed origin for `localhost` dev. NREL:
   restrict by domain if its developer dashboard offers it (not verified here).
4. **Beta testers:** add the pilot teacher and researcher to the "Beta testers" group in
   `/batcave/` when the preview opens.

## Left to the builder

The exact import CLI for local mode; file and module locations (a small `workspace` app
vs. `camp/utils`); template details within the constraints above; how the manifest is
cached; `report-to` in addition to `report-uri`; the nav icon; and how to point the local
stack at this branch for verification.

## Calls made by the designer (the user can override)

- **Node on Heroku:** sjvair.com's `package.json` has no `engines`, so Heroku picks its own
  default and the import's `>=24 <27` check could fail a deploy. Pin `engines.node` in
  sjvair.com's `package.json` to `26.x`, matching the local Docker image (nodesource 26),
  so what's verified locally is what deploys. This also affects the monitor-map build and
  the vendor/esbuild steps, which already run on 26 locally.
- **The dashboard branch to test against:** `foundations-5a-shipping` (stacked on
  `foundations`; its first task makes the build emit `dist/workspace/`), from the local
  checkout `../data-dashboard` or GitHub; `foundations` once 5a merges. The spec 5 session
  messages this session when it first builds.

## Before planning

- **Wait for spec 5a** (user's decision, 2026-10-26). The implementation plan is written
  only after `foundations-5a-shipping` builds `dist/workspace/` and the contract section is
  reviewed, so it plans against the real output and final values, not a stand-in.
- Re-check the contract values above against the spec 5 design's "Hosting contract"
  section (approved by the user 2026-10-26: data-dashboard
  `docs/superpowers/specs/2026-10-26-foundations-5a-shipping-design.md` on
  `foundations-5a-shipping`; re-checked the same day, consistent). That section is
  authoritative.
