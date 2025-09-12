from ckan.plugins.toolkit import Invalid, _
from ckan.lib.navl.validators import not_empty, ignore_missing

import ckanext.portalopendatadk.helpers as oddk_helpers

import logging


log = logging.getLogger(__name__)


def resource_format_validator(value):
    value = value.upper()
    allowed_resource_formats = oddk_helpers.formats_from_file()

    if value not in allowed_resource_formats:
        raise Invalid(_("Invalid resource format: {}").format(value))
    return value


def update_frequency_validator(value):
    value = value.upper()
    allowed_update_frequencies = oddk_helpers.frequencies_from_file()

    if value not in allowed_update_frequencies:
        raise Invalid(_("Invalid update frequency: {}").format(value))
    return value


def language_code_validator(value):
    value = value.upper()
    allowed_languages = oddk_helpers.languages_from_file()

    if value not in allowed_languages:
        raise Invalid(_("Invalid language code: {}").format(value))
    return value


def not_empty_except_bg_jobs(key, data,
                   errors, context):
    """
    Validates that a value is not empty, except when the request
    is from a background job (e.g. harvester).
    """
    if not context.get('ignore_auth', False):
        return not_empty(key, data, errors, context)
    else:
        return ignore_missing(key, data, errors, context)