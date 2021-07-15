# Copyright 2016-2017 Versada <https://versada.eu/>
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl).

import logging
import sys
import werkzeug

from odoo.service import wsgi_server
from odoo.tools import config as odoo_config

import collections

_logger = logging.getLogger(__name__)
HAS_ROLLBAR = True
try:
    import rollbar
except ImportError:
    HAS_ROLLBAR = False
    _logger.error('Cannot import "rollbar". Please make sure it is installed.')


def get_odoo_commit(odoo_dir):
    """Attempts to get Odoo git commit from :param:`odoo_dir`."""
    if not odoo_dir:
        return
    try:
        return raven.fetch_git_sha(odoo_dir)
    except raven.exceptions.InvalidGitRepository:
        _logger.debug(
            'Odoo directory: "%s" not a valid git repository', odoo_dir)


DEFAULT_LOG_LEVEL = "warn"
EXCLUDE_LOGGERS = ("werkzeug",)
DEFAULT_EXCLUDE_LOGGERS = ",".join(EXCLUDE_LOGGERS)

ODOO_USER_EXCEPTIONS = [
    "odoo.exceptions.AccessDenied",
    "odoo.exceptions.AccessError",
    "odoo.exceptions.DeferredException",
    "odoo.exceptions.MissingError",
    "odoo.exceptions.RedirectWarning",
    "odoo.exceptions.UserError",
    "odoo.exceptions.ValidationError",
    "odoo.exceptions.Warning",
    "odoo.exceptions.except_orm",
]

RollbarOption = collections.namedtuple(
    "RollbarOption", ["key", "default", "converter"])


def get_rollbar_options():
    return [
        RollbarOption("access_token", "", str.strip),
        RollbarOption("branch", "", str.strip),
        RollbarOption("code_version", "", str.strip),
        RollbarOption("enabled", "", bool),
        RollbarOption("environment", "", str.strip),
    ]


def split_multiple(string, delimiter=",", strip_chars=None):
    """Splits :param:`string` and strips :param:`strip_chars` from values."""
    if not string:
        return []
    return [v.strip(strip_chars) for v in string.split(delimiter)]


def get_extra_data(environ, request, exception):
    data = {}
    data['path_info'] = environ.get('PATH_INFO')
    data['http_request_method'] = environ.get('REQUEST_METHOD')
    data['query_string'] = environ.get('QUERY_STRING')
    data['http_user_agent'] = environ.get('HTTP_USER_AGENT')
    data['http_cookie'] = environ.get('HTTP_COOKIE')
    data['http_authorization'] = environ.get('HTTP_AUTHORIZATION')
    try:
        data['exception'] = exception.__module__ + \
            '.' + exception.__class__.__name__
    except:
        data['exception'] = exception.__class__.__name__

    return data


def ignore_handler(payload, **kw):
    try:
        if payload['data']['custom']['exception'] in ODOO_USER_EXCEPTIONS:
            _logger.debug('Skipping report for exception %s as blacklisted' %
                          payload['data']['custom']['exception'])
            return False
    except Exception as e:
        pass

    return payload


def initialize_rollbar(config):
    enabled = config.get("rollbar_enabled", False)

    if not (HAS_ROLLBAR and enabled):
        return

    options = {}

    for option in get_rollbar_options():
        value = config.get("rollbar_%s" % option.key, option.default)
        if isinstance(option.converter, collections.Callable):
            value = option.converter(value)
        if value:
            options[option.key] = value

    level = config.get("rollbar_logging_level", DEFAULT_LOG_LEVEL)
    exclude_loggers = split_multiple(
        config.get("rollbar_exclude_loggers", DEFAULT_EXCLUDE_LOGGERS)
    )

    rollbar_access_token = options.pop("access_token", None)

    if not rollbar_access_token:
        _logger.error(
            "You must specify a Rollbar Access Token to enable error reporting.")
        return

    rollbar.init(rollbar_access_token, **options)
    rollbar.events.add_payload_handler(ignore_handler)

    wsgi_application = wsgi_server.application

    def application(environ, start_response):
        try:
            return wsgi_application(environ, start_response)
        except Exception as e:
            request = werkzeug.wrappers.Request(environ)
            rollbar.report_exc_info(
                sys.exc_info(),
                request=request,
                extra_data=get_extra_data(environ, request, e)
            )
            raise e

    wsgi_server.application = application


initialize_rollbar(odoo_config)
