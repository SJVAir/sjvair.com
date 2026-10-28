import json

from django.conf import settings
from django.core.validators import RegexValidator
from django.db import models

id_validator = RegexValidator(r'^[A-Za-z0-9_-]{1,64}$', 'Enter a valid document id.')


def measure(value):
    """The size of a JSON value in characters, as the limits count it."""
    return len(json.dumps(value, ensure_ascii=False, separators=(',', ':')))


class SavedDocument(models.Model):
    class Visibility(models.TextChoices):
        PRIVATE = 'private', 'Private'
        LINK = 'link', 'Anyone with the link'
        PUBLIC = 'public', 'Public'

    id = models.CharField(max_length=64, primary_key=True, validators=[id_validator])
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='saved_documents'
    )
    kind = models.CharField(max_length=32)
    name = models.CharField(max_length=100, null=True, blank=True)
    body = models.JSONField(blank=True)
    size = models.IntegerField()
    schema_version = models.IntegerField()
    version = models.IntegerField(default=0)
    visibility = models.CharField(
        max_length=8, choices=Visibility.choices, default=Visibility.PRIVATE
    )
    share_token = models.CharField(max_length=64, unique=True, null=True, blank=True)
    copied_from = models.CharField(max_length=64, null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)
    sharing_disabled = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True, db_index=True)

    def __str__(self):
        return self.id


class DocumentChange(models.Model):
    """One save's changes: a list of {schema_version, change} entries."""

    document = models.ForeignKey(SavedDocument, on_delete=models.CASCADE, related_name='changes')
    version = models.IntegerField()
    entries = models.JSONField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=['document', 'version'], name='documents_change_unique')
        ]


class DocumentSnapshot(models.Model):
    class Reason(models.TextChoices):
        SCHEMA = 'schema', 'Schema change'
        DAILY = 'daily', 'Daily'
        CONFLICT = 'conflict', 'Conflict'

    document = models.ForeignKey(
        SavedDocument, on_delete=models.CASCADE, related_name='snapshots'
    )
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='document_snapshots'
    )
    version = models.IntegerField()
    schema_version = models.IntegerField()
    name = models.CharField(max_length=100, null=True, blank=True)
    body = models.JSONField(blank=True)
    size = models.IntegerField()
    reason = models.CharField(max_length=8, choices=Reason.choices)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)


class DocumentProfile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='document_profile'
    )
    display_name = models.CharField(max_length=60, null=True, blank=True)
    sharing_blocked = models.BooleanField(default=False)


class BlockedBuild(models.Model):
    build_id = models.CharField(max_length=64, unique=True)
    note = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.build_id


class PurgedDocument(models.Model):
    id = models.CharField(max_length=64, primary_key=True)
    owner = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='purged_documents'
    )
    purged_at = models.DateTimeField(auto_now_add=True)
