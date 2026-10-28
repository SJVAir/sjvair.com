from django.urls import path

from . import endpoints

app_name = 'documents'

# Fixed paths (profile/, export/, shared/<token>/...) are registered before <id>/, and save
# validation refuses those first segments as ids (save.RESERVED_IDS).
urlpatterns = [
    path('', endpoints.DocumentList.as_view(), name='list'),
    path('profile/', endpoints.DocumentProfileDetail.as_view(), name='profile'),
    path('export/', endpoints.DocumentExport.as_view(), name='export'),
    path(
        'shared/<str:token>/changes/', endpoints.SharedDocumentChanges.as_view(),
        name='shared-changes',
    ),
    path('shared/<str:token>/', endpoints.SharedDocumentDetail.as_view(), name='shared'),
    path('<str:id>/share/', endpoints.DocumentShare.as_view(), name='share'),
    path('<str:id>/credit/', endpoints.DocumentCredit.as_view(), name='credit'),
    path('<str:id>/snapshots/', endpoints.DocumentSnapshotList.as_view(), name='snapshots'),
    path(
        '<str:id>/snapshots/<int:snapshot_id>/', endpoints.DocumentSnapshotDetail.as_view(),
        name='snapshot',
    ),
    path('<str:id>/changes/', endpoints.DocumentChanges.as_view(), name='changes'),
    path('<str:id>/', endpoints.DocumentDetail.as_view(), name='detail'),
]
