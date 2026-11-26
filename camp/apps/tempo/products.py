from .models import Granule

# Units per TEMPO product, shared by the catalog and /tempo/products/.
TEMPO_UNITS = {
    Granule.Product.NO2: 'molecules/cm²',
    Granule.Product.O3TOT: 'molecules/cm²',
    Granule.Product.HCHO: 'molecules/cm²',
    Granule.Product.CLDO4: 'fraction',
}

# Cloud fraction is a QA layer: in the catalog, but not a user-facing map product.
QA_PRODUCTS = {Granule.Product.CLDO4}
