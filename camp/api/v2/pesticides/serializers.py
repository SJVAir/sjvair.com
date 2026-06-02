from resticus import serializers

from camp.api.v2.regions.serializers import RegionSerializer


class PesticideRegionSerializer(RegionSerializer):
    exclude = ['boundary']


class ChemicalSerializer(serializers.Serializer):
    fields = (
        ('id', lambda c: c.sqid),
        'chem_code',
        'name',
        'cas_number',
        'dtxsid',
        'iarc_group',
        'categories',
    )


class CommoditySerializer(serializers.Serializer):
    fields = (
        ('id', lambda c: c.sqid),
        'site_code',
        'name',
    )


class ProductSerializer(serializers.Serializer):
    fields = (
        ('id', lambda p: p.sqid),
        'prodno',
        'reg_number',
        'name',
        'fumigant',
        'california_restricted',
    )


class ChemicalDetailSerializer(ChemicalSerializer):
    fields = ChemicalSerializer.fields + (
        ('products', ProductSerializer),
        ('commodities', CommoditySerializer),
    )


class CommodityDetailSerializer(CommoditySerializer):
    fields = CommoditySerializer.fields + (
        ('chemicals', ChemicalSerializer),
        ('products', ProductSerializer),
    )


class ProductDetailSerializer(ProductSerializer):
    fields = ProductSerializer.fields + (
        ('chemicals', ChemicalSerializer),
        ('commodities', CommoditySerializer),
    )


class PesticideUseSerializer(serializers.Serializer):
    fields = (
        ('id', lambda r: r.sqid),
        'year',
        'use_no',
        'comtrs',
        'lbs_chemical',
        'acres_treated',
        'application_date',
        'aerial_ground',
        ('county', PesticideRegionSerializer),
        ('mtrs', PesticideRegionSerializer),
        ('product', ProductSerializer),
        ('chemical', ChemicalSerializer),
        ('commodity', CommoditySerializer),
    )


class PesticideSummarySerializer(serializers.Serializer):
    fields = (
        'year',
        ('chemical', ChemicalSerializer),
        ('commodity', CommoditySerializer),
        'total_lbs',
        'total_acres',
        'application_count',
    )


class PesticideSummaryResponseSerializer(serializers.Serializer):
    fields = (
        ('region', PesticideRegionSerializer),
        ('data', {'fields': PesticideSummarySerializer.fields}),
        'count',
    )


class PesticideNoticeSerializer(serializers.Serializer):
    fields = (
        ('id', lambda n: n.sqid),
        'application_id',
        'comtrs',
        ('county', PesticideRegionSerializer),
        'point',
        'scheduled_application',
        'treated_amount',
        'treated_units',
        'application_method',
        ('chemicals', ChemicalSerializer),
        ('products', ProductSerializer),
    )
