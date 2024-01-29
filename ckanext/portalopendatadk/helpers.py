# encoding: utf-8
import logging
import os
import json

from ckan.plugins import toolkit


log = logging.getLogger(__name__)


def _from_file(file_name):
    allowed_values = []

    try:
        cur_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(cur_dir, 'validation/{}'.format(file_name))

        with open(file_path, 'r') as file:
            for line in file:
                allowed_values.append(line.strip())
    except Exception as e:
        log.error('Error reading %s: %s' % (file_name, e))

    return allowed_values


def formats_from_file():
    return _from_file('resource_formats.txt')


def frequencies_from_file():
    return _from_file('update_frequencies.txt')


def languages_from_file():
    return _from_file('languages.txt')


def user_has_admin_access(include_editor_access):
    user = toolkit.c.userobj
    # If user is 'None' - they are not logged in.
    if user is None:
        return False
    if user.sysadmin:
        return True

    groups_admin = user.get_groups('organization', 'admin')
    groups_editor = (
        user.get_groups('organization', 'editor') if include_editor_access else []
    )
    groups_list = groups_admin + groups_editor
    organisation_list = [g for g in groups_list if g.type == 'organization']
    return len(organisation_list) > 0


def get_resource_file_types():
    allowed_resource_formats = formats_from_file()
    resource_formats = [{'id': f, 'name': f} for f in allowed_resource_formats]
    return resource_formats


def get_language_codes():
    allowed_languages = languages_from_file()
    languages = [{'id': l, 'name': l} for l in allowed_languages]
    return languages


def get_dcat_info_text(field_name):
    info_text = ''
    try:
        cur_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(cur_dir, 'dcat/dcat_info_text.json')

        with open(file_path, 'r') as file:
            dcat_info_text = json.loads(file.read())
            info_text = dcat_info_text.get(field_name, '')
    except Exception as e:
        log.error('Error reading dcat_info_text.json: %s' % e)

    return info_text


def get_dcat_license_options():
    dcat_license_options = []

    try:
        cur_dir = os.path.dirname(os.path.abspath(__file__))
        file_path = os.path.join(cur_dir, 'dcat/license_options.json')

        with open(file_path, 'r') as file:
            dcat_license_options = json.loads(file.read())
    except Exception as e:
        log.error('Error reading dcat_license_options.json: %s' % e)

    return dcat_license_options