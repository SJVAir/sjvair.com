from django.db import models


class ArticleQuerySet(models.QuerySet):
    def published(self):
        return self.filter(
            status=self.model.STATUS.published
        ).order_by('is_featured', 'title')


class TermQuerySet(models.QuerySet):
    def published(self):
        return self.filter(
            status=self.model.STATUS.published
        ).order_by('name')
