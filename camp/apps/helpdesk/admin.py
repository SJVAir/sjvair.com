from django.contrib import admin

from .models import Category, Article, Term


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ['name', 'order']
    list_editable = ['order']
    prepopulated_fields = {'slug': ['name']}


@admin.register(Article)
class ArticleAdmin(admin.ModelAdmin):
    filter_horizontal = ['related_articles', 'related_terms']
    list_display = ['title', 'category', 'modified']
    list_filter = ['category', 'modified']
    prepopulated_fields = {'slug': ['title']}
    raw_id_fields = ['category']
    search_fields = ['sqid__exact', 'title', 'content']


@admin.register(Term)
class TermAdmin(admin.ModelAdmin):
    list_display = ['name', 'modified']
    prepopulated_fields = {'slug': ['name']}
    filter_horizontal = ['related_articles', 'related_terms']
    search_fields = ['sqid__exact', 'name', 'definition']
