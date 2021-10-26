import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit
import string
from ckan.lib.navl.dictization_functions import Missing
from ckan.logic.schema import default_user_schema, default_update_user_schema
from ckan.logic.action.create import user_create as core_user_create
from ckan.logic.action.update import user_update as core_user_update
from ckan.lib import mailer
from ckan.lib.plugins import DefaultTranslation
from pylons import config
from ckan import authz

from ckanext.portalopendatadk import actions as oddk_actions

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


class PortalOpenDataDKPlugin(plugins.SingletonPlugin, DefaultTranslation, toolkit.DefaultDatasetForm):
    '''portal.opendata.dk theme plugin.

    '''
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.ITemplateHelpers)
    plugins.implements(plugins.IActions)
    plugins.implements(plugins.ITranslation)
    plugins.implements(plugins.IDatasetForm, inherit=True)
    plugins.implements(plugins.IFacets)

    def update_config(self, config):
        toolkit.add_template_directory(config, 'templates')
        toolkit.add_public_directory(config, 'public')
        toolkit.add_resource('fanstatic', 'portalopendatadk')

    def get_helpers(self):
        return {'portalopendatadk_latest_datasets': latest_datasets,
                'portalopendatadk_most_popular_datasets': most_popular_datasets,
                'get_update_frequencies': get_update_frequencies}

    def get_actions(self):

        return {
            'user_create': custom_user_create,
            'user_update': custom_user_update,
            'get_user_email': get_user_email,
            'package_update': oddk_actions.package_update,
            'package_create': oddk_actions.package_create
        }

    def package_types(self):
        return []

    # IFacets

    def dataset_facets(self, facets_dict, package_type):
        facets_dict['update_frequency'] = plugins.toolkit._('Update frequency')
        return facets_dict

    def organization_facets(self, facets_dict, organization_type, package_type):
        facets_dict['update_frequency'] = plugins.toolkit._('Update frequency')
        return facets_dict

    def group_facets(self, facets_dict, group_type, package_type):
        facets_dict['update_frequency'] = plugins.toolkit._('Update frequency')
        return facets_dict

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

@toolkit.side_effect_free
def get_user_email(context, data_dict):
    '''
    Returns the user names and emails of all the users
    '''
    if not authz.is_sysadmin(toolkit.c.user):
        toolkit.abort(403, _('You are not authorized to access this list'))

    user_list = toolkit.get_action('user_list')(context, data_dict)
    user_name_email = []

    for user in user_list:                                          
        email = user['email']                                       
        user_name = user['display_name']                                        
        user_name_email.append({'user_name':user_name,
                                'email_address':email})

    return user_name_email


def get_update_frequencies():
    update_frequencies = ['Frequent', 'Monthly', 'Yearly', 'Historical']
    update_frequencies_translations = [_('Frequent'), _('Monthly'),
                                       _('Yearly'), _('Historical')]
    return [
        {'text': update_frequencies_translations[i].title(),
         'value': update_frequencies[i]}
        for i in range(len(update_frequencies))]
