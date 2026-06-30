import glob
import os

import livereload
import sass

from invoke.tasks import task
from livereload.watcher import Watcher


# https://github.com/lepture/python-livereload/issues/156
class GlobWatcher(Watcher):
    def is_glob_changed(self, path, ignore=None):
        for f in glob.glob(path, recursive=True):
            if self.is_file_changed(f, ignore):
                return True
        return False


def path(*paths):
    if not paths[0].startswith(os.sep):
        paths = (os.getcwd(),) + paths
    return os.path.abspath(os.path.join(*paths))


def mkdir(dirname):
    dirname = path(dirname)
    if not os.path.exists(dirname):
        os.makedirs(dirname)
    return dirname


def assets(*paths):
    return path('assets', *paths)


def import_node_module(ctx, target, destination=None):
    destination = path('dist', destination or os.path.basename(target))
    target = path('node_modules', target)

    ctx.run(f'rm -rf {destination}')
    ctx.run(f'cp -r {target} {destination}')


@task()
def optimize_images(ctx):
    ctx.run('optimize-images ./public/static/')


@task()
def styles(ctx):
    compiled_css = sass.compile(
        filename=assets('sass/style.sass'),
        include_paths=(assets('sass'), path('node_modules')),
        output_style='compressed',
    )
    # Wrap compiled output in a CSS layer so it doesn't
    # override third-party utilities in embedded micro-frontends
    layered_css = f'@layer bulma{{{compiled_css}}}'
    mkdir('dist/css')
    with open(path('dist/css/style.css'), 'w') as f:
        f.write(layered_css)


@task
def collectstatic(ctx):
    ctx.run('python manage.py collectstatic --noinput', pty=True)


@task()
def import_monitor_map(ctx, mode):
    ctx.run(f'bash ./scripts/import-monitor-map.sh {mode}')


@task()
def build(ctx, mode='production'):
    # Directory prep
    ctx.run('rm -rf ./public/static')
    mkdir(path('dist'))

    import_monitor_map(ctx, mode)
    import_node_module(ctx, '@sjvair/web-widget/dist', 'widget')
    styles(ctx)
    collectstatic(ctx)
    optimize_images(ctx)


@task
def release(ctx):
    ctx.run('python manage.py migrate --no-input', pty=True)
    ctx.run('python manage.py sync_staticfiles_s3', pty=True)


# Some steps in here are no longer needed
@task()
def watch(ctx):
    server = livereload.Server(watcher=GlobWatcher())
    server.watch(path('./assets/img/'), lambda: collectstatic(ctx))
    server.watch(assets('js/**'), lambda: collectstatic(ctx))
    server.watch(assets('sass/**'), lambda: [styles(ctx), collectstatic(ctx)])
    server.watch(path('./dist/lib/'), lambda: collectstatic(ctx))
    server.serve()
