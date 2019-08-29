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


def dir(*paths):
    if not paths[0].startswith(os.sep):
        paths = (os.getcwd(),) + paths
    return os.path.abspath(os.path.join(*paths))


def mkdir(path):
    path = dir(path)
    if not os.path.exists(path):
        os.makedirs(path)
    return path


def assets(*paths):
    return dir('assets', *paths)


@invoke.task()
def styles(ctx):
    compiled_css = sass.compile(
        filename=assets('sass/style.sass'),
        include_paths=(assets('sass'), dir('node_modules')),
        output_style='compressed',
    )
    mkdir('dist/css')
    with open(dir('dist/css/style.css'), 'w') as f:
        f.write(compiled_css)


@invoke.task
def collectstatic(ctx):
    ctx.run('python manage.py collectstatic --noinput', pty=True)


def vue(ctx, name):
    command = f'''yarn build \
        --mode production \
        --no-clean \
        --formats umd-min \
        --target lib \
        --name {name} \
        --dest {dir('./dist/js')} \
        {assets(f'./{name}/main.js')}
    '''
    ctx.run(command, pty=True, warn=False)


@invoke.task()
def build(ctx):
    styles(ctx)
    vue(ctx, 'map')
    collectstatic(ctx)


@invoke.task()
def watch(ctx):
    server = livereload.Server(watcher=GlobWatcher())
    server.watch(dir('./assets/img/'), lambda: collectstatic(ctx))
    server.watch(assets('js'), lambda: collectstatic(ctx))
    server.watch(assets('sass'), lambda: [styles(ctx), collectstatic(ctx)])
    server.watch(assets('map/**'), lambda: [vue(ctx, 'map'), collectstatic(ctx)])
    server.watch(dir('./dist/lib/'), lambda: collectstatic(ctx))
    server.serve()
