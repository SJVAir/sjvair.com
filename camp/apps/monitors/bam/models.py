import time
import uuid

from django.db import models

from resticus.encoders import JSONEncoder

from camp.apps.monitors.models import Monitor, Entry

# Time,
# ConcRT(ug/m3),
# ConcHR(ug/m3),
# ConcS(ug/m3),
# Flow(lpm),
# WS(m/s),
# WD(Deg),
# AT(C),
# RH(%),
# BP(mmHg),
# FT(C),
# FRH(%),
# Status

class BAM1022(Monitor):
    auth_key = models.UUIDField(default=uuid.uuid4)

    class Meta:
        verbose_name = 'BAM 1022'
