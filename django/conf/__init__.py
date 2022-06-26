"""
Settings and configuration for Django.

Read values from the module specified by the DJANGO_SETTINGS_MODULE environment
variable, and then from django.conf.global_settings; see the global_settings.py
for a list of all possible variables.
"""

import importlib
import os
import time
import traceback
import warnings
from pathlib import Path

import django
from django.conf import global_settings
from django.core.exceptions import ImproperlyConfigured
from django.utils.deprecation import RemovedInDjango50Warning
from django.utils.functional import LazyObject, empty

# manage.py中的环境变量
# 这个环境变量决定交互式环境中可否import 用户定义的Modell
ENVIRONMENT_VARIABLE = "DJANGO_SETTINGS_MODULE"

# RemovedInDjango50Warning
USE_DEPRECATED_PYTZ_DEPRECATED_MSG = (
    'The USE_DEPRECATED_PYTZ setting, and support for pytz timezones is '
    'deprecated in favor of the stdlib zoneinfo module. Please update your '
    'code to use zoneinfo and remove the USE_DEPRECATED_PYTZ setting.'
)

USE_L10N_DEPRECATED_MSG = (
    'The USE_L10N setting is deprecated. Starting with Django 5.0, localized '
    'formatting of data will always be enabled. For example Django will '
    'display numbers and dates using the format of the current locale.'
)


class SettingsReference(str):
    """
    String subclass which references a current settings value. It's treated as
    the value in memory but serializes to a settings.NAME attribute reference.
    """

    def __new__(self, value, setting_name):
        return str.__new__(self, value)

    def __init__(self, value, setting_name):
        self.setting_name = setting_name


