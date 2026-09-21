# Locations v2: a generic point model, CDE's authoritative school data, district pages

Approved by Derek 2026-09-21 ("do it"). Supersedes the Locations part of
`2026-09-21-pesticides-explorer-v3-design.md`.

## 1. `regions.Location` becomes a generic point with region links

A Location is any point of interest we may show against pesticide use; schools
and child care are the first kinds. Modelled on `ceidars.Facility`.

```
class Location(TimeStampedModel):
    class Type(TextChoices): PUBLIC_SCHOOL, PRIVATE_SCHOOL, CHILD_CARE   # more later
    sqid, type (db_index), name (200), external_id (64), source (32)
    address, city_name, zip  (CharFields, blank allowed; `city_name` is the source's city string)
    point = PointField(srid=4326, spatial_index=True)
    county          = FK(Region, null, SET_NULL, related_name='county_locations', limit_choices_to={'type': 'county'})
    city            = FK(Region, null, SET_NULL, related_name='city_locations', limit_choices_to={'type__in': ['city', 'cdp']})
    zipcode         = FK(Region, null, SET_NULL, related_name='zipcode_locations', limit_choices_to={'type': 'zipcode'})
    school_district = FK(Region, null, SET_NULL, related_name='district_locations', limit_choices_to={'type': 'school_district'})
    metadata = JSONField(default=dict)
    imported_at = DateTimeField()
    unique_together = (source, external_id)
```
- `resolve_regions()` sets the four FKs from `point` by boundary containment
  (`Region.objects.filter(type=..., boundary__geometry__contains=point)`);
  for `school_district`, when several districts contain the point (an
  elementary and a high district overlap), prefer a Unified district, else
  the one whose `metadata['grade_low'/'grade_high']` span is widest; for
  `city`, prefer a city over a CDP. Returns the instance (not saved).
- `save()` calls `resolve_regions()` when the point changed since load (snapshot
  the point in `from_db()`/`__init__`), or when the row is new and any FK is
  unset. The importer may call it explicitly.
