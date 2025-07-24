from django_huey import task


@task()
def add(x, y):
    '''
        A task used for testing the queue.
    '''
    return x + y
