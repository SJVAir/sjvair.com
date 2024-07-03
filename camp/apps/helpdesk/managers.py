from django.contrib.postgres.search import SearchHeadline, SearchQuery, SearchRank, SearchVector
from django.db import models
from django.db.models import F, Value
from django.db.models.functions import Concat


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

    def search(self, query):
        search_query = SearchQuery(query)
        search_vector = SearchVector('title', 'content')
        search_headline = SearchHeadline(
            Concat(F('title'), Value(' '), F('content')),
            query=search_query,
            max_fragments=1,
            start_sel='<span class="highlight">',
            stop_sel='</span>',
        )
        queryset = self.model.objects.published()
        queryset = queryset.annotate(
            search=search_vector,
            rank=SearchRank(search_vector, search_query),
            headline=search_headline,
        )
        queryset = queryset.filter(search=search_query)
        queryset = queryset.order_by("-rank")
        return queryset.distinct('rank', 'pk')


class TermQuerySet(models.QuerySet):
    def published(self):
        return self.filter(
            status=self.model.STATUS.published
        )

    def search(self, query):
        search_query = SearchQuery(query)
        search_vector = (
            SearchVector('name', weight='A')
            + SearchVector('definition', weight='A')
            + SearchVector('synonyms', weight='A')
            + SearchVector('related_terms__name', weight='B')
            + SearchVector('related_terms__definition', weight='B')
        )
        queryset = self.model.objects.published()
        queryset = queryset.annotate(
            search=search_vector,
            rank=SearchRank(search_vector, search_query)
        )
        queryset = queryset.filter(search=search_query)
        queryset = queryset.order_by("-rank")
        return queryset.distinct('rank', 'pk')
