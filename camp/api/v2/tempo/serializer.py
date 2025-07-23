from resticus import serializers


class O3totSerializer(serializers.Serializer):
    fields = {
        'id',
        'timestamp', 
        'file',
    }
    
    
class HchoSerializer(serializers.Serializer):
    fields = {
        'id',
        'timestamp', 
        'file',
    }
    
    
class No2Serializer(serializers.Serializer):
    fields = {
        'id',
        'timestamp', 
        'file',
    }
    