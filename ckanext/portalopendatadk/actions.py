import logging
import markdown
import html2text
import six
import datetime
import json

# from paste.deploy.converters import asbool

import ckan.logic as logic
import ckan.lib.dictization
import ckan.logic.action
import ckan.logic.schema
import ckan.lib.navl.dictization_functions
import ckan.lib.datapreview
import ckan.plugins.toolkit as toolkit
import ckan.lib.uploader as uploader
import ckan.lib.plugins as lib_plugins
from ckan.types import Schema, Context, DataDict, ActionResult
import ckan.lib.dictization.model_save as model_save
import ckan.plugins as plugins

from ckan.common import _, config

# Define some shortcuts
# Ensure they are module-private so that they don't get loaded as available
# actions in the action API.
_get_action = logic.get_action
_check_access = logic.check_access
ValidationError = logic.ValidationError
NotFound = logic.NotFound

log = logging.getLogger(__name__)

DCAT_DATASET_FIELDS = [
    "title",
    "notes",
]


def translate_fields(context, data_dict):
    html_convert = html2text.HTML2Text()
    pkg_title = data_dict.get("title")
    pkg_notes = data_dict.get("notes", "")
    default_lang = config.get("ckan.locale_default", "da").split("_")[0]

    data_dict["title_translated-{}".format(default_lang)] = pkg_title
    data_dict["notes_translated-{}".format(default_lang)] = (
        pkg_notes if pkg_notes else ""
    )

    languages_offered = config.get("ckan.locales_offered", ["da_DK", "en", "fr"])
    languages = languages_offered
    languages = [lang.split("_")[0] for lang in languages if lang != default_lang]

    for lang in languages:
        try:
            translation = _get_action("translate")(
                context,
                {
                    "input": {
                        "title": pkg_title,
                        "notes": markdown.markdown(pkg_notes),
                    },
                    "from": default_lang,
                    "to": lang,
                },
            )
            translation_title_output = translation["output"].get("title")
            translation_notes_output = translation["output"].get("notes")
            translation_outputs = {
                "title": translation_title_output,
                "notes": translation_notes_output,
            }

            for name, translation_output in list(translation_outputs.items()):
                if translation_output.startswith("\n\n"):
                    translation_outputs[name] = translation_output[2:]

                if translation_output.endswith("\n\n"):
                    translation_outputs[name] = translation_output[:-2]

            data_dict["title_translated-{}".format(lang)] = translation_outputs["title"]
            data_dict["notes_translated-{}".format(lang)] = html_convert.handle(
                translation_outputs["notes"]
            )

        except Exception as e:
            log.debug(
                "Unable to retrieve {} translation for {}: {}".format(
                    lang, data_dict.get("name"), e
                )
            )
            data_dict["title_translated-{}".format(lang)] = pkg_title
            data_dict["notes_translated-{}".format(lang)] = pkg_notes

    existing_title_translations = data_dict.get("title_translated")
    existing_notes_translations = data_dict.get("notes_translated")

    if existing_title_translations:
        for lang, translation in list(existing_title_translations.items()):
            data_dict["title_translated"][lang] = data_dict[
                "title_translated-{}".format(lang)
            ]

    if existing_notes_translations:
        for lang, translation in list(existing_notes_translations.items()):
            data_dict["notes_translated"][lang] = data_dict[
                "notes_translated-{}".format(lang)
            ]

    return data_dict


def normalize_extras(data_dict):
    """
    Normalize extras into schema fields with priority rules:
      - 'author' always overrides 'contact_name'
      - 'author_email' always overrides 'contact_email'
      - 'data_themes' promoted and normalized as a list
      - All handled keys removed from extras
    """

    author_val = None
    contact_val = None
    author_email_val = None
    contact_email_val = None
    data_themes_val = None

    cleaned_extras = []

    for extra in data_dict.get("extras", []):
        key, val = extra.get("key"), extra.get("value")

        if key == "author":
            author_val = val
        elif key == "contact_name":
            contact_val = val
        elif key == "author_email":
            author_email_val = val
        elif key == "contact_email":
            contact_email_val = val
        elif key == "data_themes":
            data_themes_val = val
        else:
            cleaned_extras.append(extra)

    # apply precedence: author > contact_name
    if author_val is not None:
        data_dict["author"] = author_val
    elif contact_val is not None:
        data_dict["author"] = contact_val

    # apply precedence: author_email > contact_email
    if author_email_val is not None:
        data_dict["author_email"] = author_email_val
    elif contact_email_val is not None:
        data_dict["author_email"] = contact_email_val

    # normalize data_themes
    if data_themes_val is not None:
        if isinstance(data_themes_val, str):
            try:
                parsed = json.loads(data_themes_val)
                if isinstance(parsed, list):
                    data_dict["data_themes"] = parsed
                else:
                    data_dict["data_themes"] = [str(parsed)]
            except Exception:
                log.error("Failed to decode data_themes: %r", data_themes_val)
                data_dict["data_themes"] = [data_themes_val]
        elif isinstance(data_themes_val, list):
            data_dict["data_themes"] = data_themes_val
        else:
            data_dict["data_themes"] = [str(data_themes_val)]

    data_dict["extras"] = cleaned_extras
    return data_dict


