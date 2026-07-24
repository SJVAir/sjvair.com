from django.db import models
from django.utils.translation import gettext_lazy as _

from django_sqids import SqidsField, shuffle_alphabet

from camp.apps.regions.models import Region


class CalHeatScore(models.Model):
    class Score(models.IntegerChoices):
        LOW = 0, _('Low')
        MILD = 1, _('Mild')
        MODERATE = 2, _('Moderate')
        HIGH = 3, _('High')
        SEVERE = 4, _('Severe')

    sqid = SqidsField(alphabet=shuffle_alphabet('calheatscore.CalHeatScore'))
    region = models.ForeignKey(
        'regions.Region',
        verbose_name=_('ZIP Code'),
        on_delete=models.CASCADE,
        related_name='heat_scores',
        limit_choices_to={'type': Region.Type.ZIPCODE},
    )
    date = models.DateField(_('Date'))
    score = models.IntegerField(_('Score'), choices=Score.choices)
    updated_at = models.DateTimeField(_('Updated At'), auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['region', 'date'], name='unique_calheatscore_region_date'),
        ]
        ordering = ['-date']
        verbose_name = _('CalHeatScore')
        verbose_name_plural = _('CalHeatScore Records')

    def __str__(self):
        return f'{self.region.external_id} — {self.date} ({self.get_score_display()})'
