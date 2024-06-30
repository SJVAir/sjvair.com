from django.db import models


class CategoryQuerySet(models.QuerySet):
    def count_articles(self):
        return self.annotate(
            article_count=models.Count('articles',
                queryset=self.model.articles.rel.related_model.objects.published()
            )
        )

    def populated(self):
        return self.count_articles().filter(article_count__gt=0)


class ArticleQuerySet(models.QuerySet):
    def published(self):
        return self.filter(
            status=self.model.STATUS.published
        )

    def featured(self):
        return self.filter(is_featured=True)


class TermQuerySet(models.QuerySet):
    def published(self):
        return self.filter(
            status=self.model.STATUS.published
        )
