import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit
from ckan.lib.navl.dictization_functions import Missing
from ckan.logic.schema import default_user_schema, default_update_user_schema
from ckan.logic.action.create import user_create as core_user_create
from ckan.logic.action.update import user_update as core_user_update

import string
_ = toolkit._



def latest_datasets():
    '''Return a sorted list of the latest datasets.'''

    datasets = toolkit.get_action('package_search')(
        data_dict={'rows': 10, 'sort': 'metadata_created desc' })

    return datasets['results']


def most_popular_datasets():
    '''Return a sorted list of the most popular datasets.'''

    datasets = toolkit.get_action('package_search')(
        data_dict={'rows': 10, 'sort': 'views_recent desc' })

    return datasets['results']


class PortalOpenDataDKPlugin(plugins.SingletonPlugin):
    '''portal.opendata.dk theme plugin.

    '''
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.ITemplateHelpers)
    plugins.implements(plugins.IActions)

    def update_config(self, config):
        toolkit.add_template_directory(config, 'templates')
        toolkit.add_public_directory(config, 'public')
        toolkit.add_resource('fanstatic', 'portalopendatadk')

    def get_helpers(self):
        return {'portalopendatadk_latest_datasets': latest_datasets,
                'portalopendatadk_most_popular_datasets': most_popular_datasets}
    
    def get_actions(self):

        return {
            'user_create': custom_user_create,
            'user_update': custom_user_update,
        }

# Custom actions

def custom_user_create(context, data_dict):

    context['schema'] = custom_create_user_schema(
        form_schema='password1' in context.get('schema', {}))

    return core_user_create(context, data_dict)


def custom_user_update(context, data_dict):

    context['schema'] = custom_update_user_schema(
        form_schema='password1' in context.get('schema', {}))

    return core_user_update(context, data_dict)


# Custom schemas

def custom_create_user_schema(form_schema=False):

    schema = default_user_schema()

    schema['password'] = [custom_user_password_validator,
                          toolkit.get_validator('user_password_not_empty'),
                          toolkit.get_validator('ignore_missing'),
                          unicode]

    if form_schema:
        schema['password1'] = [toolkit.get_validator('user_both_passwords_entered'),
                               custom_user_password_validator,
                               toolkit.get_validator('user_passwords_match'),
                               unicode]
        schema['password2'] = [unicode]

    return schema


def custom_update_user_schema(form_schema=False):

    schema = default_update_user_schema()

    schema['password'] = [custom_user_password_validator,
                          toolkit.get_validator('user_password_not_empty'),
                          toolkit.get_validator('ignore_missing'),
                          unicode]

    if form_schema:
        schema['password'] = [toolkit.get_validator('ignore_missing')]
        schema['password1'] = [toolkit.get_validator('ignore_missing'),
                               custom_user_password_validator,
                               toolkit.get_validator('user_passwords_match'),
                               unicode]
        schema['password2'] = [toolkit.get_validator('ignore_missing'),
                               unicode]

    return schema


# Custom validators
WRONG_PASSWORD_MESSAGE = ('Your password must be 8 characters or longer, ' +
                          'contain at least one capital letter, one small letter, ' +
                          'one number(0-9) and a ' +
                          'special_character(!"#$%&\'()*+,-./:;<=>?@[\\]^_`{|}~)')


def custom_user_password_validator(key, data, errors, context):
    value = data[key]
    special_chars = string.punctuation

    if isinstance(value, Missing):
        pass
    elif not isinstance(value, basestring):
        errors[('password',)].append(_('Passwords must be strings'))
    elif value == '':
        pass
    elif (len(value) < 8 or
          not any(x.isdigit() for x in value) or
          not any(x.isupper() for x in value) or
          not any(x.islower() for x in value) or
          not any(x in special_chars for x in value)
          ):
        errors[('password',)].append(_(WRONG_PASSWORD_MESSAGE))