# Overrides the default package_create action to add auto-translation of metadata,
# add documentation upload, and to handle DCAT dataset fields.
def package_create(context: Context, data_dict: DataDict) -> ActionResult.PackageCreate:
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
    :param plugin_data: private package data belonging to plugins.
        Only sysadmin users may set this value. It should be a dict that can
        be dumped into JSON, and plugins should namespace their data with the
        plugin name to avoid collisions with other plugins, eg::

            {
                "name": "test-dataset",
                "plugin_data": {
                    "plugin1": {"key1": "value1"},
                    "plugin2": {"key2": "value2"}
                }
            }
    :type plugin_data: dict
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
    :type groups: list of dictionaries
    :param owner_org: the id of the dataset's owning organization, see
        :py:func:`~ckan.logic.action.get.organization_list` or
        :py:func:`~ckan.logic.action.get.organization_list_for_user` for
        available values. This parameter can be made optional if the config
        option :ref:`ckan.auth.create_unowned_dataset` is set to ``True``.
    :type owner_org: string

    :returns: the newly created dataset (unless 'return_id_only' is set to True
              in the context, in which case just the dataset id will
              be returned)
    :rtype: dictionary

    """
    model = context["model"]
    user = context["user"]


    resources = data_dict.get("resources", [])
    updated_resources = []

    for resource in resources:
        resource_format = resource.get("format", "").upper()

        if resource_format == "OGC WFS":
            resource["format"] = "WFS_SRVC"
        updated_resources.append(resource)

    data_dict["resources"] = updated_resources

    if "type" not in data_dict:
        package_plugin = lib_plugins.lookup_package_plugin()
        try:
            # use first type as default if user didn't provide type
            package_type = package_plugin.package_types()[0]
        except (AttributeError, IndexError):
            package_type = "dataset"
            # in case a 'dataset' plugin was registered w/o fallback
            package_plugin = lib_plugins.lookup_package_plugin(package_type)
        data_dict["type"] = package_type
    else:
        package_plugin = lib_plugins.lookup_package_plugin(data_dict["type"])

    schema: Schema = context.get("schema") or package_plugin.create_package_schema()

    data_dict = normalize_extras(data_dict)
    data_dict = translate_fields(context, data_dict)

    _check_access("package_create", context, data_dict)

    data, errors = lib_plugins.plugin_validate(
        package_plugin, context, data_dict, schema, "package_create"
    )

    documentation = data_dict.get("documentation")
    data_dict["url"] = documentation

    if data_dict.get("data_directory") in [True, "True"]:
        for field in DCAT_DATASET_FIELDS:
            if not data_dict.get(field):
                errors[field] = [_("Missing value")]

    log.debug(
        "package_create validate_errs=%r user=%s package=%s data=%r",
        errors,
        context.get("user"),
        data.get("name"),
        data_dict,
    )

    if errors:
        model.Session.rollback()
        raise ValidationError(errors)

    plugin_data = data.get("plugin_data", False)
    include_plugin_data = False
    if user:
        user_obj = model.User.by_name(six.ensure_text(user))
        if user_obj:
            data["creator_user_id"] = user_obj.id
            include_plugin_data = user_obj.sysadmin and plugin_data

    pkg = model_save.package_dict_save(data, context, include_plugin_data)

    # We have to do this after save so the package id is available.
    # If this fails, we have to rollback the transaction.
    if documentation and "http" not in documentation:
        try:
            upload = uploader.get_resource_uploader(data_dict)
            upload.upload(pkg.id, uploader.get_max_resource_size())
        except Exception as e:
            model.Session.rollback()
            raise ValidationError(
                {"upload": [_("Documentation upload failed: {}").format(e)]}
            )

    # Needed to let extensions know the package and resources ids
    model.Session.flush()
    data["id"] = pkg.id
    if data.get("resources"):
        for index, resource in enumerate(data["resources"]):
            resource["id"] = pkg.resources[index].id

    context_org_update = context.copy()
    context_org_update["ignore_auth"] = True
    context_org_update["defer_commit"] = True
    _get_action("package_owner_org_update")(
        context_org_update, {"id": pkg.id, "organization_id": pkg.owner_org}
    )

    for item in plugins.PluginImplementations(plugins.IPackageController):
        item.create(pkg)

        item.after_dataset_create(context, data)

    # Make sure that a user provided schema is not used in create_views
    # and on package_show
    context.pop("schema", None)

    # Create default views for resources if necessary
    if data.get("resources"):
        logic.get_action("package_create_default_resource_views")(
            {"model": context["model"], "user": context["user"], "ignore_auth": True},
            {"package": data},
        )

    if not context.get("defer_commit"):
        model.repo.commit()

    return_id_only = context.get("return_id_only", False)

    if return_id_only:
        return pkg.id

    return _get_action("package_show")(
        context.copy(), {"id": pkg.id, "include_plugin_data": include_plugin_data}
    )


# Overrides the default package_update action to add auto-translation of metadata,
# add documentation upload, and to handle DCAT dataset fields.
def package_update(context: Context, data_dict: DataDict) -> ActionResult.PackageUpdate:
    """Update a dataset (package).

    You must be authorized to edit the dataset and the groups that it belongs
    to.

    .. note:: Update methods may delete parameters not explicitly provided in the
        data_dict. If you want to edit only a specific attribute use `package_patch`
        instead.

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

    :returns: the updated dataset (if ``'return_id_only'`` is ``False`` in
              the context, which is the default. Otherwise returns just the
              dataset id)
    :rtype: dictionary

    """
    model = context["model"]
    name_or_id = data_dict.get("id") or data_dict.get("name")
    if name_or_id is None:
        raise ValidationError({"id": _("Missing value")})

    pkg = model.Package.get(name_or_id)
    if pkg is None:
        raise NotFound(_("Package was not found."))
    context["package"] = pkg

    # immutable fields
    data_dict["id"] = pkg.id
    data_dict["type"] = pkg.type

    data_dict = translate_fields(context, data_dict)
    data_dict = normalize_extras(data_dict)

    _check_access("package_update", context, data_dict)

    user = context["user"]
    # get the schema

    package_plugin = lib_plugins.lookup_package_plugin(pkg.type)
    schema = context.get("schema") or package_plugin.update_package_schema()

    resource_uploads = []
    for resource in data_dict.get("resources", []):
        # file uploads/clearing
        upload = uploader.get_resource_uploader(resource)

        if "mimetype" not in resource:
            if hasattr(upload, "mimetype"):
                resource["mimetype"] = upload.mimetype

        if "url_type" in resource:
            if hasattr(upload, "filesize"):
                resource["size"] = upload.filesize

        resource_uploads.append(upload)

    data, errors = lib_plugins.plugin_validate(
        package_plugin, context, data_dict, schema, "package_update"
    )

    if data_dict.get("data_directory") in [True, "True"]:
        for field in DCAT_DATASET_FIELDS:
            if not data_dict.get(field):
                errors[field] = [_("Missing value")]

    documentation = data_dict.get("documentation")
    data_dict["url"] = documentation

    if documentation and "http" not in documentation:
        try:
            upload = uploader.get_resource_uploader(data_dict)
            upload.upload(data_dict["id"], uploader.get_max_resource_size())
        except Exception as e:
            errors["upload"] = [_("Upload failed: %s") % str(e)]

    log.debug(
        "package_update validate_errs=%r user=%s package=%s data=%r",
        errors,
        user,
        context["package"].name,
        data,
    )

    if errors:
        model.Session.rollback()
        raise ValidationError(errors)

    # avoid revisioning by updating directly
    model.Session.query(model.Package).filter_by(id=pkg.id).update(
        {"metadata_modified": datetime.datetime.utcnow()}
    )
    model.Session.refresh(pkg)

    include_plugin_data = False
    user_obj = context.get("auth_user_obj")
    if user_obj:
        plugin_data = data.get("plugin_data", False)
        include_plugin_data = user_obj.sysadmin and plugin_data  # type: ignore

    pkg = model_save.package_dict_save(data, context, include_plugin_data)

    context_org_update = context.copy()
    context_org_update["ignore_auth"] = True
    context_org_update["defer_commit"] = True
    _get_action("package_owner_org_update")(
        context_org_update, {"id": pkg.id, "organization_id": pkg.owner_org}
    )

    # Needed to let extensions know the new resources ids
    model.Session.flush()
    for index, (resource, upload) in enumerate(
        zip(data.get("resources", []), resource_uploads)
    ):
        resource["id"] = pkg.resources[index].id

        upload.upload(resource["id"], uploader.get_max_resource_size())

    for item in plugins.PluginImplementations(plugins.IPackageController):
        item.edit(pkg)

        item.after_dataset_update(context, data)

    if not context.get("defer_commit"):
        model.repo.commit()

    log.debug("Updated object %s" % pkg.name)

    return_id_only = context.get("return_id_only", False)

    # Make sure that a user provided schema is not used on package_show
    context.pop("schema", None)

    # we could update the dataset so we should still be able to read it.
    context["ignore_auth"] = True
    output = (
        data_dict["id"]
        if return_id_only
        else _get_action("package_show")(
            context, {"id": data_dict["id"], "include_plugin_data": include_plugin_data}
        )
    )
    return output


@toolkit.side_effect_free
@toolkit.chained_action
def package_search(up_func, context, data_dict):
    search_results = up_func(context, data_dict)
    # Avoid returning datasets without notes when using package_search for DCAT
    if context.get("from_dcat"):
        search_results["results"] = [
            result
            for result in search_results["results"]
            if all(
                [
                    result.get(field) not in [None, ""] and len(result.get(field)) > 0
                    for field in DCAT_DATASET_FIELDS
                ]
            )
        ]

    return search_results
