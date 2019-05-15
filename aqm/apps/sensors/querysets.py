from django.db import models
from django.db.models import Case, When, Count, Value, BooleanField

# blogs = Blog.objects.annotate(Max('entry__added'))
# values = tuple([(blog.id, blog.max__entry__added) for blog in blogs])

# # Possible avoided by using a .group_by()
# entries = Entry.objects.extra(where=['(blog_id, added) IN %s' % (values,)])

# blog_dict = dict([(b.id, b) for b in blogs])
# entries = list(entries)
# for entry in entries:
#     entry._blog_cache = blog_dict[entry.blog_id]


class SensorQuerySet(models.QuerySet):
    def fetch_latest_reading(self):
        pass


class SensorDataQuerySet(models.QuerySet):
    def processed(self):
        return self.filter(processed=True)
