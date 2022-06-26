import argparse
import cgi
import mimetypes
import os
import posixpath
import shutil
import stat
import tempfile
from importlib import import_module
from urllib.request import urlretrieve

import django
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.core.management.utils import handle_extensions
from django.template import Context, Engine
from django.utils import archive
from django.utils.version import get_docs_version


class TemplateCommand(BaseCommand):
    """
    Copy either a Django application layout template or a Django project
    layout template into the specified directory.

    :param style: A color style object (see django.core.management.color).
    :param app_or_project: The string 'app' or 'project'.
    :param name: The name of the application or project.
    :param directory: The directory to which the template should be copied.
    :param options: The additional variables passed to project or app templates
    """
    requires_system_checks = []
    # The supported URL schemes
    url_schemes = ['http', 'https', 'ftp']
    # Rewrite the following suffixes when determining the target filename.
    rewrite_template_suffixes = (
        # Allow shipping invalid .py files without byte-compilation.
        ('.py-tpl', '.py'),
    )

    def add_arguments(self, parser):
        parser.add_argument('name', help='Name of the application or project.')
        parser.add_argument('directory', nargs='?', help='Optional destination directory')
        parser.add_argument('--template', help='The path or URL to load the template from.')
        parser.add_argument(
            '--extension', '-e', dest='extensions',
            action='append', default=['py'],
            help='The file extension(s) to render (default: "py"). '
                 'Separate multiple extensions with commas, or use '
                 '-e multiple times.'
        )
        parser.add_argument(
            '--name', '-n', dest='files',
            action='append', default=[],
            help='The file name(s) to render. Separate multiple file names '
                 'with commas, or use -n multiple times.'
        )
        parser.add_argument(
            '--exclude', '-x',
            action='append', default=argparse.SUPPRESS, nargs='?', const='',
            help=(
                'The directory name(s) to exclude, in addition to .git and '
                '__pycache__. Can be used multiple times.'
            ),
        )

    def handle(self, app_or_project, name, target=None, **options):
        self.app_or_project = app_or_project
        self.a_or_an = 'an' if app_or_project == 'app' else 'a'
        self.paths_to_remove = []
        self.verbosity = options['verbosity']
        # 校验工程名称是否合法
        self.validate_name(name)

        # if some directory is given, make sure it's nicely expanded

        if target is None:  # target的是指定目录，不指定则在当前目录下生成name project
            top_dir = os.path.join(os.getcwd(), name)
            try:
                os.makedirs(top_dir)  # 在当前目录生成name路径
            except FileExistsError:
                raise CommandError("'%s' already exists" % top_dir)
            except OSError as e:  # 比如权限不够之类的导致无法创建路径
                raise CommandError(e)  #
        else:  # 如果指定了目录，就在指定目录
            top_dir = os.path.abspath(os.path.expanduser(target))  # 将指定目标转换成绝对路径
            if app_or_project == 'app':
                self.validate_name(os.path.basename(top_dir), 'directory')
            if not os.path.exists(top_dir):  # 判断此路径是否存在，如果不存在提示 请先创建目标路径
                raise CommandError("Destination directory '%s' does not "
                                   "exist, please create it first." % top_dir)

        extensions = tuple(handle_extensions(options['extensions']))  # 处理扩展名
        extra_files = []  # 额外的文件
        excluded_directories = ['.git', '__pycache__']  # 排除掉git文件和缓存文件
        for file in options['files']:
            extra_files.extend(map(lambda x: x.strip(), file.split(',')))
        if exclude := options.get('exclude'):
            for directory in exclude:
                excluded_directories.append(directory.strip())
        if self.verbosity >= 2:  # verbosity作为可选参数传入，打印一些详情信息，参见BaseCommand类
            self.stdout.write(
                'Rendering %s template files with extensions: %s'
                % (app_or_project, ', '.join(extensions))
            )
            self.stdout.write(
                'Rendering %s template files with filenames: %s'
                % (app_or_project, ', '.join(extra_files))
            )
        # 根据app还是project，给下面的context初始化一些变量命
        base_name = '%s_name' % app_or_project
        base_subdir = '%s_template' % app_or_project
        base_directory = '%s_directory' % app_or_project
        camel_case_name = 'camel_case_%s_name' % app_or_project
        camel_case_value = ''.join(x for x in name.title() if x != '_')

        context = Context({
            **options,
            base_name: name,
            base_directory: top_dir,
            camel_case_name: camel_case_value,
            'docs_version': get_docs_version(),
            'django_version': django.__version__,
        }, autoescape=False)

        # Setup a stub settings environment for template rendering
        if not settings.configured:
            settings.configure()
            django.setup()  # 非常重要！

        template_dir = self.handle_template(options['template'],  # 用户可以通过参数传入template
                                            base_subdir)  # 用户如果没有指定template，django就
        # 去conf/project_template找manage.py-tpl
        prefix_length = len(template_dir) + 1  # 模板绝对路径的长度，
        # 这种写法可以处理不同的os下绝对路径的长度区别

        for root, dirs, files in os.walk(template_dir):
            # 遍历template文件夹下的所有文件
            path_rest = root[prefix_length:]  # path_rest最终的值为 "/project_name"
            relative_dir = path_rest.replace(base_name, name)  # 渲染的项目文件夹有两层带有项目名的文件夹
            if relative_dir:
                target_dir = os.path.join(top_dir, relative_dir)
                os.makedirs(target_dir, exist_ok=True)

            for dirname in dirs[:]:
                if 'exclude' not in options: # 用户可以通过参数排除某些目录不被渲染
                    if dirname.startswith('.') or dirname == '__pycache__':
                        dirs.remove(dirname)
                elif dirname in excluded_directories:
                    dirs.remove(dirname)

            for filename in files:
                # 遍历下列文件
                # ['manage.py-tpl']
                # ['__init__.py-tpl', 'urls.py-tpl', 'asgi.py-tpl', 'wsgi.py-tpl', 'settings.py-tpl']
                if filename.endswith(('.pyo', '.pyc', '.py.class')):
                    # Ignore some files as they cause various breakages.
                    continue
                old_path = os.path.join(root, filename)     # 模板路径
                new_path = os.path.join(                    # 新建的工程路径
                    top_dir, relative_dir, filename.replace(base_name, name)
                )
                for old_suffix, new_suffix in self.rewrite_template_suffixes:
                    # 这个循环就是把".py-tpl"替换为'.py'
                    if new_path.endswith(old_suffix):
                        new_path = new_path[:-len(old_suffix)] + new_suffix
                        break  # Only rewrite once

                if os.path.exists(new_path):
                    # 判断路径下是否已经存在当前待渲染的文件，如过有则抛出下面的异常
                    raise CommandError(
                        "%s already exists. Overlaying %s %s into an existing "
                        "directory won't replace conflicting files." % (
                            new_path, self.a_or_an, app_or_project,
                        )
                    )

                # Only render the Python files, as we don't want to
                # accidentally render Django templates files
                if new_path.endswith(extensions) or filename in extra_files:
                    with open(old_path, encoding='utf-8') as template_file:
                        content = template_file.read()
                    # 使用模板引擎进行渲染django/template/engine.py
                    template = Engine().from_string(content)
                    content = template.render(context)
                    with open(new_path, 'w', encoding='utf-8') as new_file:
                        new_file.write(content)
                else:
                    shutil.copyfile(old_path, new_path) # 将一个文件的内容拷贝到另一个文件中，目标文件无需存在

                if self.verbosity >= 2:
                    self.stdout.write('Creating %s' % new_path)
                try:
                    # 拷贝权限，前提是目标文件存在，不然会报错。将src文件权限复制至dst文件。文件内容，所有者和组不受影响
                    shutil.copymode(old_path, new_path)
                    self.make_writeable(new_path)
                except OSError:
                    self.stderr.write(
                        "Notice: Couldn't set permission bits on %s. You're "
                        "probably using an uncommon filesystem setup. No "
                        "problem." % new_path, self.style.NOTICE)

        if self.paths_to_remove:
            if self.verbosity >= 2:
                self.stdout.write('Cleaning up temporary files.')
            for path_to_remove in self.paths_to_remove:
                if os.path.isfile(path_to_remove):
                    os.remove(path_to_remove)
                else:
                    shutil.rmtree(path_to_remove)

    def handle_template(self, template, subdir):
        """
        Determine where the app or project templates are.
        Use django.__path__[0] as the default because the Django install
        directory isn't known.
        """
        if template is None:
            return os.path.join(django.__path__[0], 'conf', subdir)
        else:
            if template.startswith('file://'):
                template = template[7:]
            expanded_template = os.path.expanduser(template)
            expanded_template = os.path.normpath(expanded_template)
            if os.path.isdir(expanded_template):
                return expanded_template
            if self.is_url(template):
                # downloads the file and returns the path
                absolute_path = self.download(template)
            else:
                absolute_path = os.path.abspath(expanded_template)
            if os.path.exists(absolute_path):
                return self.extract(absolute_path)

        raise CommandError("couldn't handle %s template %s." %
                           (self.app_or_project, template))

    def validate_name(self, name, name_or_dir='name'):
        if name is None:
            raise CommandError('you must provide {an} {app} name'.format(
                an=self.a_or_an,
                app=self.app_or_project,
            ))
        # Check it's a valid directory name.
        """
        A string is considered a valid identifier if it only contains alphanumeric letters (a-z) and (0-9),
        or underscores (_). A valid identifier cannot start with a number, or contain any spaces.
        """
        if not name.isidentifier():
            raise CommandError(
                "'{name}' is not a valid {app} {type}. Please make sure the "
                "{type} is a valid identifier.".format(
                    name=name,
                    app=self.app_or_project,
                    type=name_or_dir,
                )
            )
        # Check it cannot be imported.
        try:
            import_module(name)
        except ImportError:
            pass
        else:
            raise CommandError(
                "'{name}' conflicts with the name of an existing Python "
                "module and cannot be used as {an} {app} {type}. Please try "
                "another {type}.".format(
                    name=name,
                    an=self.a_or_an,
                    app=self.app_or_project,
                    type=name_or_dir,
                )
            )

    def download(self, url):
        """
        Download the given URL and return the file name.
        """

        def cleanup_url(url):
            tmp = url.rstrip('/')
            filename = tmp.split('/')[-1]
            if url.endswith('/'):
                display_url = tmp + '/'
            else:
                display_url = url
            return filename, display_url

        prefix = 'django_%s_template_' % self.app_or_project
        tempdir = tempfile.mkdtemp(prefix=prefix, suffix='_download')
        self.paths_to_remove.append(tempdir)
        filename, display_url = cleanup_url(url)

        if self.verbosity >= 2:
            self.stdout.write('Downloading %s' % display_url)
        try:
            the_path, info = urlretrieve(url, os.path.join(tempdir, filename))
        except OSError as e:
            raise CommandError("couldn't download URL %s to %s: %s" %
                               (url, filename, e))

        used_name = the_path.split('/')[-1]

        # Trying to get better name from response headers
        content_disposition = info.get('content-disposition')
        if content_disposition:
            _, params = cgi.parse_header(content_disposition)
            guessed_filename = params.get('filename') or used_name
        else:
            guessed_filename = used_name

        # Falling back to content type guessing
        ext = self.splitext(guessed_filename)[1]
        content_type = info.get('content-type')
        if not ext and content_type:
            ext = mimetypes.guess_extension(content_type)
            if ext:
                guessed_filename += ext

        # Move the temporary file to a filename that has better
        # chances of being recognized by the archive utils
        if used_name != guessed_filename:
            guessed_path = os.path.join(tempdir, guessed_filename)
            shutil.move(the_path, guessed_path)
            return guessed_path

        # Giving up
        return the_path

    def splitext(self, the_path):
        """
        Like os.path.splitext, but takes off .tar, too
        """
        base, ext = posixpath.splitext(the_path)
        if base.lower().endswith('.tar'):
            ext = base[-4:] + ext
            base = base[:-4]
        return base, ext

    def extract(self, filename):
        """
        Extract the given file to a temporary directory and return
        the path of the directory with the extracted content.
        """
        prefix = 'django_%s_template_' % self.app_or_project
        tempdir = tempfile.mkdtemp(prefix=prefix, suffix='_extract')
        self.paths_to_remove.append(tempdir)
        if self.verbosity >= 2:
            self.stdout.write('Extracting %s' % filename)
        try:
            archive.extract(filename, tempdir)
            return tempdir
        except (archive.ArchiveException, OSError) as e:
            raise CommandError("couldn't extract file %s to %s: %s" %
                               (filename, tempdir, e))

    def is_url(self, template):
        """Return True if the name looks like a URL."""
        if ':' not in template:
            return False
        scheme = template.split(':', 1)[0].lower()
        return scheme in self.url_schemes

    def make_writeable(self, filename):
        """
        Make sure that the file is writeable.
        Useful if our source is read-only.
        """
        if not os.access(filename, os.W_OK):
            st = os.stat(filename)
            new_permissions = stat.S_IMODE(st.st_mode) | stat.S_IWUSR
            os.chmod(filename, new_permissions)