class LazySettings(LazyObject):
    """
    A lazy proxy for either global Django settings or a custom settings object.
    The user can manually configure settings prior to using them. Otherwise,
    Django uses the settings module pointed to by DJANGO_SETTINGS_MODULE.
    """

    def _setup(self, name=None):
        """
        Load the settings module pointed to by the environment variable. This
        is used the first time settings are needed, if the user hasn't
        configured settings manually.
        """
        # 获取ENVIRONMENT_VARIABLE环境变量
        # 就是manage.py中配置的第一个环境变量，"DJANGO_SETTINGS_MODULE"
        settings_module = os.environ.get(ENVIRONMENT_VARIABLE)
        # 在非django shell中import Model，会抛出下面的异常
        # 原因settings_module的值为None
        # not None就是True
        if not settings_module:
            desc = ("setting %s" % name) if name else "settings"
            raise ImproperlyConfigured(
                "Requested %s, but settings are not configured. "
                "You must either define the environment variable %s "
                "or call settings.configure() before accessing settings."
                % (desc, ENVIRONMENT_VARIABLE))

        self._wrapped = Settings(settings_module)

    def __repr__(self):
        # Hardcode the class name as otherwise it yields 'Settings'.
        if self._wrapped is empty:
            return '<LazySettings [Unevaluated]>'
        return '<LazySettings "%(settings_module)s">' % {
            'settings_module': self._wrapped.SETTINGS_MODULE,
        }

    def __getattr__(self, name):
        """Return the value of a setting and cache it in self.__dict__."""
        # empty就是一个空对象
        # 正常创建的django项目，从django shell读取self._wrapped都会是Setting对象
        # 如果wrapped是empty，则会调用_setup()来设置Setting的属性
        if self._wrapped is empty:
            self._setup(name)
        val = getattr(self._wrapped, name)

        # Special case some settings which require further modification.
        # This is done here for performance reasons so the modified value is cached.
        # 强调要配置秘钥，用户的settings里不能把SECRET_KEY给干掉
        if name in {'MEDIA_URL', 'STATIC_URL'} and val is not None:
            val = self._add_script_prefix(val)
        elif name == 'SECRET_KEY' and not val:
            raise ImproperlyConfigured("The SECRET_KEY setting must not be empty.")

        self.__dict__[name] = val
        return val

    def __setattr__(self, name, value):
        """
        Set the value of setting. Clear all cached values if _wrapped changes
        (@override_settings does this) or clear single values when set.
        """
        if name == '_wrapped':
            self.__dict__.clear()
        else:
            self.__dict__.pop(name, None)
        super().__setattr__(name, value)

    def __delattr__(self, name):
        """Delete a setting and clear it from cache if needed."""
        super().__delattr__(name)
        self.__dict__.pop(name, None)

    def configure(self, default_settings=global_settings, **options):
        """
        Called to manually configure the settings. The 'default_settings'
        parameter sets where to retrieve any unspecified values from (its
        argument must support attribute access (__getattr__)).
        """
        if self._wrapped is not empty:
            raise RuntimeError('Settings already configured.')
        holder = UserSettingsHolder(default_settings)
        for name, value in options.items():
            if not name.isupper():
                raise TypeError('Setting %r must be uppercase.' % name)
            setattr(holder, name, value)
        self._wrapped = holder

    @staticmethod
    def _add_script_prefix(value):
        """
        Add SCRIPT_NAME prefix to relative paths.

        Useful when the app is being served at a subpath and manually prefixing
        subpath to STATIC_URL and MEDIA_URL in settings is inconvenient.
        """
        # Don't apply prefix to absolute paths and URLs.
        if value.startswith(('http://', 'https://', '/')):
            return value
        from django.urls import get_script_prefix
        return '%s%s' % (get_script_prefix(), value)

    @property
    def configured(self):
        """Return True if the settings have already been configured."""
        return self._wrapped is not empty

    @property
    def USE_L10N(self):
        stack = traceback.extract_stack()
        # Show a warning if the setting is used outside of Django.
        # Stack index: -1 this line, -2 the caller.
        filename, _, _, _ = stack[-2]
        if not filename.startswith(os.path.dirname(django.__file__)):
            warnings.warn(
                USE_L10N_DEPRECATED_MSG,
                RemovedInDjango50Warning,
                stacklevel=2,
            )
        return self.__getattr__('USE_L10N')

    # RemovedInDjango50Warning.
    @property
    def _USE_L10N_INTERNAL(self):
        # Special hook to avoid checking a traceback in internal use on hot
        # paths.
        return self.__getattr__('USE_L10N')


