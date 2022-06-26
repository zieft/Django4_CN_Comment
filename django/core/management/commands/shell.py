import os
import select
import sys
import traceback

from django.core.management import BaseCommand, CommandError
from django.utils.datastructures import OrderedSet


class Command(BaseCommand):
    help = (
        "Runs a Python interactive interpreter. Tries to use IPython or "
        "bpython, if one of them is available. Any standard input is executed "
        "as code."
    )

    requires_system_checks = []
    shells = ['ipython', 'bpython', 'python']

    def add_arguments(self, parser):
        parser.add_argument(
            '--no-startup', action='store_true',
            help='When using plain Python, ignore the PYTHONSTARTUP environment variable and ~/.pythonrc.py script.',
        )
        parser.add_argument(
            '-i', '--interface', choices=self.shells,
            help='Specify an interactive interpreter interface. Available options: "ipython", "bpython", and "python"',
        )
        parser.add_argument(
            '-c', '--command',
            help='Instead of opening an interactive shell, run a command as Django and exit.',
        )

    def ipython(self, options):
        from IPython import start_ipython
        start_ipython(argv=[])

    def bpython(self, options):
        import bpython
        bpython.embed()

    def python(self, options):
        import code

        # Set up a dictionary to serve as the environment for the shell.
        # 初始化一个字典，储存（虚拟环境）变量
        imported_objects = {}

        # We want to honor both $PYTHONSTARTUP and .pythonrc.py, so follow system
        # conventions and get $PYTHONSTARTUP first then .pythonrc.py.
        if not options['no_startup']:
            for pythonrc in OrderedSet([os.environ.get("PYTHONSTARTUP"), os.path.expanduser('~/.pythonrc.py')]):
                if not pythonrc:
                    continue
                if not os.path.isfile(pythonrc):
                    continue
                with open(pythonrc) as handle:
                    pythonrc_code = handle.read()
                # Match the behavior of the cpython shell where an error in
                # PYTHONSTARTUP prints an exception and continues.
                try:
                    exec(compile(pythonrc_code, pythonrc, 'exec'), imported_objects)
                except Exception:
                    traceback.print_exc()

        # By default, this will set up readline to do tab completion and to read and
        # write history to the .python_history file, but this can be overridden by
        # $PYTHONSTARTUP or ~/.pythonrc.py.
        # 代码运行到这里的时候，产生交互的方式
        try:
            hook = sys.__interactivehook__
        except AttributeError:
            # Match the behavior of the cpython shell where a missing
            # sys.__interactivehook__ is ignored.
            pass
        else:
            try:
                hook()
            except Exception:
                # Match the behavior of the cpython shell where an error in
                # sys.__interactivehook__ prints a warning and the exception
                # and continues.
                print('Failed calling sys.__interactivehook__')
                traceback.print_exc()

        # Set up tab completion for objects imported by $PYTHONSTARTUP or
        # ~/.pythonrc.py.
        # 自动补全相关模块
        try:
            import readline
            import rlcompleter
            readline.set_completer(rlcompleter.Completer(imported_objects).complete)
        except ImportError:
            pass

        # Start the interactive interpreter.
        # 进入交互模式
        code.interact(local=imported_objects)

    def handle(self, **options):
        # Execute the command and exit.
        if options['command']: # 先看参数有没有command
            exec(options['command'], globals()) # 执行python！代码，不是shell代码！
            return

        # Execute stdin if it has anything to read and exit.
        # Not supported on Windows due to select.select() limitations.
        # 如果系统不是32位windows，并且，命令输入不是tty（意思是，不是在终端窗口内执行）， 并且 。。。
        if sys.platform != 'win32' and not sys.stdin.isatty() and select.select([sys.stdin], [], [], 0)[0]:
            exec(sys.stdin.read(), globals())
            return

        # 用户可以通过--interface 参数来指定 特定的交互模式
        # 就是上面提到的三种 ipython, bpython和python
        available_shells = [options['interface']] if options['interface'] else self.shells

        for shell in available_shells:
            # 用户如果不指定-i， 则循环遍历['ipython', 'bpython', 'python']
            # 看看哪一个是可用的
            try:
                # getattr(self, shell)的意思，调取self的shell方法
                # 比如第一层循环时，shell的值是ipython，那么则是执行Command.ipython方法
                # ipython方法需要传入一个参数options，后面的括号就是调用方法时传入的参数
                return getattr(self, shell)(options)
                # 小技巧，getattr函数可以在遍历中使用，用于组合不同的类及方法。
            except ImportError:
                pass
        raise CommandError("Couldn't import {} interface.".format(shell))
