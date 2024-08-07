import logging
import datetime
import markdown
import html2text
import json
from paste.deploy.converters import asbool

import ckan.lib.plugins as lib_plugins
import ckan.logic as logic
import ckan.lib.dictization
import ckan.logic.action
import ckan.logic.schema
import ckan.lib.dictization.model_save as model_save
import ckan.lib.navl.dictization_functions
import ckan.lib.datapreview
import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit
import ckan.lib.uploader as uploader
import ckan.lib.search as search
import ckan.authz as authz

from ckan.common import _, config

# Define some shortcuts
# Ensure they are module-private so that they don't get loaded as available
# actions in the action API.
_validate = ckan.lib.navl.dictization_functions.validate
_check_access = logic.check_access
_get_action = logic.get_action
ValidationError = logic.ValidationError
NotFound = logic.NotFound

log = logging.getLogger(__name__)

DCAT_DATASET_FIELDS = [
    'title',
    'notes',
]


def translate_fields(context, data_dict):
    html_convert = html2text.HTML2Text()
    pkg_title = data_dict.get('title')
    pkg_notes = data_dict.get('notes', '')
    default_lang = config.get('ckan.locale_default', 'da').split('_')[0]

    data_dict['title_translated-{}'.format(default_lang)] = pkg_title
    data_dict['notes_translated-{}'.format(default_lang)] = (
        pkg_notes if pkg_notes else ''
    )

    languages_offered = config.get('ckan.locales_offered', 'en fr')
    languages = languages_offered.split()
    languages = [lang.split('_')[0] for lang in languages if lang != default_lang]

    for lang in languages:
        try:
            translation = _get_action('translate')(
                context,
                {
                    'input': {
                        'title': pkg_title,
                        'notes': markdown.markdown(pkg_notes),
                    },
                    'from': default_lang,
                    'to': lang,
                },
            )
            translation_title_output = translation['output'].get('title')
            translation_notes_output = translation['output'].get('notes')
            translation_outputs = {
                'title': translation_title_output,
                'notes': translation_notes_output,
            }

            for name, translation_output in translation_outputs.items():
                if translation_output.startswith('\n\n'):
                    translation_outputs[name] = translation_output[2:]

                if translation_output.endswith('\n\n'):
                    translation_outputs[name] = translation_output[:-2]

            data_dict['title_translated-{}'.format(lang)] = translation_outputs['title']
            data_dict['notes_translated-{}'.format(lang)] = html_convert.handle(
                translation_outputs['notes']
            )

        except Exception as e:
            log.debug(
                'Unable to retrieve {} translation for {}: {}'.format(
                    lang, data_dict.get('name'), e
                )
            )
            data_dict['title_translated-{}'.format(lang)] = pkg_title
            data_dict['notes_translated-{}'.format(lang)] = pkg_notes

    existing_title_translations = data_dict.get('title_translated')
    existing_notes_translations = data_dict.get('notes_translated')

    if existing_title_translations:
        for lang, translation in existing_title_translations.items():
            data_dict['title_translated'][lang] = data_dict[
                'title_translated-{}'.format(lang)
            ]

    if existing_notes_translations:
        for lang, translation in existing_notes_translations.items():
            data_dict['notes_translated'][lang] = data_dict[
                'notes_translated-{}'.format(lang)
            ]

    return data_dict


