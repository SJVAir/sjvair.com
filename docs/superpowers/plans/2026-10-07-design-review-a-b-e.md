# Design Review Fixes (Batches A, B, E + Compact Hero) — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the place-pages design review's accessibility (A), colour (B) and content (E) findings, and add a shared compact explorer hero, across the site chrome and both explorers' shared pieces.

**Source of findings (the spec):** `/tmp/claude-1000/-home-derek-dev-ccac-sjvair-com/d2f1c328-d4be-4c0c-b586-9ed8de314699/scratchpad/design-review/findings.md` (IDs C1–C6, H1–H10, M1–M25, L1–L14; published at https://claude.ai/artifact/RABKXSJqkEzR3DnwaVixYs). Screenshots alongside it. Emissions' review: `.claude/worktrees/feature+ceidars-explorer/.superpowers/emissions-review/01-findings.md` (S*/P* items).

**Approved by Derek 2026-10-07:** batches A, B, E; site-wide colour change (decision 1: darker link/text blue ~#1f6fae with #3498db kept for fills/lines; grey ~#6b6b6b); compact hero on explorer inner pages, as a shared modifier both explorers use. **Not approved yet (do not do):** Notices year picker/pounds shading (H8), buffer labelling (H7), phone filter collapse / unpinned scope bar (H6, H6b), other map changes (batch D), phone layout batch C except where listed here.

## Global Constraints
- Worktree `/home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+pesticides-explorer`, branch `feature/pesticides-explorer`; absolute paths, `git -C <worktree>`; never the main checkout.
- Shared files (page.html, sjvair sass, regions/ templates, maps/ core, explorer base pieces) change only here; emissions merges down.
- Tests: `django.test.TestCase`, plain `assert`; run `docker compose run --rm test pytest camp/apps/pesticides camp/apps/regions camp/api -n 4 --dist loadscope -q`.
- Static: `docker exec sjvair-web-run-6c41a98c8a28 sh -c 'invoke styles && python manage.py collectstatic --noinput -v0'` (8002 mounts this worktree; check `docker ps` if the container name changed).
- **Commit messages: no `Co-Authored-By` trailer, no AI attribution;** check `git log -1 --format=%B`. Commit locally; never push.
- Never remove the pesticides map's Tiles/Ramp/Bins selectors. Products before chemicals wherever both appear.
- Verify visually: after each task, screenshot the affected pages at 1440 and 390 with the Chrome DevTools MCP (load `mcp__plugin_chrome-devtools-mcp_chrome-devtools__*` via ToolSearch) against http://localhost:8002, and re-check the specific findings fixed; save under the scratchpad `design-review/after/`.

## Review Focus
1. Colour change must reach every text use of the link blue (links, active tab, breadcrumbs, selected toolbar button text) without darkening fills/lines that are meant to stay #3498db (map lines, chart series, badges' backgrounds).
2. Skip link is visible on focus and lands on `<main>`; no page loses its content wrapper.
3. Menus still open/close by mouse and keyboard after dropping `role="menu"`; focus returns to the trigger.
4. Tooltip fix keeps tooltips working on hover/focus (desktop) and doesn't reintroduce overflow on phones.
5. Compact hero: the explorer home keeps the full hero; inner pages get the compact band on both desktop and phone; tabs stay reachable and labelled.

---

### Task 1: Colour tokens and links (batch B)
Findings: H1, H2 (incl. tag colours), C2 (underline in-text links), L12 (tiny uppercase labels), L14 (sort icons). Files: `assets/sass/sjvair/variables.sass` (`$blue: #3498db` at line 8; Bulma derives `$link` from it — check how), explorer sass (`assets/sass/sjvair/pages/pesticides.sass`, `components/area-pages.sass`), classification-badge styles, sort-link styles.
- Introduce a darker text/link shade (about `#1f6fae`; verify ≥4.5:1 on #fff, #fafafa and #ededed — compute, and pick the lightest shade that passes all three) and use it for `$link` and any text set in the blue (active tab, breadcrumbs, `.has-text-link`, selected toolbar/segmented button text/background where text sits on it — white on the new shade must also pass). Keep `#3498db` for non-text fills/lines.
- Secondary grey: `#6b6b6b` or darker wherever `#7a7a7a` text appears (Bulma `$grey`/`$text-light` usage, `.has-text-grey`, stat labels/notes, `.identifiers`); verify ≥4.5:1 on #fff and #fafafa.
- Flag tags: Prop 65 / IARC / Fumigant text to pass 4.5:1 on their tag backgrounds.
- Underline links in running text: `.content p a`, `.help a`, `.is-size-7 a`, data-notes links, `.sources a`, `.school-kind a` (not nav, tabs, buttons, tables, boards).
- L12: raise the 11px uppercase stat labels to a readable size or sentence case (keep the design; one rule).
- L14: sort icons only on the sorted column and on hover/focus, in grey.
- Test: a small Python test computing contrast for the chosen tokens against the backgrounds above (parse the sass variables or hard-code the chosen values in one place the test imports — keep it simple). Commit: `style(site): link blue and grey pass text contrast; in-text links underlined`.

### Task 2: Site chrome landmarks (batch A, site-wide)
Findings: M20 (main + skip link), M19 (footer h4 order; one H1 per page), C6 (translate select label). File: `camp/templates/page.html` (`{% block main %}` ~line 148, footer ~166, `select#id_translate` ~127).
- Wrap `{% block main %}` in `<main id="main">`; add a skip link first in `<body>` ("Skip to content", visible on focus); footer headings to a level that follows the page (e.g. h2 with the same look); `aria-label="Language"` on the translate select.
- Check every template that extends page.html still renders (grep for templates that output their own `<main>`; avoid nesting).
- Test: a page response contains exactly one `<main`, the skip link targets `#main`, the select has the label. Commit: `fix(site): main landmark, skip link, footer heading order, labelled language picker`.

### Task 3: Explorer controls and structure (batch A)
Findings: C1, C3, C4, C5, H3, H4, M11, M12, M17, M18, M24, M19 (board/chart titles as headings; one H1), L2, L4, L6, L13. Files: `camp/templates/maps/includes/map.html` (shared map chrome), `assets/js/maps/chrome.js`, `camp/templates/pesticides/includes/scope-picker.html`, `buffer-toolbar.html`, `map-toolbar.html`, `by-county-table.html`, `includes/notice-filters.html`, `includes/pagination.html`, `regions/includes/area-header.html`, chart templates/`assets/js/pesticides/charts.js`, sort-link tag, archive months include, reveal toggles.
- C1: Options button `aria-label`. C4: drop `role="menu"`/`menuitem` from link dropdowns (scope pickers, Map area, Compare), keep `aria-expanded` + `aria-controls`, Escape closes and returns focus to the trigger, ArrowDown from the trigger moves into the list (optional). M17: Options panel `role="dialog"` with a label, focus its first control ("Shade by"/Pounds) on open; selectors stay.
- C5: Scheduled/Past radios in a `fieldset` + `legend` ("Notices"), visually unchanged.
- H3: visible `:focus-visible` outline on map toolbar buttons.
- H4: tooltip pseudo-elements not laid out while hidden (e.g. `display:none` until `:hover`/`:focus-visible`), right-edge tooltips anchored left; confirm `document.documentElement.scrollWidth <= innerWidth` at 390 and 1440 on Records/Notices/Schools.
- C3: visually hidden data tables for the Overview trend and method-share charts (follow the heatmap's existing screen-reader table pattern).
- M11 `aria-sort` on sorted headers; M12 `aria-current="page"` on the active archive month; L2 pagination disabled state as a non-link (`span` with `aria-disabled="true"`); L6 `aria-controls` on reveal toggles; L13 near-me radius links in a labelled group; L4 map toolbar before attribution in focus order (DOM order or tabindex-free reordering).
- M18/M24: 24px minimum targets — pad the narrowing/shades "?" icons, map/legend checkboxes (make the label the hit area), scope buttons, phone zoom controls, Community links.
- M19: one H1 per page; board and chart titles as headings at the right level.
- Tests where server-rendered (aria attributes, fieldset, pagination markup, headings); JS behaviour checked in the browser. Commit: `fix(explorer): accessible menus, focus, targets, tooltips and chart tables`.

### Task 4: Shared compact hero
Approved: explorer home keeps the full hero; every other explorer page gets a compact band — title and tabs only, about 110px on desktop; on phone the title on one line and **labelled** tabs (not icon-only). Built as a shared modifier both explorers use: `.explorer-hero.is-compact` (or `#explorer-hero` + `is-compact` on the existing `section.hook#explorer-hero` in `camp/templates/pesticides/base.html` ~42), with a base-template block (e.g. `{% block explorer-hero-class %}is-compact{% endblock %}` default on inner pages, overridden on the home page) that emissions' base can use the same way. Shared sass in the components layer (not `body.pesticides`-only).
- Test: home page renders the full hero; an inner page renders `is-compact`. Screenshots at 1440/390 of home, a list page, a place page. Commit: `feat(explorer): compact hero on inner pages`.

### Task 5: Content and data (batch E)
Findings: M9 (Overview "View all" targets + distinct names), M13 (spell out "active ingredient" for "AI"; MTRS codes don't wrap mid-code; tract place hints), M15 (Community heading duplication "CalEnviroScreen CalEnviroScreen 5.0"; tract labels with a place hint, e.g. "Tract 20.01 · <nearest city/CDP>"), M21 (scheduled-notices empty state links to past notices and SprayDays sign-up), M23 (**investigate** the acreage figures: Restricted materials 46,006,777 acre-treatments for 7,681 applications; a nursery row with 63,000 acres; unify "acres treated" vs "acre-treatments" wording — report the cause before changing data logic; fix wording only), L3 (entity picker: exact and prefix matches ranked first; label CDPR codes), L5 (one `<title>` pattern across tabs, e.g. "<Tab> · <Place> | …"), L7 (ZIP links styled as links), L9 (leave data; skip), L11 (Notices count copy: "28 past notices here in October 2026").
- Files: `camp/templates/pesticides/place.html` and area tab templates, `regions/includes/community-card.html` / `tract-name.html`, `includes/notice-rows.html` empty state, picker search API (`camp/api/v2/pesticides` search endpoint) ranking, views for titles.
- Tests for each server-rendered change. Commit: `fix(pesticides): View all targets, Community labels, empty states, titles and copy` (split into two commits if the picker ranking change is large).
