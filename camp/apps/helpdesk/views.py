from django.db.models import OuterRef, Subquery, Prefetch

import vanilla

from .models import Category, Article, Term


class Home(vanilla.TemplateView):
    template_name = 'helpdesk/home.html'

    def get_context_data(self, **kwargs):
        return super().get_context_data(
            feature_list=self.get_featured_articles(),
            category_list=self.get_categories(),
            glossary=self.get_glossary(),
            **kwargs
        )

    def get_featured_articles(self):
        return Article.objects.published().featured()

    def get_categories(self):
        subquery = Subquery(Article.objects
            .published()
            .filter(category_id=OuterRef('category_id'))
            .values_list('pk', flat=True)[:5]
        )
        article_prefetch = Prefetch('articles',
            queryset=Article.objects.filter(pk__in=subquery)
        )
        queryset = (Category.objects
            .populated()
            .prefetch_related(article_prefetch)
        )
        return queryset

    def get_glossary(self):
        return Term.objects.published()


class CategoryDetail(vanilla.DetailView):
    model = Category
    template_name = 'helpdesk/category-detail.html'


class ArticleDetail(vanilla.DetailView):
    model = Article
    template_name = 'helpdesk/article-detail.html'


class Glossary(vanilla.ListView):
    model = Term
    template_name = 'helpdesk/glossary.html'
    
    def get_queryset(self):
        return super().get_queryset().published()


class Search(vanilla.TemplateView):
    template_name = 'helpdesk/search.html'
