from django.db import models

from django_jsonform.models.fields import ArrayField
from django_sqids import SqidsField
from model_utils import Choices
from model_utils.fields import StatusField
from model_utils.models import TimeStampedModel
from prose.fields import RichTextField


class Category(models.Model):
    sqid = SqidsField(real_field_name='id')
    name = models.CharField(max_length=100)
    slug = models.SlugField()
    order = models.PositiveIntegerField(default=0)

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['order']
        verbose_name_plural = 'Categories'


class Article(TimeStampedModel):
    STATUS = Choices('draft', 'published')

    sqid = SqidsField(real_field_name='id')
    title = models.CharField(max_length=255)
    slug = models.SlugField()
    status = StatusField(db_index=True)
    is_featured = models.BooleanField(default=False)
    category = models.ForeignKey('helpdesk.Category',
        blank=True,
        null=True,
        related_name='articles',
        on_delete=models.SET_NULL
    )
    content = RichTextField(blank=True, default='')

    related_articles = models.ManyToManyField('self', blank=True)
    related_terms = models.ManyToManyField('helpdesk.Term', blank=True)

    def __str__(self):
        return self.title

    class Meta:
        ordering = ['is_featured', 'title']


class Term(TimeStampedModel):
    STATUS = Choices('draft', 'published')

    sqid = SqidsField(real_field_name='id')
    name = models.CharField(max_length=100)
    slug = models.SlugField()
    definition = RichTextField()
    synonyms = ArrayField(models.CharField(max_length=100), blank=True)

    related_terms = models.ManyToManyField('self', blank=True)
    related_articles = models.ManyToManyField('helpdesk.Article',
        through=Article.related_terms.through,
        related_name='+',
        blank=True
    )

    def __str__(self):
        return self.name

    class Meta:
        ordering = ['name', '-modified']
