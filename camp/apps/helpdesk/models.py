from django.db import models
from django.urls import reverse

from django_jsonform.models.fields import ArrayField
from django_sqids import SqidsField
from model_utils import Choices
from model_utils.fields import StatusField
from model_utils.models import TimeStampedModel
from prose.fields import RichTextField

from . import managers


class Category(models.Model):
    sqid = SqidsField(real_field_name='id')
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100)
    order = models.PositiveIntegerField(default=0)

    objects = managers.CategoryQuerySet.as_manager()

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        return reverse('helpdesk:category-detail', kwargs={
            'sqid': self.sqid,
            'slug': self.slug
        })

    class Meta:
        ordering = ['order']
        verbose_name_plural = 'Categories'


class Article(TimeStampedModel):
    STATUS = Choices('draft', 'published')

    sqid = SqidsField(real_field_name='id')
    title = models.CharField(max_length=255)
    slug = models.SlugField(max_length=255, help_text='This is used in the generating the URL.')
    status = StatusField(db_index=True, help_text='Drafts are not displayed publicly on the website, but can be accessed by staff users directly.')
    is_featured = models.BooleanField(default=False, help_text='Featured articles are displayed with prominence.')
    category = models.ForeignKey('helpdesk.Category',
        blank=True,
        null=True,
        related_name='articles',
        on_delete=models.SET_NULL
    )
    content = RichTextField(blank=True, default='')

    related_articles = models.ManyToManyField('self', blank=True)
    related_terms = models.ManyToManyField('helpdesk.Term', blank=True)

    objects = managers.ArticleQuerySet.as_manager()

    def __str__(self):
        return self.title

    def get_absolute_url(self):
        return reverse('helpdesk:article-detail', kwargs={
            'sqid': self.sqid,
            'slug': self.slug
        })

    class Meta:
        ordering = ['-is_featured', 'title']


class Term(TimeStampedModel):
    STATUS = Choices('draft', 'published')

    sqid = SqidsField(real_field_name='id')
    name = models.CharField(max_length=100)
    slug = models.SlugField(max_length=100, help_text='This is used in the generating the URL.')
    status = StatusField(db_index=True, help_text='Drafts are not displayed publicly on the website.')
    definition = RichTextField()
    synonyms = ArrayField(models.CharField(max_length=100), blank=True, default=list)

    related_terms = models.ManyToManyField('self', blank=True)
    related_articles = models.ManyToManyField('helpdesk.Article',
        through=Article.related_terms.through,
        related_name='+',
        blank=True
    )

    objects = managers.TermQuerySet.as_manager()

    def __str__(self):
        return self.name

    def get_absolute_url(self):
        path = reverse('helpdesk:glossary')
        return f'{path}#{self.slug}'

    class Meta:
        ordering = ['name', '-modified']
