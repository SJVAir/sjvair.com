# CalEnviroScreen 5.0 Integration — Design

## Background

CalEnviroScreen 5.0 (CES5) was released by OEHHA in July 2026, replacing CES4 as
the current version. This adds CES5 alongside the existing CES4 implementation
in `camp/apps/ces/`. As part of this work, CES4's API is also restructured so
both versions share a consistent URL shape.

Source data was verified directly against the live dataset (not just docs):

- Dataset: `calenviroscreen-5-0` on data.ca.gov. Resources: Shapefile, CSV, GDB,
  Excel, and a data dictionary PDF.
- Shapefile (`calenviroscreen50results_f_070126.shp`, final release) has 9,106
  features with field names matching the CSV/dictionary exactly (no 10-char
  DBF truncation this time).
- Confirmed via `ogrinfo`: missing values use the same `-999` sentinel
  convention as CES4 (float, may have precision drift near -999).
- Draft 2026 SB535 DAC designation layer found by tracing OEHHA's ArcGIS
  Instant App (`f6f616c3b8d645489c1090d5292f6546`) → webmap
  (`869210729aa948b6b578cc3ddb21777b`) → FeatureServer:
  `https://services1.arcgis.com/PCHfdHz4GlDNAhBb/arcgis/rest/services/DRAFT_SB535_Disadvantaged_Communities_2026/FeatureServer/0`.
  Confirmed via a grouped stats query that `dac_type` has exactly three
  distinct values: `CES 4.0 Carry-Over DAC` (436), `CES 5.0 Top 25%` (2,259),
  `CES 5.0 High Pollution/Low Population` (9). This layer is explicitly a
  **draft** — CalEPA's public comment period runs through August 14, 2026.

## Key differences from CES4

| Aspect | CES4 | CES5 |
|---|---|---|
| Census tract vintage | Native 2010, crosswalked to 2020 | Native 2020 only |
| Indicator count | 21 | 23 (+ Diabetes Prevalence, + Small Air Toxic Sites) |
| Demographics | Raw population counts (`IntegerField`) | Percentages (`FloatField`) |
| Asian/Pacific Islander | Combined `pop_aapi` | Split into `asian` / `pacisl` |
| Tract metadata | None | zipcode, approx city, county, CES region name |
| DAC source | Finalized 2022 SB535 layer | Draft 2026 layer (pending finalization) |

Decisions made during design (see conversation for full rationale):

- Store 2020-native CES5 records only — no backward crosswalk to 2010.
- Use the **draft** 2026 DAC layer now; the import command is idempotent and
  documented as safe to re-run once CalEPA finalizes it.
- Missing values (`-999`) are stored literally, matching CES4's existing
  `_clean_value` convention — no behavior change for consistency.
- Store the new tract metadata fields (zipcode, approx_loc, county,
  region_name) directly on `CES5`, not on the shared `CESRecord` abstract
  base (adding them there would force a meaningless migration onto CES4's
  table).
- Demographic percentage fields get a `_pct` suffix (e.g. `pop_hispanic_pct`)
  to make the count→percentage change impossible to miss when reading code
  that touches both CES4 and CES5.
- `region` is already a `CESRecord` property (returns the linked
  `regions.Region`). The shapefile's own `region` column (CalEnviroScreen's
  multi-county grouping, e.g. "San Joaquin Valley") is stored as
  `region_name` to avoid the collision.
- `DACCategory.PRIOR_DAC`'s label changes from "Designated under 2017 DAC
  list" to "Carried over from prior DAC designation" — generalizing it since
  the enum is shared between CES4 and CES5 and the lineage differs per
  version. Integer value and matching logic are unchanged.
