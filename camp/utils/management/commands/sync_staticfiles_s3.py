import shlex
import subprocess

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    def handle(self, *args, **kwargs):
        if not all((
            getattr(settings, 'AWS_STORAGE_BUCKET_NAME', None),
            getattr(settings, 'AWS_ACCESS_KEY_ID', None),
            getattr(settings, 'AWS_SECRET_ACCESS_KEY', None),
        )):
            raise CommandError('AWS S3 is not configured.')

        command = shlex.split(f'''
            aws s3 sync
            {settings.STATIC_ROOT}
            s3://{settings.AWS_STORAGE_BUCKET_NAME}/{settings.STATICFILES_LOCATION}/
            --acl public-read
            --size-only
        ''')

        print(' '.join(command))

        process = subprocess.Popen(command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            universal_newlines=True
        )

        while True:
            output = process.stdout.readline()
            print(output.strip())
            return_code = process.poll()
            if return_code is not None:
                print('RETURN CODE', return_code)
                # Process has finished, read rest of the output
                for output in process.stdout.readlines():
                    print(output.strip())
                break
