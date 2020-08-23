from datetime import timedelta

from django.core.management.base import BaseCommand
from django.utils import timezone

from camp.apps.purple import api
from camp.apps.purple.models import PurpleAir
from camp.apps.purple.tasks import periodic_purple_import

device_list = {
    42353: 'WMV47W0OP5U83JWZ',
    42465: 'LORO5GCYP7MVS44X',
    42463: '74DLG32REJFGS9KW',
    42319: '215KE4B48DYNZB9D',
    42367: '0UCY781DESV1GPR2',
    42461: 'Y6TU720YF68JR10U',
    42469: 'AIM5OPHUCKRE606J',
    42321: '3KIY6QQ6FII9WXNU',
    42487: 'NTCMTVOM3B57GGMH',
    42505: 'CJXGI6TILUDROACU',
    42475: 'H6GHJ7BNL16GTU56',
    42467: 'YVEOR4SXMDTBF52Q',
    42257: 'G1BMSE7I5CXS5AZ9',
    42261: 'LYI1XNT58ZALMK36',
    40989: 'QFHQDSO4RBBIA7BI',
    42451: '0W49EBAFKUOA6517',
    42441: 'FQ9D4SUI4DWPPBEE',
    42443: 'K7O9Z72AMJSUSKS6',
    42445: 'MCNRP56CCS7C5VJE',
    41719: 'GKA2178VDJORUG0F',
    42355: 'JTOVAL21F0ERXWF9',
    42433: 'IBA4PJZF64C8NI1O',
    42337: 'QJRI3PBICN9Q4P4Y',
    42255: 'OXQTRVXOGKUWBEX3',
    41715: '15ZCH10XQJV9SRRZ',
    42327: 'R2R3JBU4SLM7AIS7',
    42357: 'IZ4D0RJBOB8WSHU3',
    42333: 'X6WTQQHIA4VT2E3M',
    42291: 'QGBILX03CSFYZM46',
    42299: 'J6ZF9235R9EN9G1U',
    8852: 'LHKQYQ5XXO9AZL2A',
    8866: '75IF8VSBIU3PR8RD',
    8896: '9F43ESB2K4VZVBAX',
    8870: 'EO9LV052HHSJFEM6',
    8908: '6J68Y3SG0YEA9HLJ',
}


class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        for purple_id, key in device_list.items():
            PurpleAir.objects.get_or_create(
                purple_id=purple_id,
                defaults={
                    'data': [{'THINGSPEAK_PRIMARY_ID_READ_KEY': key}]
                }
            )
        periodic_purple_import()
