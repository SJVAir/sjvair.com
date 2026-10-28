from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import TestCase

from camp.apps.documents.models import (
    DocumentChange,
    DocumentProfile,
    DocumentSnapshot,
    PurgedDocument,
    SavedDocument,
    measure,
)

User = get_user_model()


class DocumentModelTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            'owner@sjvair.com', 'letmein1', full_name='Owner', phone='+15595550101'
        )

    def make(self, id='doc1', **extra):
        fields = dict(
            id=id, owner=self.user, kind='dashboard', body={}, size=2, schema_version=1
        )
        fields.update(extra)
        return SavedDocument.objects.create(**fields)

    def test_id_validator_rejects(self):
        for bad in ['a b', 'x' * 65, '']:
            doc = SavedDocument(
                id=bad, owner=self.user, kind='dashboard', body={}, size=2, schema_version=1
            )
            with self.assertRaises(ValidationError, msg=repr(bad)):
                doc.full_clean()
        SavedDocument(
            id='Ab-_9', owner=self.user, kind='dashboard', body={}, size=2, schema_version=1
        ).full_clean()

    def test_share_token_unique(self):
        self.make('a', share_token='tok')
        with self.assertRaises(IntegrityError), transaction.atomic():
            self.make('b', share_token='tok')
        self.make('c', share_token=None)
        self.make('d', share_token=None)

    def test_user_delete_cascades(self):
        doc = self.make()
        DocumentChange.objects.create(document=doc, version=1, entries=[])
        DocumentSnapshot.objects.create(
            document=doc, owner=self.user, version=1, schema_version=1, name=None,
            body={}, size=2, reason='daily',
        )
        DocumentProfile.objects.create(user=self.user)
        PurgedDocument.objects.create(id='gone', owner=self.user)
        self.user.delete()
        for model in [SavedDocument, DocumentChange, DocumentSnapshot, DocumentProfile, PurgedDocument]:
            self.assertEqual(model.objects.count(), 0, model.__name__)

    def test_measure_counts_characters(self):
        self.assertEqual(measure({'a': 'é'}), len('{"a":"é"}'))
