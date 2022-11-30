import glob
import json
import os
import shutil

import delegator
import invoke
import livereload
import sass

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


@invoke.task()
def optimize_images(ctx):
    ctx.run('optimize-images ./public/static/')

@invoke.task()
def styles(ctx):
    compiled_css = sass.compile(
        filename=assets('sass/style.sass'),
        include_paths=(assets('sass'), path('node_modules')),
        output_style='compressed',
    )
    mkdir('dist/css')
    with open(path('dist/css/style.css'), 'w') as f:
        f.write(compiled_css)


@invoke.task
def collectstatic(ctx):
    ctx.run('python manage.py collectstatic --noinput', pty=True)


@invoke.task()
def import_monitor_map(ctx):
    # Copy over monitor map
    ctx.run(f'rm -rf {path("./dist/{monitor-map,widget}")}')
    ctx.run(f'''
        cp -r \
        {path('node_modules/@sjvair/monitor-map/dist/{monitor-map,widget}')} \
        {path('./dist')}
    ''')


@invoke.task()
def build(ctx):
    # Directory prep
    ctx.run('rm -rf ./public/static')
    mkdir(path('dist'))

    import_monitor_map(ctx)
    styles(ctx)
    collectstatic(ctx)
    optimize_images(ctx)


# Some steps in here are no longer needed
@invoke.task()
def watch(ctx):
    server = livereload.Server(watcher=GlobWatcher())
    server.watch(path('./assets/img/'), lambda: collectstatic(ctx))
    server.watch(assets('js/**'), lambda: collectstatic(ctx))
    server.watch(assets('sass/**'), lambda: [styles(ctx), collectstatic(ctx)])
    server.watch(path('./dist/lib/'), lambda: collectstatic(ctx))
    server.serve()