@toolkit.side_effect_free
def package_create(context, data_dict):
    """Create a new dataset (package).
    You must be authorized to create new datasets. If you specify any groups
    for the new dataset, you must also be authorized to edit these groups.
    Plugins may change the parameters of this function depending on the value
    of the ``type`` parameter, see the
    :py:class:`~ckan.plugins.interfaces.IDatasetForm` plugin interface.
    :param name: the name of the new dataset, must be between 2 and 100
        characters long and contain only lowercase alphanumeric characters,
        ``-`` and ``_``, e.g. ``'warandpeace'``
    :type name: string
    :param title: the title of the dataset (optional, default: same as
        ``name``)
    :type title: string
    :param private: If ``True`` creates a private dataset
    :type private: bool
    :param author: the name of the dataset's author (optional)
    :type author: string
    :param author_email: the email address of the dataset's author (optional)
    :type author_email: string
    :param maintainer: the name of the dataset's maintainer (optional)
    :type maintainer: string
    :param maintainer_email: the email address of the dataset's maintainer
        (optional)
    :type maintainer_email: string
    :param license_id: the id of the dataset's license, see
        :py:func:`~ckan.logic.action.get.license_list` for available values
        (optional)
    :type license_id: license id string
    :param notes: a description of the dataset (optional)
    :type notes: string
    :param url: a URL for the dataset's source (optional)
    :type url: string
    :param version: (optional)
    :type version: string, no longer than 100 characters
    :param state: the current state of the dataset, e.g. ``'active'`` or
        ``'deleted'``, only active datasets show up in search results and
        other lists of datasets, this parameter will be ignored if you are not
        authorized to change the state of the dataset (optional, default:
        ``'active'``)
    :type state: string
    :param type: the type of the dataset (optional),
        :py:class:`~ckan.plugins.interfaces.IDatasetForm` plugins
        associate themselves with different dataset types and provide custom
        dataset handling behaviour for these types
    :type type: string
    :param resources: the dataset's resources, see
        :py:func:`resource_create` for the format of resource dictionaries
        (optional)
    :type resources: list of resource dictionaries
    :param tags: the dataset's tags, see :py:func:`tag_create` for the format
        of tag dictionaries (optional)
    :type tags: list of tag dictionaries
    :param extras: the dataset's extras (optional), extras are arbitrary
        (key: value) metadata items that can be added to datasets, each extra
        dictionary should have keys ``'key'`` (a string), ``'value'`` (a
        string)
    :type extras: list of dataset extra dictionaries
    :param relationships_as_object: see :py:func:`package_relationship_create`
        for the format of relationship dictionaries (optional)
    :type relationships_as_object: list of relationship dictionaries
    :param relationships_as_subject: see :py:func:`package_relationship_create`
        for the format of relationship dictionaries (optional)
    :type relationships_as_subject: list of relationship dictionaries
    :param groups: the groups to which the dataset belongs (optional), each
        group dictionary should have one or more of the following keys which
        identify an existing group:
        ``'id'`` (the id of the group, string), or ``'name'`` (the name of the
        group, string),  to see which groups exist
        call :py:func:`~ckan.logic.action.get.group_list`
    :type groups: limport ckan.plugins as pluginsist of dictionaries
    :param owner_org: the id of the dataset's owning organization, see
        :py:func:`~ckan.logic.action.get.organization_list` or
        :py:func:`~ckan.logic.action.get.organization_list_for_user` for
        available values (optional)
    :type owner_org: string
    :returns: the newly created dataset (unless 'return_id_only' is set to True
              in the context, in which case just the dataset id will
              be returned)
    :rtype: dictionary
    """
    model = context['model']
    user = context['user']

    if 'type' not in data_dict:
        package_plugin = lib_plugins.lookup_package_plugin()
        try:
            # use first type as default if user didn't provide type
            package_type = package_plugin.package_types()[0]
        except (AttributeError, IndexError):
            package_type = 'dataset'
            # in case a 'dataset' plugin was registered w/o fallback
            package_plugin = lib_plugins.lookup_package_plugin(package_type)
        data_dict['type'] = package_type
    else:
        package_plugin = lib_plugins.lookup_package_plugin(data_dict['type'])

    if 'schema' in context:
        schema = context['schema']
    else:
        schema = package_plugin.create_package_schema()
    for extra in data_dict.get('extras', []):
        if extra.get('key') == 'contact_name' and not data_dict.get('author'):
            data_dict['author'] = extra['value']
        if extra.get('key') == 'contact_email' and not data_dict.get('author_email'):
            data_dict['author_email'] = extra['value']

    data_dict = translate_fields(context, data_dict)

    _check_access('package_create', context, data_dict)

    if 'api_version' not in context:
        # check_data_dict() is deprecated. If the package_plugin has a
        # check_data_dict() we'll call it, if it doesn't have the method we'll
        # do nothing.
        check_data_dict = getattr(package_plugin, 'check_data_dict', None)
        if check_data_dict:
            try:
                check_data_dict(data_dict, schema)
            except TypeError:
                # Old plugins do not support passing the schema so we need
                # to ensure they still work
                package_plugin.check_data_dict(data_dict)

    data, errors = lib_plugins.plugin_validate(
        package_plugin, context, data_dict, schema, 'package_create'
    )

    if data_dict.get('data_directory') in [True, 'True']:
        for field in DCAT_DATASET_FIELDS:
            if not data_dict.get(field):
                errors[field] = [_('Missing value')]

    documentation = data_dict.get("documentation")
    data_dict['url'] = documentation

    log.debug(
        'package_create validate_errs=%r user=%s package=%s data=%r',
        errors,
        context.get('user'),
        data.get('name'),
        data_dict,
    )

    if errors:
        model.Session.rollback()
        raise ValidationError(errors)

    rev = model.repo.new_revision()
    rev.author = user
    if 'message' in context:
        rev.message = context['message']
    else:
        rev.message = _('REST API: Create object %s') % data.get('name')

    if user:
        user_obj = model.User.by_name(user.decode('utf8'))
        if user_obj:
            data['creator_user_id'] = user_obj.id

    pkg = model_save.package_dict_save(data, context)

    # We have to do this after save so the package id is available.
    # If this fails, we have to rollback the transaction.
    if documentation and 'http' not in documentation:
        try:
            upload = uploader.get_resource_uploader(data_dict)
            upload.upload(pkg.id, uploader.get_max_resource_size())
        except Exception as e:
            model.Session.rollback()
            raise ValidationError({'upload': [_('Documentation upload failed: {}').format(e)]})

    # Needed to let extensions know the package and resources ids
    model.Session.flush()
    data['id'] = pkg.id
    if data.get('resources'):
        for index, resource in enumerate(data['resources']):
            resource['id'] = pkg.resources[index].id

    context_org_update = context.copy()
    context_org_update['ignore_auth'] = True
    context_org_update['defer_commit'] = True
    context_org_update['add_revision'] = False
    _get_action('package_owner_org_update')(
        context_org_update, {'id': pkg.id, 'organization_id': pkg.owner_org}
    )

    for item in plugins.PluginImplementations(plugins.IPackageController):
        item.create(pkg)

        item.after_create(context, data)

    # Make sure that a user provided schema is not used in create_views
    # and on package_show
    context.pop('schema', None)

    # Create default views for resources if necessary
    if data.get('resources'):
        logic.get_action('package_create_default_resource_views')(
            {'model': context['model'], 'user': context['user'], 'ignore_auth': True},
            {'package': data},
        )

    if not context.get('defer_commit'):
        model.repo.commit()

    # need to let rest api create
    context['package'] = pkg
    # this is added so that the rest controller can make a new location
    context['id'] = pkg.id
    log.debug('Created object %s' % pkg.name)

    return_id_only = context.get('return_id_only', False)

    output = (
        context['id']
        if return_id_only
        else _get_action('package_show')(context, {'id': context['id']})
    )

    return output


