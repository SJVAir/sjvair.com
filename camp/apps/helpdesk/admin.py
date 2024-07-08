from django.contrib import admin

from .models import Category, Article, Term


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'sqid', 'article_count', 'order']
    list_editable = ['order']
    prepopulated_fields = {'slug': ['name']}

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        queryset = queryset.count_articles()
        return queryset

    def article_count(self, instance):
        return instance.article_count
    article_count.short_description = '# of Articles'


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    filter_horizontal = ['related_articles', 'related_terms']
    list_display = ['title', 'sqid', 'category', 'is_featured', 'status', 'modified']
    list_filter = ['category', 'is_featured', 'status', 'modified']
    prepopulated_fields = {'slug': ['title']}
    raw_id_fields = ['category']
    search_fields = ['sqid__exact', 'title', 'content']


@admin.register(Term)
class TermAdmin(admin.ModelAdmin):
    list_display = ['name', 'sqid', 'status', 'modified']
    list_filter = ['status', 'modified']
    prepopulated_fields = {'slug': ['name']}
    filter_horizontal = ['related_articles', 'related_terms']
    search_fields = ['sqid__exact', 'name', 'definition']
