"""
The emissions app's models, one module per source or subject. Everything is
re-exported here, so `from camp.apps.emissions.models import Facility` (and
migrations' references such as `methane_plume_upload_to`) keep working.
"""

from camp.apps.emissions.models.facilities import (  # noqa: F401
    EmissionsRecord,
    Facility,
    FacilityManager,
    FacilityQuerySet,
    MINOR_SOURCE_SIC_CODES,
)
from camp.apps.emissions.models.imports import (  # noqa: F401
    SourceImport,
)
from camp.apps.emissions.models.toxics import (  # noqa: F401
    ACUTE_SCALE,
    CANCER_SCALE,
    CHRONIC_SCALE,
    PRECURSOR_IDS,
    RESERVED_SLUGS,
    ToxicEmission,
    ToxicPollutant,
    UNWEIGHTED_IDS,
)
from camp.apps.emissions.models.inventories import (  # noqa: F401
    CountyInventory,
    CountyNEI,
)
from camp.apps.emissions.models.wells import (  # noqa: F401
    Well,
)
from camp.apps.emissions.models.dairies import (  # noqa: F401
    Dairy,
    DairyHerd,
    Digester,
    DigesterGrant,
    DigesterQuerySet,
    HERD_FIELDS,
    LARGE_MATURE_COWS,
    LARGE_OTHER_CATTLE,
    MATURE_DAIRY_FIELDS,
    MEDIUM_MATURE_COWS,
    MEDIUM_OTHER_CATTLE,
    OTHER_CATTLE_FIELDS,
    REPORTED_REF_CODE,
    SizeClass,
    herd_totals,
    size_class,
)
from camp.apps.emissions.models.compliance import (  # noqa: F401
    AirComplianceFacility,
    ComplianceEvent,
)
from camp.apps.emissions.models.ghg import (  # noqa: F401
    GHGReport,
)
from camp.apps.emissions.models.methane import (  # noqa: F401
    MethanePlume,
    MethaneSource,
    methane_plume_upload_to,
)