@toolkit.side_effect_free
def package_update(context, data_dict):
    """Update a dataset (package).
    You must be authorized to edit the dataset and the groups that it belongs
    to.
    It is recommended to call
    :py:func:`ckan.logic.action.get.package_show`, make the desired changes to
    the result, and then call ``package_update()`` with it.
    Plugins may change the parameters of this function depending on the value
    of the dataset's ``type`` attribute, see the
    :py:class:`~ckan.plugins.interfaces.IDatasetForm` plugin interface.
    For further parameters see
    :py:func:`~ckan.logic.action.create.package_create`.
    :param id: the name or id of the dataset to update
    :type id: string
    :returns: the updated dataset (if ``'return_package_dict'`` is ``True`` in
              the context, which is the default. Otherwise returns just the
              dataset id)
    :rtype: dictionary
    """

    model = context['model']
    user = context['user']
    name_or_id = data_dict.get('id') or data_dict.get('name')
    if name_or_id is None:
        raise ValidationError({'id': _('Missing value')})

    pkg = model.Package.get(name_or_id)
    if pkg is None:
        raise NotFound(_('Package was not found.'))
    context['package'] = pkg
    data_dict['id'] = pkg.id
    data_dict['type'] = pkg.type

    for extra in data_dict.get('extras', []):
        if extra.get('key') == 'contact_name' and not data_dict.get('author'):
            data_dict['author'] = extra['value']
        if extra.get('key') == 'contact_email' and not data_dict.get('author_email'):
            data_dict['author_email'] = extra['value']

    data_dict = translate_fields(context, data_dict)

    _check_access('package_update', context, data_dict)

    # get the schema
    package_plugin = lib_plugins.lookup_package_plugin(pkg.type)
    if 'schema' in context:
        schema = context['schema']
    else:
        schema = package_plugin.update_package_schema()

    if 'api_version' not in context:
        # check_data_dict() is deprecated. If the package_plugin has a
        # check_data_dict() we'll call it, if it doesn't have the method we'll
        # do nothing.
        check_data_dict = getattr(package_plugin, 'check_data_dict', None)
        if check_data_dict:
            try:
                package_plugin.check_data_dict(data_dict, schema)
            except TypeError:
                # Old plugins do not support passing the schema so we need
                # to ensure they still work.
                package_plugin.check_data_dict(data_dict)

    data, errors = lib_plugins.plugin_validate(
        package_plugin, context, data_dict, schema, 'package_update'
    )

    if data_dict.get('data_directory') in [True, 'True']:
        for field in DCAT_DATASET_FIELDS:
            if not data_dict.get(field):
                errors[field] = [_('Missing value')]

    documentation = data_dict.get('documentation')
    data_dict["url"] = documentation

    if documentation and 'http' not in documentation:
        try:
            upload = uploader.get_resource_uploader(data_dict)
            upload.upload(data_dict['id'], uploader.get_max_resource_size())
        except Exception as e:
            errors['upload'] = [_('Upload failed: %s') % str(e)]

    log.debug(
        'package_update validate_errs=%r user=%s package=%s data=%r',
        errors,
        context.get('user'),
        context.get('package').name if context.get('package') else '',
        data,
    )

    if errors:
        model.Session.rollback()
        raise ValidationError(errors)

    rev = model.repo.new_revision()
    rev.author = user
    if 'message' in context:
        rev.message = context['message']
    else:
        rev.message = _('REST API: Update object %s') % data.get('name')

    # avoid revisioning by updating directly
    model.Session.query(model.Package).filter_by(id=pkg.id).update(
        {'metadata_modified': datetime.datetime.utcnow()}
    )
    model.Session.refresh(pkg)

    pkg = model_save.package_dict_save(data, context)

    context_org_update = context.copy()
    context_org_update['ignore_auth'] = True
    context_org_update['defer_commit'] = True
    context_org_update['add_revision'] = False
    _get_action('package_owner_org_update')(
        context_org_update, {'id': pkg.id, 'organization_id': pkg.owner_org}
    )

    # Needed to let extensions know the new resources ids
    model.Session.flush()
    if data.get('resources'):
        for index, resource in enumerate(data['resources']):
            resource['id'] = pkg.resources[index].id

    for item in plugins.PluginImplementations(plugins.IPackageController):
        item.edit(pkg)

        item.after_update(context, data)

    if not context.get('defer_commit'):
        model.repo.commit()

    log.debug('Updated object %s' % pkg.name)

    return_id_only = context.get('return_id_only', False)

    # Make sure that a user provided schema is not used on package_show
    context.pop('schema', None)

    # we could update the dataset so we should still be able to read it.
    context['ignore_auth'] = True
    output = (
        data_dict['id']
        if return_id_only
        else _get_action('package_show')(context, {'id': data_dict['id']})
    )

    return output


