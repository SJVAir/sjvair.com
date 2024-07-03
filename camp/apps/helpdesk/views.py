from django.db.models import Count, OuterRef, Prefetch, Q, Subquery
from django.shortcuts import redirect

import vanilla

from .forms import SearchForm
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
    lookup_field = 'sqid'
    lookup_url_kwarg = 'sqid'
    model = Category
    template_name = 'helpdesk/category-detail.html'

    def get_queryset(self):
        return self.model.objects.populated()

    def get_context_data(self, **kwargs):
        return super().get_context_data(
            articles=self.get_articles(),
            categories=self.get_categories(),
            **kwargs
        )

    def get_articles(self):
        queryset = Article.objects.published()
        queryset = queryset.filter(category__pk=self.object.pk)
        return queryset

    def get_categories(self):
        queryset = Category.objects.populated()
        return queryset


class ArticleDetail(vanilla.DetailView):
    lookup_field = 'sqid'
    lookup_url_kwarg = 'sqid'
    model = Article
    template_name = 'helpdesk/article-detail.html'

    def get_queryset(self):
        queryset = super().get_queryset().published()
        queryset = queryset.prefetch_related(
            Prefetch('category__articles', queryset=Article.objects.published())
        )
        return queryset

    def get_context_data(self, **kwargs):
        return super().get_context_data(
            related_articles=self.get_related_articles(),
            related_terms=self.get_related_terms(),
            **kwargs
        )

    def get_related_articles(self):
        queryset = Article.objects.published()
        queryset = queryset.filter(related_articles=self.object)
        return queryset

    def get_related_terms(self):
        queryset = Term.objects.published()
        queryset = queryset.filter(related_articles=self.object)
        return queryset


class Glossary(vanilla.ListView):
    model = Term
    template_name = 'helpdesk/glossary.html'
    
    def get_queryset(self):
        queryset = super().get_queryset().published()
        queryset = queryset.prefetch_related(
            Prefetch('related_articles', queryset=Article.objects.published()),
            Prefetch('related_terms', queryset=Term.objects.published()),
        )
        queryset = queryset.annotate(
            related_articles_count=Count('related_articles', queryset=Article.objects.published()),
            related_terms_count=Count('related_terms', queryset=Term.objects.published()),
        )
        queryset = queryset.order_by('name')
        return queryset


class Search(vanilla.TemplateView):
    template_name = 'helpdesk/search.html'

    def get(self, request):
        self.form = SearchForm(request.GET)
        if self.form.is_valid():
            self.query = self.get_search_query()
            return super().get(request)
        return redirect('helpdesk:home')

    def get_context_data(self, **kwargs):
        return super().get_context_data(
            form=self.form,
            search_query=self.query,
            article_results=Article.objects.search(self.query),
            term_results=Term.objects.search(self.query),
        )

    def get_search_query(self):
        return self.form.cleaned_data['q']
