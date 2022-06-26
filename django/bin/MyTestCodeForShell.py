# 交互解释器的实验
##### 为了使这个交互窗口可以调用用户定义的Model从而操作数据库，
##### 需要先添加下面几行
##### 这个方法在python原生解释器中也有效
import os
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "Change_to_your——project_name.settings")
django.setup()
##### 完


import code
import sys
import traceback  # 用于异常的跟踪


def python():
    # Set up a dictionary to serve as the environment for the shell.
    # 初始化一个字典，储存（虚拟环境）变量
    imported_objects = {}

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
    try:
        import readline
        import rlcompleter
        readline.set_completer(rlcompleter.Completer(imported_objects).complete)
    except ImportError:
        pass

    # Start the interactive interpreter.
    # 进入交互模式
    #################这部分代码是自己添加的########################
    # 可以把本地的变量传给解释器，让其可以直接在解释器中被调用
    imported_objects = {
        "hello": "zieft",

    }

    #################这部分代码是自己添加的########################
    code.interact(local=imported_objects)

# python()函数可以直接在解释器中调用
