from django.db import models


class HealthCheckManager(models.Manager):
    def evaluate(self, monitor, hour):
        """
        Fetches entries for a given monitor + hour + entry_model,
        runs the evaluation, and creates/updates a HealthCheck.
        """

        try:
            health_check = self.get(monitor_id=monitor.pk, hour=hour)
        except self.model.DoesNotExist:
            health_check = self.model(monitor_id=monitor.pk, hour=hour)

        health_check.evaluate()
        health_check.save()
        return health_check