@toolkit.side_effect_free
def package_search(context, data_dict):
    """
    Searches for packages satisfying a given search criteria.

    This action accepts solr search query parameters (details below), and
    returns a dictionary of results, including dictized datasets that match
    the search criteria, a search count and also facet information.

    **Solr Parameters:**

    For more in depth treatment of each paramter, please read the `Solr
    Documentation <http://wiki.apache.org/solr/CommonQueryParameters>`_.

    This action accepts a *subset* of solr's search query parameters:


    :param q: the solr query.  Optional.  Default: ``"*:*"``
    :type q: string
    :param fq: any filter queries to apply.  Note: ``+site_id:{ckan_site_id}``
        is added to this string prior to the query being executed.
    :type fq: string
    :param sort: sorting of the search results.  Optional.  Default:
        ``'relevance asc, metadata_modified desc'``.  As per the solr
        documentation, this is a comma-separated string of field names and
        sort-orderings.
    :type sort: string
    :param rows: the number of matching rows to return. There is a hard limit
        of 1000 datasets per query.
    :type rows: int
    :param start: the offset in the complete result for where the set of
        returned datasets should begin.
    :type start: int
    :param facet: whether to enable faceted results.  Default: ``True``.
    :type facet: string
    :param facet.mincount: the minimum counts for facet fields should be
        included in the results.
    :type facet.mincount: int
    :param facet.limit: the maximum number of values the facet fields return.
        A negative value means unlimited. This can be set instance-wide with
        the :ref:`search.facets.limit` config option. Default is 50.
    :type facet.limit: int
    :param facet.field: the fields to facet upon.  Default empty.  If empty,
        then the returned facet information is empty.
    :type facet.field: list of strings
    :param include_drafts: if ``True``, draft datasets will be included in the
        results. A user will only be returned their own draft datasets, and a
        sysadmin will be returned all draft datasets. Optional, the default is
        ``False``.
    :type include_drafts: boolean
    :param include_private: if ``True``, private datasets will be included in
        the results. Only private datasets from the user's organizations will
        be returned and sysadmins will be returned all private datasets.
        Optional, the default is ``False``.
    :param use_default_schema: use default package schema instead of
        a custom schema defined with an IDatasetForm plugin (default: False)
    :type use_default_schema: bool


    The following advanced Solr parameters are supported as well. Note that
    some of these are only available on particular Solr versions. See Solr's
    `dismax`_ and `edismax`_ documentation for further details on them:

    ``qf``, ``wt``, ``bf``, ``boost``, ``tie``, ``defType``, ``mm``


    .. _dismax: http://wiki.apache.org/solr/DisMaxQParserPlugin
    .. _edismax: http://wiki.apache.org/solr/ExtendedDisMax


    **Examples:**

    ``q=flood`` datasets containing the word `flood`, `floods` or `flooding`
    ``fq=tags:economy`` datasets with the tag `economy`
    ``facet.field=["tags"] facet.limit=10 rows=0`` top 10 tags

    **Results:**

    The result of this action is a dict with the following keys:

    :rtype: A dictionary with the following keys
    :param count: the number of results found.  Note, this is the total number
        of results found, not the total number of results returned (which is
        affected by limit and row parameters used in the input).
    :type count: int
    :param results: ordered list of datasets matching the query, where the
        ordering defined by the sort parameter used in the query.
    :type results: list of dictized datasets.
    :param facets: DEPRECATED.  Aggregated information about facet counts.
    :type facets: DEPRECATED dict
    :param search_facets: aggregated information about facet counts.  The outer
        dict is keyed by the facet field name (as used in the search query).
        Each entry of the outer dict is itself a dict, with a "title" key, and
        an "items" key.  The "items" key's value is a list of dicts, each with
        "count", "display_name" and "name" entries.  The display_name is a
        form of the name that can be used in titles.
    :type search_facets: nested dict of dicts.

    An example result: ::

     {'count': 2,
      'results': [ { <snip> }, { <snip> }],
      'search_facets': {u'tags': {'items': [{'count': 1,
                                             'display_name': u'tolstoy',
                                             'name': u'tolstoy'},
                                            {'count': 2,
                                             'display_name': u'russian',
                                             'name': u'russian'}
                                           ]
                                 }
                       }
     }

    **Limitations:**

    The full solr query language is not exposed, including.

    fl
        The parameter that controls which fields are returned in the solr
        query.
        fl can be  None or a list of result fields, such as ['id', 'extras_custom_field'].
        if fl = None, datasets are returned as a list of full dictionary.
    """
    # sometimes context['schema'] is None
    schema = context.get('schema') or logic.schema.default_package_search_schema()
    data_dict, errors = _validate(data_dict, schema, context)
    # put the extras back into the data_dict so that the search can
    # report needless parameters
    data_dict.update(data_dict.get('__extras', {}))
    data_dict.pop('__extras', None)
    if errors:
        raise ValidationError(errors)

    model = context['model']
    session = context['session']
    user = context.get('user')

    _check_access('package_search', context, data_dict)

    # Move ext_ params to extras and remove them from the root of the search
    # params, so they don't cause and error
    data_dict['extras'] = data_dict.get('extras', {})
    for key in [key for key in data_dict.keys() if key.startswith('ext_')]:
        data_dict['extras'][key] = data_dict.pop(key)

    # check if some extension needs to modify the search params
    for item in plugins.PluginImplementations(plugins.IPackageController):
        data_dict = item.before_search(data_dict)

    # the extension may have decided that it is not necessary to perform
    # the query
    abort = data_dict.get('abort_search', False)

    if data_dict.get('sort') in (None, 'rank'):
        data_dict['sort'] = 'score desc, metadata_modified desc'

    results = []
    if not abort:
        if asbool(data_dict.get('use_default_schema')):
            data_source = 'data_dict'
        else:
            data_source = 'validated_data_dict'
        data_dict.pop('use_default_schema', None)

        result_fl = data_dict.get('fl')
        if not result_fl:
            data_dict['fl'] = 'id {0}'.format(data_source)
        else:
            data_dict['fl'] = ' '.join(result_fl)

        # Remove before these hit solr FIXME: whitelist instead
        include_private = asbool(data_dict.pop('include_private', False))
        include_drafts = asbool(data_dict.pop('include_drafts', False))
        data_dict.setdefault('fq', '')
        if not include_private:
            data_dict['fq'] = '+capacity:public ' + data_dict['fq']
        if include_drafts:
            data_dict['fq'] += ' +state:(active OR draft)'

        # Pop these ones as Solr does not need them
        extras = data_dict.pop('extras', None)

        # enforce permission filter based on user
        if context.get('ignore_auth') or (user and authz.is_sysadmin(user)):
            labels = None
        else:
            labels = lib_plugins.get_permission_labels().get_user_dataset_labels(
                context['auth_user_obj']
            )

        query = search.query_for(model.Package)
        query.run(data_dict, permission_labels=labels)

        # Add them back so extensions can use them on after_search
        data_dict['extras'] = extras

        if result_fl:
            for package in query.results:
                if package.get('extras'):
                    package.update(package['extras'])
                    package.pop('extras')
                results.append(package)
        else:
            for package in query.results:
                # get the package object
                package_dict = package.get(data_source)
                ## use data in search index if there
                if package_dict:
                    # the package_dict still needs translating when being viewed
                    package_dict = json.loads(package_dict)
                    if context.get('for_view'):
                        for item in plugins.PluginImplementations(
                            plugins.IPackageController
                        ):
                            package_dict = item.before_view(package_dict)
                    results.append(package_dict)
                else:
                    log.error(
                        'No package_dict is coming from solr for package ' 'id %s',
                        package['id'],
                    )

        count = query.count
        facets = query.facets
    else:
        count = 0
        facets = {}
        results = []

    search_results = {
        'count': count,
        'facets': facets,
        'results': results,
        'sort': data_dict['sort'],
    }

    # create a lookup table of group name to title for all the groups and
    # organizations in the current search's facets.
    group_names = []
    for field_name in ('groups', 'organization'):
        group_names.extend(facets.get(field_name, {}).keys())

    groups = (
        session.query(model.Group.name, model.Group.title)
        .filter(model.Group.name.in_(group_names))
        .all()
        if group_names
        else []
    )
    group_titles_by_name = dict(groups)

    # Transform facets into a more useful data structure.
    restructured_facets = {}
    for key, value in facets.items():
        restructured_facets[key] = {'title': key, 'items': []}
        for key_, value_ in value.items():
            new_facet_dict = {}
            new_facet_dict['name'] = key_
            if key in ('groups', 'organization'):
                display_name = group_titles_by_name.get(key_, key_)
                display_name = (
                    display_name if display_name and display_name.strip() else key_
                )
                new_facet_dict['display_name'] = display_name
            elif key == 'license_id':
                license = model.Package.get_license_register().get(key_)
                if license:
                    new_facet_dict['display_name'] = license.title
                else:
                    new_facet_dict['display_name'] = key_
            else:
                new_facet_dict['display_name'] = key_
            new_facet_dict['count'] = value_
            restructured_facets[key]['items'].append(new_facet_dict)
    search_results['search_facets'] = restructured_facets

    # check if some extension needs to modify the search results
    for item in plugins.PluginImplementations(plugins.IPackageController):
        search_results = item.after_search(search_results, data_dict)

    # After extensions have had a chance to modify the facets, sort them by
    # display name.
    for facet in search_results['search_facets']:
        search_results['search_facets'][facet]['items'] = sorted(
            search_results['search_facets'][facet]['items'],
            key=lambda facet: facet['display_name'],
            reverse=True,
        )

    # Avoid returning datasets without notes when using package_search for DCAT
    if context.get('from_dcat'):
        search_results['results'] = [
            result
            for result in search_results['results']
            if all(
                [
                    result.get(field) not in [None, ''] and len(result.get(field)) > 0
                    for field in DCAT_DATASET_FIELDS
                ]
            )
        ]

    return search_results
