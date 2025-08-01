# encoding: utf-8

# This file contains commonly used parts of external libraries. The idea is
# to help in removing helpers from being used as a dependency by many files
# but at the same time making it easy to change for example the json lib
# used.
#
# NOTE:  This file is specificaly created for
# from ckan.common import x, y, z to be allowed
from __future__ import annotations

import logging
from collections.abc import MutableMapping, Iterable

from typing import (
    Any, Optional, TYPE_CHECKING,
    TypeVar, cast, overload, Union)
from typing_extensions import Literal

import flask

from werkzeug.local import Local, LocalProxy

from flask_login import current_user as _cu
from flask_login import login_user as _login_user, logout_user as _logout_user
from flask_babel import (gettext as flask_ugettext,
                         ngettext as flask_ungettext)

import simplejson as json  # type: ignore # noqa
from ckan.config.declaration import Declaration
from ckan.types import Request


if TYPE_CHECKING:
    MutableMapping = MutableMapping[str, Any]
    import ckan.model as model_

SENTINEL = {}

log = logging.getLogger(__name__)

TCurrentUser = Union["model_.User", "model_.AnonymousUser"]
current_user = cast(TCurrentUser, _cu)
login_user = _login_user
logout_user = _logout_user


def streaming_response(data: Iterable[Any],
                       mimetype: str = u'application/octet-stream',
                       with_context: bool = False) -> flask.Response:
    iter_data = iter(data)

    if with_context:
        iter_data = flask.stream_with_context(iter_data)
    resp = flask.Response(iter_data, mimetype=mimetype)

    return resp


def ugettext(*args: Any, **kwargs: Any) -> str:
    return flask_ugettext(*args, **kwargs)


_ = ugettext


def ungettext(*args: Any, **kwargs: Any) -> str:
    return flask_ungettext(*args, **kwargs)


class CKANConfig(MutableMapping):
    u'''Main CKAN configuration object

    This is a dict-like object that also proxies any changes to the
    Flask and Pylons configuration objects.

    The actual `config` instance in this module is initialized in the
    `load_environment` method with the values of the ini file or env vars.

    '''
    store: dict[str, Any]

    def __init__(self, *args: Any, **kwargs: Any):
        self.store = dict()
        self.update(dict(*args, **kwargs))

    def __getitem__(self, key: str):
        return self.store[key]

    def __iter__(self):
        return iter(self.store)

    def __len__(self):
        return len(self.store)

    def __repr__(self):
        return self.store.__repr__()

    def copy(self) -> dict[str, Any]:
        return self.store.copy()

    def clear(self) -> None:
        self.store.clear()
        try:
            flask.current_app.config.clear()
        except RuntimeError:
            pass

    def __setitem__(self, key: str, value: Any):
        self.store[key] = value
        try:
            flask.current_app.config[key] = value
        except RuntimeError:
            pass

    def __delitem__(self, key: str):
        del self.store[key]
        try:
            del flask.current_app.config[key]
        except RuntimeError:
            pass

    def is_declared(self, key: str) -> bool:
        return key in config_declaration

    def get(self, key: str, default: Any = SENTINEL) -> Any:
        """Return the value for key if key is in the config, else default.
        """
        if default is SENTINEL:
            default = None
            if len(config_declaration) and key not in config_declaration:
                log.warning("Option %s is not declared", key)

        return super().get(key, default)


def _get_request():
    return flask.request


class HtmxDetails(object):
    """Object to access htmx properties from the request headers.

    This object will be added to the CKAN `request` object
    as `request.htmx`. It adds properties to easily access
    htmx's request headers defined in
    https://htmx.org/reference/#headers.
    """

    def __init__(self, request: Any):
        self.request = request

    def __bool__(self) -> bool:
        return self.request.headers.get("HX-Request") == "true"

    @property
    def boosted(self) -> bool:
        return self.request.headers.get("HX-Boosted") == "true"

    @property
    def current_url(self) -> str | None:
        return self.request.headers.get("HX-Current-URL")

    @property
    def history_restore_request(self) -> bool:
        return self.request.headers.get("HX-History-Restore-Request") == "true"

    @property
    def prompt(self) -> str | None:
        return self.request.headers.get("HX-Prompt")

    @property
    def target(self) -> str | None:
        return self.request.headers.get("HX-Target")

    @property
    def trigger(self) -> str | None:
        return self.request.headers.get("HX-Trigger")

    @property
    def trigger_name(self) -> str | None:
        return self.request.headers.get("HX-Trigger-Name")


class CKANRequest(LocalProxy[Request]):
    '''CKAN request class.

    This is a subclass of the Flask request object. It adds a new
    `htmx` property to access htmx properties from the request headers.
    '''

    @property
    def htmx(self) -> HtmxDetails:
        return HtmxDetails(self)


def _get_c():
    return flask.g


def _get_session():
    return flask.session


def asbool(obj: Any) -> bool:
    """Convert a string (e.g. 1, true, True) into a boolean.

    Example::

        assert asbool("yes") is True

    """

    if isinstance(obj, str):
        obj = obj.strip().lower()
        if obj in truthy:
            return True
        elif obj in falsy:
            return False
        else:
            raise ValueError(u"String is not true/false: {}".format(obj))
    return bool(obj)


def asint(obj: Any) -> int:
    """Convert a string into an int.

    Example::

        assert asint("111") == 111

    """
    try:
        return int(obj)
    except (TypeError, ValueError):
        raise ValueError(u"Bad integer value: {}".format(obj))


T = TypeVar('T')
SequenceT = TypeVar('SequenceT', "list[Any]", "tuple[Any]")


@overload
def aslist(obj: str,
           sep: Optional[str] = None,
           strip: bool = True) -> list[str]:
    ...


@overload
def aslist(obj: SequenceT,
           sep: Optional[str] = None,
           strip: bool = True) -> SequenceT:
    ...


@overload
def aslist(obj: Literal[None],
           sep: Optional[str] = None,
           strip: bool = True) -> list[str]:
    ...


def aslist(obj: Any, sep: Optional[str] = None, strip: bool = True) -> Any:
    """Convert a space-separated string into a list.

    Example::

        assert aslist("a b c") == ["a", "b", "c"]

    """

    if isinstance(obj, str):
        lst = obj.split(sep)
        if strip:
            lst = [v.strip() for v in lst]
        return lst
    elif isinstance(obj, (list, tuple)):
        return cast(Any, obj)
    elif isinstance(obj, Iterable):
        return list(obj)
    elif obj is None:
        return []
    else:
        return [obj]


def repr_untrusted(danger: Any):
    """
    repr-format danger and truncate e.g. for logging untrusted input
    """
    r = repr(danger)
    rtrunc = r[:200]
    return rtrunc + '…' if r != rtrunc else r


local = Local()

# This a proxy to the bounded config object
local(u'config')

# Thread-local safe objects
config = local.config = CKANConfig()

local("config_declaration")
config_declaration = local.config_declaration = Declaration()

# Proxies to already thread-local safe objects
request = CKANRequest(_get_request)
# Provide a `c`  alias for `g` for backwards compatibility
g: Any = LocalProxy(_get_c)
c = g
session: Any = LocalProxy(_get_session)

truthy = frozenset([u'true', u'yes', u'on', u'y', u't', u'1'])
falsy = frozenset([u'false', u'no', u'off', u'n', u'f', u'0'])
