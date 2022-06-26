from asgiref.local import Local

from django.conf import settings as django_settings
from django.utils.functional import cached_property


class ConnectionProxy:
    """Proxy for accessing a connection object's attributes."""
    """
        代理模式
        假如我们将这个类实例化出来：
        connection = ConnectionProxy(connections, alias)
        其中，connections是django.db.utils.ConnectionHandler的一个实例
        alias就是项目setting中配置数据库的别名，默认为"default"
        然后，根据__getattr__()的定义，有
        connection.cursor()  等价于  connections["default"].cursor()
    """

    def __init__(self, connections, alias):
        self.__dict__['_connections'] = connections
        self.__dict__['_alias'] = alias

    def __getattr__(self, item):
        return getattr(self._connections[self._alias], item)

    def __setattr__(self, name, value):
        return setattr(self._connections[self._alias], name, value)

    def __delattr__(self, name):
        return delattr(self._connections[self._alias], name)

    def __contains__(self, key):
        # 这个魔法函数用于定义迭代方法，决定调用for items in connection是，对什么进行迭代
        return key in self._connections[self._alias]

    def __eq__(self, other):
        return self._connections[self._alias] == other


class ConnectionDoesNotExist(Exception):
    pass


class BaseConnectionHandler:
    settings_name = None  # 在被django.db.utils.ConnectionHandler继承后，值变为"DATABASES"
    exception_class = ConnectionDoesNotExist
    thread_critical = False

    def __init__(self, settings=None):
        # 初始化时settings为None，后由settings()方法配置
        self._settings = settings
        # Local is a drop-in replacement for thread，是python内建的类
        # 暂时不知道是干什么的
        self._connections = Local(self.thread_critical)

    @cached_property  # 将一个只需要self参数的方法转换成属性的形式
    def settings(self):
        # 将当前的self._settings作为参数传给configure_settings()
        # self._settings在self被初始化的时候为None
        self._settings = self.configure_settings(self._settings)
        # 这里返回的就是用户配置文件中关于DATABASES的信息（字典）
        return self._settings

    def configure_settings(self, settings):
        if settings is None:  # self刚初始化的时候，settings为None
            # django_settings是django.conf.LazySettings的实例
            # settings变量里保存的就是从配置文件中读出的关于DATABASES的信息
            settings = getattr(django_settings, self.settings_name)
        return settings

    def create_connection(self, alias):
        # 父类没有实现，相当于一个接口
        raise NotImplementedError('Subclasses must implement create_connection().')

    def __getitem__(self, alias):
        # connections[alias]就会调用这个魔法函数
        try:
            return getattr(self._connections, alias)
        except AttributeError:
            if alias not in self.settings:  # 会调用上面的settings()方法
                # 这里的self.settings看起来像是在调用self的settings属性
                # 然而往上面看，有一个被@cached_property装饰的方法settings()
                # 事实上，这里调用的是这个方法
                raise self.exception_class(f"The connection '{alias}' doesn't exist.")
        conn = self.create_connection(alias)
        setattr(self._connections, alias, conn)
        return conn

    def __setitem__(self, key, value):
        setattr(self._connections, key, value)

    def __delitem__(self, key):
        delattr(self._connections, key)

    def __iter__(self):
        return iter(self.settings)

    def all(self):
        return [self[alias] for alias in self]
