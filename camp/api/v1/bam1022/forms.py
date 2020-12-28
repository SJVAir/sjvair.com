from django import forms

Time: 2020-06-11 19:00:00
ConcRT(ug/m3): +00002.9
ConcHR(ug/m3): -00000.0
ConcS(ug/m3): -00000.0
Flow(lpm): +16.61
WS(m/s): 00.0
WD(Deg): 000
AT(C): +029.0
RH(%): 030
BP(mmHg): 749.9
FT(C): +034.8
FRH(%): 016
Status: 00000

class BAM1022EntryForm(forms.Form):
    time = forms.DateTimeField()
    conc_rt = models.DecimalField(default=0, max_digits=6, decimal_places=1)
    conc_hr = models.DecimalField(default=0, max_digits=6, decimal_places=1)
    conc_s = models.DecimalField(default=0, max_digits=6, decimal_places=1)
    flow = models.DecimalField(default=0, max_digits=4, decimal_places=2)
    ws = models.DecimalField(default=0, max_digits=3, decimal_places=1)
    wd = models.IntegerField(default=0)
    at = models.DecimalField(default=0, max_digits=4, decimal_places=1)
    rh = models.IntegerField(default=0)
    bp = models.DecimalField(default=0, max_digits=4, decimal_places=1)
    ft = models.DecimalField(default=0, max_digits=4, decimal_places=1)
    frh = models.IntegerField(default=0)