- Accessors: `get_county()`, `get_city()` (city Region name, else `city_name`),
  `get_zipcode()`, `get_school_district()`, `short_type`, `get_pesticides_url()`
  (the school district's page, else '').
- Rename the old `district` field/FK to `school_district` (migration with a
  RenameField + the new FKs). Update every caller (`camp/api/v2/pesticides/locations.py`,
  `camp/apps/pesticides/places.py`, admin, tests).

## 2. Sources

| source | type | dataset (data.ca.gov CKAN id → CSV resource) | notes |
|---|---|---|---|
| `cde-districts` | (Region, not Location) | `california-school-district-areas-2025-26` | already `import_school_districts`; unchanged |
| `cde-public` | public_school | `california-public-schools-2025-26` (CSV, UTF-8 BOM; columns: `CDS Code, District Code, School Code, County Name, District Name, School Name, School Type, Status, Open Date, Closed Date, School Level, Grade Low, Grade High, Charter, Charter Num, Charter Funding Type, Virtual, Magnet, Title I, DASS, Assistance Status ESSA, Street, City, Zip, Locale, School Website, Enroll Total, <race/ethnicity counts and %>, English Learner, Foster, Homeless, Migrant, Socioeconomically Disadvantaged, Students with Disabilities, Free/Reduced Meal Eligible (each count + %), Grade TK … Grade 12, Latitude, Longitude, Geographic County Code/Name, Geographic Elementary District Code/Name, Geographic High District Code/Name, Geographic Unified District Code/Name, US Congressional District, CA State Senate District, CA State Assembly District, Staff Total/Teacher/Admin/Pupil Services/Other`) | keep `Status == 'Active'`, `Virtual` not the exclusively-virtual value (inspect the vocabulary: expect N/Y/P/F/C style; keep N/C/P, drop F/Y-exclusive — record what you found in the code comment), `County Name` in the eight; names are already properly cased: do NOT title-case them |
| `cde-private` | private_school | `california-private-schools-2024-25` (CSV; columns `USER_Name, USER_Street, USER_City, USER_Zip, USER_County, USER_District, USER_CDS, USER_Type, USER_Classification, USER_LowGrade, USER_HighGrade, USER_EnrollK…12, USER_TotalEnroll, USER_FullTimeTeach…, X, Y (Web Mercator), Match_addr, Status, Score`) | keep `USER_County` in the eight and `USER_TotalEnroll >= 6`; coordinates from `X,Y` (EPSG:3857 → transform to 4326) or geocode `Match_addr` when the geocode `Status` isn't a match; external_id = `USER_CDS` |
| `cdss-ccl` | child_care | `community-care-licensing-facilities1` | unchanged (site merge stays) |

Both CDE sources download themselves through the CKAN `package_show` → CSV
resource path the CDSS source already uses. The bot-wall detection stays as a
general guard. `--path` remains supported for every source.

Public-school metadata (nested like the district Regions'): `cds_code,
district_code, district_name` (the administering district), `geographic:
{county, elementary, high, unified}` (code + name each), `school_type,
school_level, grade_low, grade_high, charter (bool), charter_number,
charter_funding, virtual, magnet, title_i, dass, assistance_status, locale,
website, open_date`, `enrollment: {total, by_grade: {tk, kg, 1..12}}`,
`demographics: {african_american: {count, pct}, … not_reported}`,
`subgroups: {english_learners, foster_youth, homeless, migrant,
socioeconomically_disadvantaged, students_with_disabilities,
free_reduced_meals: {count, pct}}`, `staff: {total, teacher, admin,
pupil_services, other}`. Private-school metadata: `cds_code, district_name
(CDE's geographic district), classification, school_type, accommodations,
grade_low, grade_high, enrollment: {total, by_grade}, staff: {...}, tax_exempt`.

`school_district` for public schools: spatial via `resolve_regions()`, then
cross-checked against the file's geographic district codes (unified, else
elementary/high): when the spatial answer's CDS district code differs from
the file's, prefer the file's district (looked up by CDS code prefix) and
count it in a printed "district mismatch" tally. Private schools and child
care: spatial only.

Commands: `import_schools` runs `import_school_districts` then
`import_locations --source cde-public`, so districts exist before schools link
to them; `import_locations` keeps `--source`, `--path`, `--no-geocode`.

## 3. District pages

School-district place pages show:
- A demographics strip (from the Region's metadata): enrollment total, and
  percent Hispanic/Latino, English learners, socioeconomically disadvantaged,
  migrant — as small stat tiles in the existing `.stat-row` idiom, titled
  "Who goes to school here", with the academic year from the Region's
  `version`.
- The schools panel in two groups: "Run by {district}" (public schools whose
  metadata `district_code` matches the Region's CDS district code, i.e. the
  first 7 characters of `external_id`), then "Other schools and child care in
  the area" (everything else with `school_district` == this Region: charters
  run elsewhere, county-office schools, private schools, child care). Same
  columns as today (name, type, city, lbs within about a mile, applications,
  section link); the 15-row cap with "Show all" applies per group. Names are
  rendered as stored for CDE sources; `title_case_name` only for `cdss-ccl`
  (drive it off `source`, not the name's case).
- The map toggle stays on by default there.

## 4. API and map
`/api/2.0/pesticides/locations/` properties: rename `district`/`district_id`/
`district_url` to `school_district`, `school_district_id`, `school_district_url`;
add `city` (from `get_city()`), `grade_span`, `enrollment` (total, when
present), `capacity`. The map popup sub-line stays `type · address, city`;
the "District page" pill uses `school_district_url`.

## Global constraints
Same as the v3 spec: worktree only (`/home/derek/dev/ccac/sjvair.com/.claude/worktrees/feature+pesticides-explorer`), stage by name, no AI attribution or co-author trailers, do not push, Django TestCase + plain assert, fixtures, sqids, Bulma, `Region.short_name` in tables, static assets not cache-busted, `invoke styles` for Sass.
