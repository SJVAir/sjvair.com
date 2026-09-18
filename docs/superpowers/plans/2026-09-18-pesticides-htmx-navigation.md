# Pesticides Explorer htmx Navigation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clicking around the explorer stops reloading the whole page: links, filter forms, sorting, pagination, and the year picker swap only the explorer's own region and push the URL, so every page stays fully server-rendered, linkable, and testable.

**Architecture:** htmx `hx-boost` on the explorer wrapper. Boosted requests fetch the same full page the server already renders; `hx-select` pulls out the explorer region (hero + breadcrumbs + content) and swaps it in place, `hx-push-url` updates the address bar, and htmx sets the document title from the response. No server changes to rendering. Our two component scripts (section map, find-your-area) initialise on `htmx:load` as well as on page load, and history navigation refetches rather than restoring a cached snapshot (Leaflet-generated DOM must not be re-hydrated from a snapshot). Filter forms auto-submit on change.

**Tech Stack:** htmx 2.x vendored under `assets/js/vendor/` (no build step), Django templates, plain ES2017.

**Spec:** `docs/superpowers/specs/2026-09-16-pesticides-explorer-v2-design.md` (cross-cutting: URLs are the only state; no new framework or build step). Derek 2026-09-18: "constant whole page refreshes … using the history api and updating the url so everything is transparent to the user and still linkable" — "I was just gonna mention htmx. I'm down for it."

## Global Constraints

- Commands from the worktree root inside Docker: `docker compose run --rm test pytest camp/apps/pesticides -q`; `node --check` on edited scripts; `docker compose run --rm web invoke styles` after sass edits (`dist/css/style.css` is git-ignored).
- Every explorer URL must still render completely on a plain GET (no htmx header) — tests stay on plain `self.client.get`. Nothing depends on JS for content.
- No AI attribution in commits. Never `git add -A`. A dev server for this worktree runs on port 8002 (do not start/stop it).

---

## File map

| File | Responsibility |
|---|---|
| `assets/js/vendor/htmx.min.js` | vendored htmx 2.x (copied from `node_modules/htmx.org/dist/htmx.min.js` after `yarn add htmx.org`) |
| `camp/templates/pesticides/base.html` | `#explorer` wrapper with the boost attributes around hero + breadcrumbs + content; htmx script tag; config |
| `assets/js/pesticides/explorer.js` | htmx config (`historyCacheSize = 0`, `scrollBehavior`), progress indicator hooks, auto-submit wiring, and `htmx:load` → init of components |
| `assets/js/pesticides/section-map.js`, `find-area.js` | export `init(root)` that initialises only uninitialised containers under `root` (mark with `data-initialised`), called on `DOMContentLoaded` and from `explorer.js` |
| `camp/templates/pesticides/includes/filter-form.html`, `records.html`, `notice-list.html` | `hx-trigger` for auto-submit on change (text search debounced) |
| `assets/sass/sjvair/pages/pesticides.sass` | `.htmx-request` progress bar under the nav; `.htmx-swapping` fade |
| `camp/apps/pesticides/tests/test_views.py` | boost attributes present; a request with `HX-Request: true` still returns the full page (200, contains `id="explorer"`) |

---

### Task 1: Vendor htmx and boost the explorer region

- [ ] `docker compose run --rm web yarn add htmx.org@^2.0.4`; copy `node_modules/htmx.org/dist/htmx.min.js` to `assets/js/vendor/htmx.min.js` (commit the copy; `node_modules` is not served).
- [ ] `base.html`: wrap the three sections (hero, breadcrumbs, content) in `<div id="explorer" hx-boost="true" hx-target="#explorer" hx-select="#explorer" hx-swap="outerHTML show:window:top" hx-push-url="true">`. Load `vendor/htmx.min.js` before the pesticides scripts and add `assets/js/pesticides/explorer.js` after them. Keep the `<title>` block as is (htmx applies the response title).
- [ ] `explorer.js` (plain ES2017 IIFE): `htmx.config.historyCacheSize = 0` (history navigation refetches), `htmx.config.scrollBehavior = 'instant'`; on `htmx:load` call `window.PesticidesSectionMap.init(evt.detail.elt)` and `window.PesticidesFindArea.init(evt.detail.elt)` when those globals exist; on `htmx:responseError` fall back to a full navigation (`window.location = evt.detail.pathInfo.requestPath`) so a 500 never leaves the page half-swapped; on `htmx:beforeSwap` for non-2xx/3xx responses set `evt.detail.shouldSwap = false`.
- [ ] `section-map.js` / `find-area.js`: refactor the bottom `init` to accept a root element, skip containers with `data-initialised`, set it, and expose `window.PesticidesSectionMap = { init }` / `window.PesticidesFindArea = { init }`. The existing `DOMContentLoaded` call becomes `init(document)`.
- [ ] Links that must not be boosted: external links already have `target="_blank"`; add `hx-boost="false"` on the API docs / client docs / SprayDays links inside `#explorer` if they are not `target="_blank"` (check `detail-base.html`, `section-detail.html`, `place.html`, `home.html`, `about.html`).
- [ ] Test: `test_explorer_region_is_boosted` (home HTML contains `hx-boost="true"` and `id="explorer"`), `test_htmx_request_gets_full_page` (`self.client.get(url, HTTP_HX_REQUEST='true')` → 200 and contains `<title>`).
- [ ] Commit: `feat(pesticides): swap the explorer region with htmx instead of reloading the page`.

### Task 2: Auto-submit filters and a loading indicator

- [ ] `includes/filter-form.html` (entity lists), `records.html`, `notice-list.html`: on each filter `<form method="GET">` add `hx-trigger="submit, change delay:250ms"`; on the `q` search input add `hx-trigger="keyup changed delay:500ms"` via a wrapping attribute on the input (`hx-get` is inherited from the boosted form: put `hx-get="{{ request.path }}" hx-include="closest form"` on the input). Keep the Apply button (submits immediately; also the no-JS path).
- [ ] Sass: a 2px `$primary` progress bar fixed at the top of the viewport shown while `body.htmx-request` (htmx adds `htmx-request` to the requesting element; use `hx-indicator="body"` on `#explorer`), and `#explorer.htmx-swapping { opacity: .6 }` with a 150 ms transition, honouring `prefers-reduced-motion`.
- [ ] Focus: after a swap triggered by typing in `q`, keep focus in the search box with the caret at the end (`htmx:afterSwap` → if the trigger was `#id_q`, refocus `#id_q` in the new content and set `selectionStart` to the value length).
- [ ] Commit: `feat(pesticides): auto-submit explorer filters and show a progress bar during swaps`.

### Task 3: Browser check (controller)

Chrome on port 8002: click through Map → Chemicals → a chemical → Records → Notices → a notice → back/forward; change year on a detail page; type in the chemicals search; change county on records (map re-inits with the new filter); landing search still works after navigating away and back; a 404 link falls back to a full navigation. Ledger; push.
