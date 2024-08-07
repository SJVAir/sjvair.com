# Generated by Django 4.2.11 on 2024-06-29 00:54

from django.db import migrations, models
import django.db.models.deletion
import django.utils.timezone
import django_jsonform.models.fields
import model_utils.fields
import prose.fields


class Migration(migrations.Migration):

    initial = True

    dependencies = [
    ]

    operations = [
        migrations.CreateModel(
            name='Article',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, editable=False, verbose_name='created')),
                ('modified', model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, editable=False, verbose_name='modified')),
                ('title', models.CharField(max_length=255)),
                ('slug', models.SlugField(help_text='This is used in the generating the URL.', max_length=255)),
                ('status', model_utils.fields.StatusField(choices=[('draft', 'draft'), ('published', 'published')], db_index=True, default='draft', help_text='Drafts are not displayed publicly on the website, but can be accessed by staff users directly.', max_length=100, no_check_for_status=True)),
                ('is_featured', models.BooleanField(default=False, help_text='Featured articles are displayed with prominence.')),
                ('content', prose.fields.RichTextField(blank=True, default='')),
            ],
            options={
                'ordering': ['is_featured', 'title'],
            },
        ),
        migrations.CreateModel(
            name='Category',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=100)),
                ('slug', models.SlugField(max_length=100)),
                ('order', models.PositiveIntegerField(default=0)),
            ],
            options={
                'verbose_name_plural': 'Categories',
                'ordering': ['order'],
            },
        ),
        migrations.CreateModel(
            name='Term',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('created', model_utils.fields.AutoCreatedField(default=django.utils.timezone.now, editable=False, verbose_name='created')),
                ('modified', model_utils.fields.AutoLastModifiedField(default=django.utils.timezone.now, editable=False, verbose_name='modified')),
                ('name', models.CharField(max_length=100)),
                ('slug', models.SlugField(help_text='This is used in the generating the URL.', max_length=100)),
                ('status', model_utils.fields.StatusField(choices=[('draft', 'draft'), ('published', 'published')], db_index=True, default='draft', help_text='Drafts are not displayed publicly on the website.', max_length=100, no_check_for_status=True)),
                ('definition', prose.fields.RichTextField()),
                ('synonyms', django_jsonform.models.fields.ArrayField(base_field=models.CharField(max_length=100), blank=True, default=list, size=None)),
                ('related_articles', models.ManyToManyField(blank=True, related_name='+', to='helpdesk.article')),
                ('related_terms', models.ManyToManyField(blank=True, to='helpdesk.term')),
            ],
            options={
                'ordering': ['name', '-modified'],
            },
        ),
        migrations.AddField(
            model_name='article',
            name='category',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, related_name='articles', to='helpdesk.category'),
        ),
        migrations.AddField(
            model_name='article',
            name='related_articles',
            field=models.ManyToManyField(blank=True, to='helpdesk.article'),
        ),
        migrations.AddField(
            model_name='article',
            name='related_terms',
            field=models.ManyToManyField(blank=True, to='helpdesk.term'),
        ),
    ]
