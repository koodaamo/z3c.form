import zope.component
import zope.interface
import zope.location
import zope.schema.interfaces
from zope.contentprovider.interfaces import IContentProvider

from z3c.form.field import FieldWidgets
from z3c.form import interfaces
from z3c.form.interfaces import IContentProviders


class BaseProvider(object):
    __slots__ = ('position')

lookup_ = BaseProvider()


class ContentProviders(dict):
    zope.interface.implements(IContentProviders)

    def __init__(self, names=None):
        super(ContentProviders, self).__init__()
        if names is not None:
            for position, name in enumerate(names):
                self[name] = lookup_
                self[name].position = position

    def __setitem__(self, key, value):
        factory = ContentProviderFactory(factory=value, name=key)
        super(ContentProviders, self).__setitem__(key, factory)


class ContentProviderFactory(object):

    def __init__(self, factory, name):
        self.factory = factory
        self.name = name
        self.position = getattr(factory, 'position', None)

    def __call__(self, manager):
        if self.factory != lookup_:
            contentProvider = self.factory(manager.content, manager.request, manager.form)
        else:
            contentProvider = zope.component.getMultiAdapter((manager.content, manager.request, manager.form),
                                                             IContentProvider, self.name)
        return contentProvider


class FieldWidgetsAndProviders(FieldWidgets):
    zope.component.adapts(
        interfaces.IFieldsAndContentProviderForm, interfaces.IFormLayer, zope.interface.Interface)
    zope.interface.implementsOnly(interfaces.IWidgets)

    def update(self):
        super(FieldWidgetsAndProviders, self).update()

        uniqueOrderedKeys = self._data_keys
        for name in self.form.contentProviders:
            factory = self.form.contentProviders[name]
            contentProvider = factory(self)
            shortName = name
            contentProvider.update()
            uniqueOrderedKeys.insert(factory.position, shortName)
            self._data_values.insert(factory.position, contentProvider)
            self._data[shortName] = contentProvider
            zope.location.locate(contentProvider, self, shortName)
            # allways ensure that we add all keys and keep the order given from
            # button items
            self._data_keys = uniqueOrderedKeys
