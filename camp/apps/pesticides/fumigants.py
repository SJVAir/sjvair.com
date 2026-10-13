"""
Which products are fumigants. CDPR flags fumigants per product
registration (PRODUCT.fumigant_sw) and misses re-registrations -- the 2021
Telone products carry no flag. So an active ingredient counts as a fumigant
when almost all of its reported pounds, across every loaded year, came from
CDPR-flagged products or field fumigation (aer_gnd_ind 'F'); a product is a
fumigant when CDPR flags it or it contains one. Across all years rather than
per year, so no product flips between years as its use shifts.
"""
from django.db import connection, transaction
from django.db.models import Q, Sum

from camp.apps.pesticides.models import Chemical, PesticideUse, Product

FUMIGANT_MIN_LBS = 100
FUMIGANT_MIN_SHARE = 0.9
FUMIGANT = Chemical.Category.FUMIGANT


def fumigant_chemical_ids():
    rows = (
        PesticideUse.objects.filter(chemical__isnull=False)
        .order_by()
        .values('chemical')
        .annotate(
            total=Sum('lbs_chemical'),
            fumigant=Sum('lbs_chemical', filter=Q(product__fumigant=True) | Q(aerial_ground='F')),
        )
    )
    return {
        r['chemical'] for r in rows
        if (r['total'] or 0) >= FUMIGANT_MIN_LBS and (r['fumigant'] or 0) >= FUMIGANT_MIN_SHARE * r['total']
    }


@transaction.atomic
def classify_fumigants():
    ids = list(fumigant_chemical_ids())
    table = Chemical._meta.db_table
    with connection.cursor() as cursor:
        cursor.execute(
            f"UPDATE {table} SET categories = array_remove(categories, %s) "
            "WHERE %s = ANY(categories) AND NOT (id = ANY(%s))",
            [FUMIGANT, FUMIGANT, ids],
        )
        cursor.execute(
            f"UPDATE {table} SET categories = array_append(COALESCE(categories, '{{}}'), %s) "
            "WHERE id = ANY(%s) AND NOT (%s = ANY(COALESCE(categories, '{}')))",
            [FUMIGANT, ids, FUMIGANT],
        )
    by_ingredient = Product.objects.filter(product_chemicals__chemical__in=ids).values('pk')
    Product.objects.filter(is_fumigant=True).update(is_fumigant=False)
    Product.objects.filter(Q(fumigant=True) | Q(pk__in=by_ingredient)).update(is_fumigant=True)
    return {
        'chemicals': len(ids),
        'products': Product.objects.filter(is_fumigant=True).count(),
        'added': Product.objects.filter(is_fumigant=True, fumigant=False).count(),
    }