class Settings:
    def __init__(self, settings_module):
        # settings_module参数传入的是用户定义的Settings.py
        # 他是manage.py中最先定义的那组环境变量  DJANGO_SETTING_MODULE 的值
        # 即 'XXXXproject.settings'

        # update this dict from global settings (but only for ALL_CAPS settings)
        for setting in dir(global_settings):
            # 这个循环就是将global_settings里所有的属性值读出来，并作为Settings对象的属性保存起来
            # 虽然Global_settings里面没有写__file__， '__loader__'等内建属性，但是dir的时候会有这些。
            # dir() 可以将global_settings里的所有属性读出来，并保存在列表中
            if setting.isupper():
                # 我们感兴趣的属性都是用大写字母定义的
                # 不感兴趣的，比如python内建的属性__builtins__等等，都可以直接忽略掉
                setattr(self, setting, getattr(global_settings, setting))

        # store the settings module in case someone later cares
        self.SETTINGS_MODULE = settings_module

        # importlib是python自建模块
        # 这句就是把用户的settings文件作为一个模块给引入进来
        # 经过测试，传入的参数只能是'XXXXproject.settings'而不能是 settings的绝对路径
        # 没想明白为什么
        # mod可以使用.来获取settings.py里的所有属性
        mod = importlib.import_module(self.SETTINGS_MODULE)

        tuple_settings = (
            'ALLOWED_HOSTS',
            "INSTALLED_APPS",
            "TEMPLATE_DIRS",
            "LOCALE_PATHS",
        )
        self._explicit_settings = set()
        for setting in dir(mod):
            if setting.isupper():
                # 这个if就是只认大写的属性，这就是为什么settings里面都要用大写作为变量名
                setting_value = getattr(mod, setting)  # 比如setting为DEBUG时，这个写法等价于mod.DEBUG

                if (setting in tuple_settings and
                    not isinstance(setting_value, (list, tuple))):
                    # 限定属性只能为列表或者元组
                    raise ImproperlyConfigured("The %s setting must be a list or a tuple." % setting)
                setattr(self, setting, setting_value)
                # 这里用用户的属性值覆盖global的属性值
                self._explicit_settings.add(setting)

        if self.USE_TZ is False and not self.is_overridden('USE_TZ'):
            warnings.warn(
                'The default value of USE_TZ will change from False to True '
                'in Django 5.0. Set USE_TZ to False in your project settings '
                'if you want to keep the current default behavior.',
                category=RemovedInDjango50Warning,
            )

        if self.is_overridden('USE_DEPRECATED_PYTZ'):
            warnings.warn(USE_DEPRECATED_PYTZ_DEPRECATED_MSG, RemovedInDjango50Warning)

        if hasattr(time, 'tzset') and self.TIME_ZONE:
            # When we can, attempt to validate the timezone. If we can't find
            # this file, no check happens and it's harmless.
            zoneinfo_root = Path('/usr/share/zoneinfo')
            zone_info_file = zoneinfo_root.joinpath(*self.TIME_ZONE.split('/'))
            if zoneinfo_root.exists() and not zone_info_file.exists():
                raise ValueError("Incorrect timezone setting: %s" % self.TIME_ZONE)
            # Move the time zone info into os.environ. See ticket #2315 for why
            # we don't do this unconditionally (breaks Windows).
            os.environ['TZ'] = self.TIME_ZONE
            time.tzset()

        if self.is_overridden('USE_L10N'):
            warnings.warn(USE_L10N_DEPRECATED_MSG, RemovedInDjango50Warning)

    def is_overridden(self, setting):
        return setting in self._explicit_settings

    def __repr__(self):
        return '<%(cls)s "%(settings_module)s">' % {
            'cls': self.__class__.__name__,
            'settings_module': self.SETTINGS_MODULE,
        }


class UserSettingsHolder:
    """Holder for user configured settings."""
    # SETTINGS_MODULE doesn't make much sense in the manually configured
    # (standalone) case.
    SETTINGS_MODULE = None

    def __init__(self, default_settings):
        """
        Requests for configuration variables not in this class are satisfied
        from the module specified in default_settings (if possible).
        """
        self.__dict__['_deleted'] = set()
        self.default_settings = default_settings

    def __getattr__(self, name):
        if not name.isupper() or name in self._deleted:
            raise AttributeError
        return getattr(self.default_settings, name)

    def __setattr__(self, name, value):
        self._deleted.discard(name)
        if name == 'USE_L10N':
            warnings.warn(USE_L10N_DEPRECATED_MSG, RemovedInDjango50Warning)
        super().__setattr__(name, value)
        if name == 'USE_DEPRECATED_PYTZ':
            warnings.warn(USE_DEPRECATED_PYTZ_DEPRECATED_MSG, RemovedInDjango50Warning)

    def __delattr__(self, name):
        self._deleted.add(name)
        if hasattr(self, name):
            super().__delattr__(name)

    def __dir__(self):
        return sorted(
            s for s in [*self.__dict__, *dir(self.default_settings)]
            if s not in self._deleted
        )

    def is_overridden(self, setting):
        deleted = (setting in self._deleted)
        set_locally = (setting in self.__dict__)
        set_on_default = getattr(self.default_settings, 'is_overridden', lambda s: False)(setting)
        return deleted or set_locally or set_on_default

    def __repr__(self):
        return '<%(cls)s>' % {
            'cls': self.__class__.__name__,
        }


settings = LazySettings()