- If the draft DAC layer is unreachable or missing tracts, the importer warns
  and proceeds (matching CES4's existing "missing tracts" warning pattern)
  rather than failing the whole import.
- **CES4's API is restructured** as part of this work: the `<year>` URL
  segment moves to an optional `?year=` query param (defaulting to `2020`),
  so CES4 and CES5 share the same URL shape. Base path stays
  `calenviroscreen/`; version segments stay dotted (`4.0/`, `5.0/`).

## Model

New concrete model `CES5(CESRecord)` in `camp/apps/ces/models.py`. Reuses the
abstract `CESRecord` base unchanged (`boundary`, `population`, `ci_score`,
`ci_score_p`, `dac_sb535`, `dac_category`, and the `tract`/`census_year`/
`region` properties). `DACCategory` enum is reused unchanged except for the
`PRIOR_DAC` label tweak above.

```python
class CES5(CESRecord):
    # --- Tract metadata (new in CES5) ---
    zipcode = models.IntegerField(_('ZIP Code'), null=True)
    approx_loc = models.CharField(_('Approximate Location'), max_length=100, null=True, blank=True)
    county = models.CharField(_('County'), max_length=100, null=True, blank=True)
    region_name = models.CharField(_('CalEnviroScreen Region'), max_length=100, null=True, blank=True)

    # --- Pollution Burden ---
    pollution = models.FloatField(_('Pollution Burden Score'), null=True)
    pollution_s = models.FloatField(_('Pollution Burden Score (scaled)'), null=True)
    pollution_p = models.FloatField(_('Pollution Burden Percentile'), null=True)

    pol_ozone = models.FloatField(_('Ozone'), null=True)
    pol_ozone_p = models.FloatField(_('Ozone Percentile'), null=True)
    pol_pm = models.FloatField(_('PM2.5'), null=True)
    pol_pm_p = models.FloatField(_('PM2.5 Percentile'), null=True)
    pol_diesel = models.FloatField(_('Diesel PM'), null=True)
    pol_diesel_p = models.FloatField(_('Diesel PM Percentile'), null=True)
    pol_pest = models.FloatField(_('Pesticides'), null=True)
    pol_pest_p = models.FloatField(_('Pesticides Percentile'), null=True)
    pol_rsei_haz = models.FloatField(_('Toxic Releases (RSEI)'), null=True)
    pol_rsei_haz_p = models.FloatField(_('Toxic Releases Percentile'), null=True)
    pol_traffic = models.FloatField(_('Traffic'), null=True)
    pol_traffic_p = models.FloatField(_('Traffic Percentile'), null=True)
    pol_drink = models.FloatField(_('Drinking Water Contaminants'), null=True)
    pol_drink_p = models.FloatField(_('Drinking Water Contaminants Percentile'), null=True)
    pol_lead = models.FloatField(_("Child's Lead Risk from Housing"), null=True)
    pol_lead_p = models.FloatField(_("Child's Lead Risk from Housing Percentile"), null=True)
    pol_cleanups = models.FloatField(_('Cleanup Sites'), null=True)
    pol_cleanups_p = models.FloatField(_('Cleanup Sites Percentile'), null=True)
    pol_gwthreats = models.FloatField(_('Groundwater Threats'), null=True)
    pol_gwthreats_p = models.FloatField(_('Groundwater Threats Percentile'), null=True)
    pol_haz = models.FloatField(_('Hazardous Waste'), null=True)
    pol_haz_p = models.FloatField(_('Hazardous Waste Percentile'), null=True)
    pol_iwb = models.FloatField(_('Impaired Water Bodies'), null=True)
    pol_iwb_p = models.FloatField(_('Impaired Water Bodies Percentile'), null=True)
    pol_small_ats = models.FloatField(_('Small Air Toxic Sites'), null=True)         # NEW
    pol_small_ats_p = models.FloatField(_('Small Air Toxic Sites Percentile'), null=True)  # NEW
    pol_swis = models.FloatField(_('Solid Waste Sites'), null=True)
    pol_swis_p = models.FloatField(_('Solid Waste Sites Percentile'), null=True)

    # --- Population Characteristics ---
    popchar = models.FloatField(_('Population Characteristics Score'), null=True)
    popchar_s = models.FloatField(_('Population Characteristics Score (scaled)'), null=True)
    popchar_p = models.FloatField(_('Population Characteristics Percentile'), null=True)

    char_asthma = models.FloatField(_('Asthma'), null=True)
    char_asthma_p = models.FloatField(_('Asthma Percentile'), null=True)
    char_cvd = models.FloatField(_('Cardiovascular Disease'), null=True)
    char_cvd_p = models.FloatField(_('Cardiovascular Disease Percentile'), null=True)
    char_diabetes = models.FloatField(_('Diabetes Prevalence'), null=True)          # NEW
    char_diabetes_p = models.FloatField(_('Diabetes Prevalence Percentile'), null=True)  # NEW
    char_lbw = models.FloatField(_('Low Birth Weight'), null=True)
    char_lbw_p = models.FloatField(_('Low Birth Weight Percentile'), null=True)
    char_edu = models.FloatField(_('Educational Attainment'), null=True)
    char_edu_p = models.FloatField(_('Educational Attainment Percentile'), null=True)
    char_ling = models.FloatField(_('Linguistic Isolation'), null=True)
    char_ling_p = models.FloatField(_('Linguistic Isolation Percentile'), null=True)
    char_pov = models.FloatField(_('Poverty'), null=True)
    char_pov_p = models.FloatField(_('Poverty Percentile'), null=True)
    char_unemp = models.FloatField(_('Unemployment'), null=True)
    char_unemp_p = models.FloatField(_('Unemployment Percentile'), null=True)
    char_housingb = models.FloatField(_('Housing Burden'), null=True)
    char_housingb_p = models.FloatField(_('Housing Burden Percentile'), null=True)

    # --- Demographics (percentages, unlike CES4's raw counts) ---
    pop_under_10_pct = models.FloatField(_('Population Under 10 (%)'), null=True)
    pop_10_64_pct = models.FloatField(_('Population 10–64 (%)'), null=True)
    pop_65_plus_pct = models.FloatField(_('Population 65+ (%)'), null=True)
    pop_hispanic_pct = models.FloatField(_('Hispanic/Latino Population (%)'), null=True)
    pop_white_pct = models.FloatField(_('White Population (%)'), null=True)
    pop_black_pct = models.FloatField(_('Black or African American Population (%)'), null=True)
    pop_native_pct = models.FloatField(_('American Indian and Alaska Native Population (%)'), null=True)
    pop_asian_pct = models.FloatField(_('Asian Population (%)'), null=True)          # split from pop_aapi
    pop_pacisl_pct = models.FloatField(_('Pacific Islander Population (%)'), null=True)  # split from pop_aapi
    pop_other_pct = models.FloatField(_('Other or Multiple Races Population (%)'), null=True)

    class Meta(CESRecord.Meta):
        verbose_name = _('CalEnviroScreen 5.0')
        verbose_name_plural = _('CalEnviroScreen 5.0 Records')
        ordering = ['boundary__region__external_id']
```

`camp/apps/ces/admin.py` gets a `CES5Admin(CESRecordAdmin)` registration
following the same fieldsets pattern as `CES4Admin`.

## Import command

`camp/apps/ces/management/commands/import_ces5.py`, invoked as
`python manage.py import_ces5`.

```python
CES5_DATASET_ID = 'calenviroscreen-5-0'
CES5_RESOURCE_NAME = 'CalEnviroScreen 5.0 Shapefile'

# Draft 2026 SB535 DAC designation, based on CES5. Public comment open
# through Aug 14, 2026 — re-run this command once CalEPA finalizes it.
DRAFT_DAC_2026_URL = 'https://services1.arcgis.com/PCHfdHz4GlDNAhBb/arcgis/rest/services/DRAFT_SB535_Disadvantaged_Communities_2026/FeatureServer/0'

DAC_CATEGORY_MAP = {
    'CES 5.0 Top 25%': DACCategory.TOP_CES_SCORE,
    'CES 5.0 High Pollution/Low Population': DACCategory.TOP_POLLUTION,
    'CES 4.0 Carry-Over DAC': DACCategory.PRIOR_DAC,
}

FIELD_MAP = {
    'zipcode': 'zipcode', 'approx_loc': 'approx_loc', 'county': 'county', 'region': 'region_name',
    'ACS2024Pop': 'population', 'CIscore': 'ci_score', 'CIscoreP': 'ci_score_p',
    'ozone': 'pol_ozone', 'ozoneP': 'pol_ozone_p', 'pm': 'pol_pm', 'pmP': 'pol_pm_p',
    'diesel': 'pol_diesel', 'dieselP': 'pol_diesel_p', 'pest': 'pol_pest', 'pestP': 'pol_pest_p',
    'RSEIhaz': 'pol_rsei_haz', 'RSEIhazP': 'pol_rsei_haz_p',
    'traffic': 'pol_traffic', 'trafficP': 'pol_traffic_p',
    'drink': 'pol_drink', 'drinkP': 'pol_drink_p', 'lead': 'pol_lead', 'leadP': 'pol_lead_p',
    'cleanups': 'pol_cleanups', 'cleanupsP': 'pol_cleanups_p',
    'gwthreats': 'pol_gwthreats', 'gwthreatsP': 'pol_gwthreats_p',
    'haz': 'pol_haz', 'hazP': 'pol_haz_p', 'iwb': 'pol_iwb', 'iwbP': 'pol_iwb_p',
    'SmATS': 'pol_small_ats', 'SmATSP': 'pol_small_ats_p',
    'swis': 'pol_swis', 'swisP': 'pol_swis_p',
    'Pollution': 'pollution', 'PollutionS': 'pollution_s', 'PollutionP': 'pollution_p',
    'asthma': 'char_asthma', 'asthmaP': 'char_asthma_p', 'cvd': 'char_cvd', 'cvdP': 'char_cvd_p',
    'diabetes': 'char_diabetes', 'diabetesP': 'char_diabetes_p',
    'lbw': 'char_lbw', 'lbwP': 'char_lbw_p', 'edu': 'char_edu', 'eduP': 'char_edu_p',
    'ling': 'char_ling', 'lingP': 'char_ling_p', 'pov': 'char_pov', 'povP': 'char_pov_p',
    'unemp': 'char_unemp', 'unempP': 'char_unemp_p',
    'housingB': 'char_housingb', 'housingBP': 'char_housingb_p',
    'PopChar': 'popchar', 'PopCharSco': 'popchar_s', 'PopCharP': 'popchar_p',
    'pop_und10': 'pop_under_10_pct', 'pop_10_64': 'pop_10_64_pct', 'pop_ov64': 'pop_65_plus_pct',
    'hisp': 'pop_hispanic_pct', 'white': 'pop_white_pct', 'black': 'pop_black_pct',
    'amind': 'pop_native_pct', 'asian': 'pop_asian_pct', 'pacisl': 'pop_pacisl_pct',
    'othmult': 'pop_other_pct',
}
```

Flow (no crosswalk needed — CES5 is 2020-native):

1. `get_ces5()` — `geodata.gdf_from_ckan(dataset_id=CES5_DATASET_ID, resource_name=CES5_RESOURCE_NAME, string_fields=['tract'], limit_to_region=True, threshold=0.25)`. Zfill `tract` to 11 chars.
2. Join DAC data: fetch the draft 2026 layer via `esri2gpd.get(DRAFT_DAC_2026_URL)`, zfill its `tract` column, build a `dac_type` lookup by GEOID, map through `DAC_CATEGORY_MAP`, and set `dac_sb535`/`dac_category` — same pattern as CES4's SB535 join. If the layer fetch fails or tracts are missing, warn (`self.style.WARNING`) and continue with those fields left null, rather than aborting.
3. `save_records()` — match against existing 2020-vintage `Boundary` rows (already populated by CES4's crosswalk step) via `boundary_map`, `update_or_create` keyed on `boundary`, reusing `_clean_value` for the `-999`/NaN handling.
4. Keep `--print-columns` for field-mapping verification, same as CES4.

## API

Both CES4 and CES5 endpoints live in the existing `camp/api/v2/ces/` package
(not a new `ces5/` package — that package represents "the CES API," not
specifically CES4).

**`camp/api/v2/ces/urls.py`**
```python
urlpatterns = [
    path('4.0/', endpoints.CES4List.as_view(), name='ces4-list'),
    path('4.0/<str:tract>/', endpoints.CES4Detail.as_view(), name='ces4-detail'),
    path('5.0/', endpoints.CES5List.as_view(), name='ces5-list'),
    path('5.0/<str:tract>/', endpoints.CES5Detail.as_view(), name='ces5-detail'),
]
```
Mounted at `calenviroscreen/` under `/api/2.0/` (unchanged).

**`camp/api/v2/ces/endpoints.py`** — `CES4Mixin` changes to read `year` from
the query string instead of a URL kwarg, defaulting to `'2020'`:
```python
class CES4Mixin:
    model = CES4
    serializer_class = CES4Serializer
    paginate = True

    def get_queryset(self):
        year = self.request.GET.get('year') or '2020'
        return super().get_queryset().filter(boundary__version=year)


class CES4List(CES4Mixin, generics.ListEndpoint):
    filter_class = CES4Filter


class CES4Detail(CES4Mixin, generics.DetailEndpoint):
    def get_object(self):
        try:
            return self.get_queryset().get(boundary__region__external_id=self.kwargs['tract'])
        except CES4.DoesNotExist:
            raise Http404


class CES5Mixin:
    model = CES5
    serializer_class = CES5Serializer
    paginate = True


class CES5List(CES5Mixin, generics.ListEndpoint):
    filter_class = CES5Filter


class CES5Detail(CES5Mixin, generics.DetailEndpoint):
    def get_object(self):
        try:
            return self.get_queryset().get(boundary__region__external_id=self.kwargs['tract'])
        except CES5.DoesNotExist:
            raise Http404
```

**`serializers.py`** — `CES5Serializer` mirrors `CES4Serializer`'s shape, plus
`zipcode`, `approx_loc`, `county`, `region_name`, `pol_small_ats(_p)`,
`char_diabetes(_p)`, and the `_pct`-suffixed demographic fields.

**`filters.py`** — `CES5Filter` mirrors `CES4Filter`'s `region_id` method
filter and range filters on `ci_score`, `ci_score_p`, `pollution_p`,
`popchar_p`, plus new range filters for `pol_small_ats_p` and
`char_diabetes_p`.

## Tests & fixtures

- Extend `fixtures/calenviroscreen.yaml` (or add a sibling fixture) with CES5
  records for the existing fake Fresno tracts, covering one DAC and one
  non-DAC tract — same PK-range convention already used to avoid conflicts
  with `regions.yaml`.
- `camp/apps/ces/tests.py`: add `CES5ModelTests` mirroring `CES4ModelTests`
  minus the dual-vintage tests (`test_both_vintages_exist`,
  `for_version`/`for_tract` vintage assertions) since CES5 has one vintage.
- `camp/api/v2/ces/tests.py`: add `CES5EndpointTests` and
  `CES5RegionFilterTests` mirroring the CES4 equivalents minus year-vintage
  cases. Update the existing `CES4EndpointTests` to pass `year` as a query
  param (`?year=2020`) instead of a URL kwarg, and add
  `test_list_defaults_to_2020_when_year_omitted`.

## Out of scope / follow-ups

- Re-running `import_ces5` once CalEPA finalizes the 2026 DAC designation
  (currently in public comment through Aug 14, 2026).
- Deleting `camp/apps/integrate/ces4/` (the old, unused intern implementation)
  — unrelated to this work, already tracked as a pre-existing cleanup item.
