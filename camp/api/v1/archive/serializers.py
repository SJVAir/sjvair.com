from resticus import serializers


class EntryArchiveSerializer(serializers.Serializer):
    fields = ('month', 'year', ('url', lambda archive: archive.get_csv_url()))
