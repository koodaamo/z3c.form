##############################################################################
#
# Copyright (c) 2006 Zope Foundation and Contributors.
# All Rights Reserved.
#
# This software is subject to the provisions of the Zope Public License,
# Version 2.1 (ZPL).  A copy of the ZPL should accompany this distribution.
# THIS SOFTWARE IS PROVIDED "AS IS" AND ANY AND ALL EXPRESS OR IMPLIED
# WARRANTIES ARE DISCLAIMED, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF TITLE, MERCHANTABILITY, AGAINST INFRINGEMENT, AND FITNESS
# FOR A PARTICULAR PURPOSE.
#
##############################################################################
"""Field Implementation

$Id$
"""
__docformat__ = "reStructuredText"
import zope.component
import zope.interface
import zope.location
import zope.schema.interfaces

from z3c.form import interfaces, util
from z3c.form.widget import AfterWidgetUpdateEvent


def _initkw(keepReadOnly=(), omitReadOnly=False, **defaults):
    return keepReadOnly, omitReadOnly, defaults


class WidgetFactories(dict):

    def __init__(self):
        super(WidgetFactories, self).__init__()
        self.default = None

    def __getitem__(self, key):
        if key not in self and self.default:
            return self.default
        return super(WidgetFactories, self).__getitem__(key)

    def get(self, key, default=None):
        if key not in self and self.default:
            return self.default
        return super(WidgetFactories, self).get(key, default)


class WidgetFactoryProperty(object):

    def __get__(self, inst, klass):
        if not hasattr(inst, '_widgetFactories'):
            inst._widgetFactories = WidgetFactories()
        return inst._widgetFactories

    def __set__(self, inst, value):
        if not hasattr(inst, '_widgetFactories'):
            inst._widgetFactories = WidgetFactories()
        inst._widgetFactories.default = value


class Field(object):
    """Field implementation."""
    zope.interface.implements(interfaces.IField)

    widgetFactory = WidgetFactoryProperty()

    def __init__(self, field, name=None, prefix='', mode=None, interface=None):
        self.field = field
        if name is None:
            name = field.__name__
        assert name
        self.__name__ = util.expandPrefix(prefix) + name
        self.prefix = prefix
        self.mode = mode
        if interface is None:
            interface = field.interface
        self.interface = interface

    def __repr__(self):
        return '<%s %r>' % (self.__class__.__name__, self.__name__)


class Fields(util.SelectionManager):
    """Field manager."""
    zope.interface.implements(interfaces.IFields)
    managerInterface = interfaces.IFields

    def __init__(self, *args, **kw):
        keepReadOnly, omitReadOnly, defaults = _initkw(**kw)

        fields = []
        for arg in args:
            if isinstance(arg, zope.interface.interface.InterfaceClass):
                for name, field in zope.schema.getFieldsInOrder(arg):
                    fields.append((name, field, arg))

            elif zope.schema.interfaces.IField.providedBy(arg):
                name = arg.__name__
                if not name:
                        raise ValueError("Field has no name")
                fields.append((name, arg, arg.interface))

            elif self.managerInterface.providedBy(arg):
                for form_field in arg.values():
                    fields.append(
                        (form_field.__name__, form_field, form_field.interface))

            elif isinstance(arg, Field):
                fields.append((arg.__name__, arg, arg.interface))

            else:
                raise TypeError("Unrecognized argument type", arg)

        self._data_keys = []
        self._data_values = []
        self._data = {}
        for name, field, iface in fields:
            if isinstance(field, Field):
                form_field = field
            else:
                if field.readonly:
                    if omitReadOnly and (name not in keepReadOnly):
                        continue
                customDefaults = defaults.copy()
                if iface is not None:
                    customDefaults['interface'] = iface
                form_field = Field(field, **customDefaults)
                name = form_field.__name__

            if name in self._data:
                raise ValueError("Duplicate name", name)

            self._data_values.append(form_field)
            self._data_keys.append(name)
            self._data[name] = form_field


    def select(self, *names, **kwargs):
        """See interfaces.IFields"""
        prefix = kwargs.pop('prefix', None)
        interface = kwargs.pop('interface', None)
        assert len(kwargs) == 0
        if prefix:
            names = [util.expandPrefix(prefix) + name for name in names]
        mapping = self
        if interface is not None:
            mapping = dict([(field.field.__name__, field)
                            for field in self.values()
                            if field.field.interface is interface])
        return self.__class__(*[mapping[name] for name in names])


    def omit(self, *names, **kwargs):
        """See interfaces.IFields"""
        prefix = kwargs.pop('prefix', None)
        interface = kwargs.pop('interface', None)
        assert len(kwargs) == 0
        if prefix:
            names = [util.expandPrefix(prefix) + name for name in names]
        fields = [field for field in self.values()]
        return self.__class__(
            *[field for name, field in self.items()
              if not ((name in names and interface is None) or
                      (field.field.interface is interface and
                       field.field.__name__ in names)) ])


