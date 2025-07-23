import copy

from django.conf import settings
from django.test import override_settings, TestCase, RequestFactory
from django.urls import reverse

from django_huey import get_queue

from . import endpoints
from camp.utils.test import debug, get_response_data
from camp.utils.test.helpers import queue_immediate_mode
from camp.utils.tasks import add

current_time = endpoints.CurrentTime.as_view()
task_status = endpoints.TaskStatus.as_view()


class EndpointTests(TestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def test_get_current_time(self):
        url = reverse('api:v1:current-time')
        request = self.factory.get(url)
        response = current_time(request)
        assert response.status_code == 200

        content = get_response_data(response)
        assert isinstance(content, int)

    def test_task_status_not_found(self):
        kwargs = {'task_id': 'non-existent-id'}
        url = reverse('api:v2:task-status', kwargs=kwargs)
        request = self.factory.get(url)
        response = task_status(request, **kwargs)
        content = get_response_data(response)

        assert response.status_code == 200
        assert content == {'data': None}

    @queue_immediate_mode(False)
    def test_task_status_returns_result(self):
        # Get the queue anmd execute a task.
        queue = get_queue('primary')
        result = add(3, 4)
        task = queue.dequeue()
        returned = queue.execute(task)

        # Build the request and fetch the status
        kwargs = {'task_id': result.id}
        url = reverse('api:v2:task-status', kwargs=kwargs)
        request = self.factory.get(url)
        response = task_status(request, **kwargs)
        content = get_response_data(response)

        assert response.status_code == 200
        assert content['data'] == returned == 7

    @queue_immediate_mode(False)
    def test_task_status_preserve_flag(self):
        # Enqueue and manually execute the task
        queue = get_queue('primary')
        result = add(19, 87)
        task = queue.dequeue()
        returned = queue.execute(task)

        # Call the view
        kwargs = {'task_id': result.id}
        url = reverse('api:v2:task-status', kwargs=kwargs)
        request = self.factory.get(url)
        response = task_status(request, **kwargs)
        content = get_response_data(response)

        assert response.status_code == 200

        # Confirm result is still stored
        preserved = queue.result(result.id)
        assert content['data'] == preserved == returned == 106