class FieldWidgets(util.Manager):
    """Widget manager for IFieldWidget."""

    zope.component.adapts(
        interfaces.IFieldsForm, interfaces.IFormLayer, zope.interface.Interface)
    zope.interface.implementsOnly(interfaces.IWidgets)

    prefix = 'widgets.'
    mode = interfaces.INPUT_MODE
    errors = ()
    ignoreContext = False
    ignoreRequest = False
    ignoreReadonly = False

    def __init__(self, form, request, content):
        super(FieldWidgets, self).__init__()
        self.form = form
        self.request = request
        self.content = content

    def validate(self, data):
        fields = self.form.fields.values()

        # Step 1: Collect the data for the various schemas
        schemaData = {}
        for field in fields:
            schema = field.interface
            if schema is None:
                continue

            fieldData = schemaData.setdefault(schema, {})
            if field.__name__ in data:
                fieldData[field.field.__name__] = data[field.__name__]

        # Step 2: Validate the individual schemas and collect errors
        errors = ()
        for schema, fieldData in schemaData.items():
            validator = zope.component.getMultiAdapter(
                (self.content, self.request, self.form, schema, self),
                interfaces.IManagerValidator)
            errors += validator.validate(fieldData)

        return errors

    def update(self):
        """See interfaces.IWidgets"""
        # Create a unique prefix.
        prefix = util.expandPrefix(self.form.prefix)
        prefix += util.expandPrefix(self.prefix)
        # Walk through each field, making a widget out of it.
        for field in self.form.fields.values():
            # Step 1: Determine the mode of the widget.
            mode = self.mode
            if field.mode is not None:
                mode = field.mode
            elif field.field.readonly and not self.ignoreReadonly:
                    mode = interfaces.DISPLAY_MODE
            elif not self.ignoreContext:
                # If we do not have enough permissions to write to the
                # attribute, then switch to display mode.
                dm = zope.component.getMultiAdapter(
                    (self.content, field.field), interfaces.IDataManager)
                if not dm.canWrite():
                    mode = interfaces.DISPLAY_MODE
            # Step 2: Get the widget for the given field.
            factory = field.widgetFactory.get(mode)
            if factory is not None:
                widget = factory(field.field, self.request)
            else:
                widget = zope.component.getMultiAdapter(
                    (field.field, self.request), interfaces.IFieldWidget)
            # Step 3: Set the prefix for the widget
            shortName = field.__name__
            widget.name = prefix + shortName
            widget.id = (prefix + shortName).replace('.', '-')
            # Step 4: Set the context
            widget.context = self.content
            zope.interface.alsoProvides(widget, interfaces.IContextAware)
            # Step 5: Set the form
            widget.form = self.form
            zope.interface.alsoProvides(widget, interfaces.IFormAware)
            # Step 6: Set some variables
            widget.ignoreContext = self.ignoreContext
            widget.ignoreRequest = self.ignoreRequest
            # Step 7: Set the mode of the widget
            widget.mode = mode
            # Step 8: Update the widget
            widget.update()
            zope.event.notify(AfterWidgetUpdateEvent(widget))
            # Step 9: Add the widget to the manager
            self._data_keys.append(shortName)
            self._data_values.append(widget)
            self._data[shortName] = widget
            zope.location.locate(widget, self, shortName)

    def extract(self):
        """See interfaces.IWidgets"""
        data = {}
        self.errors = ()
        for name, widget in self.items():
            if widget.mode == interfaces.DISPLAY_MODE:
                continue
            raw = widget.extract()
            value = widget.field.missing_value
            try:
                if raw is not interfaces.NOVALUE:
                    value = interfaces.IDataConverter(widget).toFieldValue(raw)
                zope.component.getMultiAdapter(
                    (self.content,
                     self.request,
                     self.form,
                     getattr(widget, 'field', None),
                     widget),
                    interfaces.IValidator).validate(value)
            except (zope.schema.ValidationError, ValueError), error:
                view = zope.component.getMultiAdapter(
                    (error, self.request, widget, widget.field,
                     self.form, self.content), interfaces.IErrorViewSnippet)
                view.update()
                widget.error = view
                self.errors += (view,)
            else:
                name = widget.__name__
                data[name] = value
        self.errors += self.validate(data)
        return data, self.errors
