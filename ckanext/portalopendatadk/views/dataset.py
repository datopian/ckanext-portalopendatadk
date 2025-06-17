# encoding: utf-8
from __future__ import annotations

import logging
import inspect
from collections import OrderedDict
from functools import partial
from typing_extensions import TypeAlias
from urllib.parse import urlencode
from typing import Any, Iterable, Optional, Union
import json

from flask import Blueprint
from flask.views import MethodView
from jinja2.exceptions import TemplateNotFound
from werkzeug.datastructures import MultiDict
from ckan.common import asbool, current_user

import ckan.lib.base as base
from ckan.lib.helpers import helper_functions as h
from ckan.lib.helpers import Page
import ckan.lib.navl.dictization_functions as dict_fns
import ckan.logic as logic
import ckan.model as model
import ckan.plugins as plugins
import ckan.authz as authz
from ckan.common import _, config, g, request
from ckan.views.home import CACHE_PARAMETERS
from ckan.lib.plugins import lookup_package_plugin
from ckan.lib.search import (
    SearchError,
    SearchQueryError,
    SearchIndexError,
    SolrConnectionError,
)
from ckan.types import Context, Response


NotFound = logic.NotFound
NotAuthorized = logic.NotAuthorized
ValidationError = logic.ValidationError
check_access = logic.check_access
get_action = logic.get_action
tuplize_dict = logic.tuplize_dict
clean_dict = logic.clean_dict
parse_params = logic.parse_params
flatten_to_string_key = logic.flatten_to_string_key

log = logging.getLogger(__name__)

dataset = Blueprint(
    "oddk-dataset",
    __name__,
    url_prefix="/dataset",
    url_defaults={"package_type": "dataset"},
)


def _setup_template_variables(
    context: Context, data_dict: dict[str, Any], package_type: Optional[str] = None
) -> None:
    return lookup_package_plugin(package_type).setup_template_variables(
        context, data_dict
    )


def _get_pkg_template(template_type: str, package_type: Optional[str] = None) -> str:
    pkg_plugin = lookup_package_plugin(package_type)
    method = getattr(pkg_plugin, template_type)
    signature = inspect.signature(method)
    if len(signature.parameters):
        return method(package_type)
    else:
        return method()


def _encode_params(params: Iterable[tuple[str, Any]]):
    return [(k, v.encode("utf-8") if isinstance(v, str) else str(v)) for k, v in params]


Params: TypeAlias = "list[tuple[str, Any]]"


def url_with_params(url: str, params: Params) -> str:
    params = _encode_params(params)
    return url + "?" + urlencode(params)


def search_url(params: Params, package_type: Optional[str] = None) -> str:
    if not package_type:
        package_type = "dataset"
    url = h.url_for("{0}.search".format(package_type))
    return url_with_params(url, params)


def remove_field(
    package_type: Optional[str],
    key: str,
    value: Optional[str] = None,
    replace: Optional[str] = None,
):
    if not package_type:
        package_type = "dataset"
    url = h.url_for("{0}.search".format(package_type))
    return h.remove_url_param(key, value=value, replace=replace, alternative_url=url)


def _tag_string_to_list(tag_string: str) -> list[dict[str, str]]:
    """This is used to change tags from a sting to a list of dicts."""
    out: list[dict[str, str]] = []
    for tag in tag_string.split(","):
        tag = tag.strip()
        if tag:
            out.append({"name": tag, "state": "active"})
    return out


def _form_save_redirect(
    pkg_name: str, action: str, package_type: Optional[str] = None
) -> Response:
    """This redirects the user to the CKAN package/read page,
    unless there is request parameter giving an alternate location,
    perhaps an external website.
    @param pkg_name - Name of the package just edited
    @param action - What the action of the edit was
    """
    assert action in ("new", "edit")
    url = request.args.get("return_to") or config.get("package_%s_return_url" % action)
    if url:
        url = url.replace("<NAME>", pkg_name)
    else:
        if not package_type:
            package_type = "dataset"
        url = h.url_for("{0}.read".format(package_type), id=pkg_name)
    return h.redirect_to(url)


def _get_package_type(id: str) -> str:
    """
    Given the id of a package this method will return the type of the
    package, or 'dataset' if no type is currently set
    """
    pkg = model.Package.get(id)
    if pkg:
        return pkg.type or "dataset"
    return "dataset"


class CreateView(MethodView):
    def _is_save(self) -> bool:
        return "save" in request.form

    def _prepare(self) -> Context:  # noqa

        context: Context = {
            "user": current_user.name,
            "auth_user_obj": current_user,
            "save": self._is_save(),
        }
        try:
            check_access("package_create", context)
        except NotAuthorized:
            return base.abort(403, _("Unauthorized to create a package"))
        return context

    def post(self, package_type: str) -> Union[Response, str]:
        # The staged add dataset used the new functionality when the dataset is
        # partially created so we need to know if we actually are updating or
        # this is a real new.
        context = self._prepare()
        is_an_update = False
        ckan_phase = request.form.get("_ckan_phase")
        try:
            data_dict = clean_dict(
                dict_fns.unflatten(tuplize_dict(parse_params(request.form)))
            )

            documentation_upload = request.files.get("upload")

            if documentation_upload:
                data_dict["upload"] = documentation_upload
        except dict_fns.DataError:
            return base.abort(400, _("Integrity Error"))
        try:
            if ckan_phase:
                # prevent clearing of groups etc
                context["allow_partial_update"] = True
                # sort the tags
                if "tag_string" in data_dict:
                    data_dict["tags"] = _tag_string_to_list(data_dict["tag_string"])
                if data_dict.get("pkg_name"):
                    is_an_update = True
                    # This is actually an update not a save
                    data_dict["id"] = data_dict["pkg_name"]
                    del data_dict["pkg_name"]
                    # don't change the dataset state
                    data_dict["state"] = "draft"
                    # this is actually an edit not a save
                    pkg_dict = get_action("package_update")(context, data_dict)

                    # redirect to add dataset resources
                    url = h.url_for(
                        "{}_resource.new".format(package_type), id=pkg_dict["name"]
                    )
                    return h.redirect_to(url)
                # Make sure we don't index this dataset
                if request.form["save"] not in ["go-resource", "go-metadata"]:
                    data_dict["state"] = "draft"
                # allow the state to be changed
                context["allow_state_change"] = True

            data_dict["type"] = package_type
            pkg_dict = get_action("package_create")(context, data_dict)

            create_on_ui_requires_resources = config.get(
                "ckan.dataset.create_on_ui_requires_resources"
            )
            if ckan_phase:
                if create_on_ui_requires_resources:
                    # redirect to add dataset resources if
                    # create_on_ui_requires_resources is set to true
                    url = h.url_for(
                        "{}_resource.new".format(package_type), id=pkg_dict["name"]
                    )
                    return h.redirect_to(url)

                get_action("package_update")(
                    Context(context, allow_state_change=True),
                    dict(pkg_dict, state="active"),
                )
                return h.redirect_to("{}.read".format(package_type), id=pkg_dict["id"])

            return _form_save_redirect(
                pkg_dict["name"], "new", package_type=package_type
            )
        except NotAuthorized:
            return base.abort(403, _("Unauthorized to read package"))
        except NotFound:
            return base.abort(404, _("Dataset not found"))
        except SearchIndexError as e:
            try:
                exc_str = str(repr(e.args))
            except Exception:  # We don't like bare excepts
                exc_str = str(str(e))
            return base.abort(
                500, _("Unable to add package to search index.") + exc_str
            )
        except ValidationError as e:
            errors = e.error_dict
            error_summary = e.error_summary
            if is_an_update:
                # we need to get the state of the dataset to show the stage we
                # are on.
                pkg_dict = get_action("package_show")(context, data_dict)
                data_dict["state"] = pkg_dict["state"]
                return EditView().get(
                    package_type, data_dict["id"], data_dict, errors, error_summary
                )
            data_dict["state"] = "none"
            return self.get(package_type, data_dict, errors, error_summary)

    def get(
        self,
        package_type: str,
        data: Optional[dict[str, Any]] = None,
        errors: Optional[dict[str, Any]] = None,
        error_summary: Optional[dict[str, Any]] = None,
    ) -> str:
        context = self._prepare()
        if data and "type" in data:
            package_type = data["type"]

        data = data or clean_dict(
            dict_fns.unflatten(
                tuplize_dict(parse_params(request.args, ignore_keys=CACHE_PARAMETERS))
            )
        )
        resources_json = h.dump_json(data.get("resources", []))
        # convert tags if not supplied in data
        if data and not data.get("tag_string"):
            data["tag_string"] = ", ".join(
                h.dict_list_reduce(data.get("tags", {}), "name")
            )

        errors = errors or {}
        error_summary = error_summary or {}
        # in the phased add dataset we need to know that
        # we have already completed stage 1
        stage = ["active"]
        if data.get("state", "").startswith("draft"):
            stage = ["active", "complete"]

        # if we are creating from a group then this allows the group to be
        # set automatically
        data["group_id"] = request.args.get("group") or request.args.get(
            "groups__0__id"
        )

        form_snippet = _get_pkg_template("package_form", package_type=package_type)
        form_vars: dict[str, Any] = {
            "data": data,
            "errors": errors,
            "error_summary": error_summary,
            "action": "new",
            "stage": stage,
            "dataset_type": package_type,
            "form_style": "new",
        }
        errors_json = h.dump_json(errors)

        # TODO: remove
        g.resources_json = resources_json
        g.errors_json = errors_json

        _setup_template_variables(context, {}, package_type=package_type)

        new_template = _get_pkg_template("new_template", package_type)
        return base.render(
            new_template,
            extra_vars={
                "form_vars": form_vars,
                "form_snippet": form_snippet,
                "dataset_type": package_type,
                "resources_json": resources_json,
                "errors_json": errors_json,
            },
        )


class EditView(MethodView):
    def _prepare(self) -> Context:
        context: Context = {
            "user": current_user.name,
            "auth_user_obj": current_user,
            "save": "save" in request.form,
        }
        return context

    def post(self, package_type: str, id: str) -> Union[Response, str]:
        context = self._prepare()
        package_type = _get_package_type(id) or package_type
        log.debug("Package save request name: %s POST: %r", id, request.form)
        try:
            data_dict = clean_dict(
                dict_fns.unflatten(tuplize_dict(parse_params(request.form)))
            )

            documentation_upload = request.files.get("upload")

            if documentation_upload:
                # if we are uploading a file then we need to set the
                # documentation field
                data_dict["upload"] = documentation_upload

        except dict_fns.DataError:
            return base.abort(400, _("Integrity Error"))
        try:
            if "_ckan_phase" in data_dict:
                # we allow partial updates to not destroy existing resources
                context["allow_partial_update"] = True
                if "tag_string" in data_dict:
                    data_dict["tags"] = _tag_string_to_list(data_dict["tag_string"])
                del data_dict["_ckan_phase"]
                del data_dict["save"]
            data_dict["id"] = id
            pkg_dict = get_action("package_update")(context, data_dict)

            return _form_save_redirect(
                pkg_dict["name"], "edit", package_type=package_type
            )
        except NotAuthorized:
            return base.abort(403, _("Unauthorized to read package %s") % id)
        except NotFound:
            return base.abort(404, _("Dataset not found"))
        except SearchIndexError as e:
            try:
                exc_str = str(repr(e.args))
            except Exception:  # We don't like bare excepts
                exc_str = str(str(e))
            return base.abort(500, _("Unable to update search index.") + exc_str)
        except ValidationError as e:
            errors = e.error_dict
            error_summary = e.error_summary
            return self.get(package_type, id, data_dict, errors, error_summary)

    def get(
        self,
        package_type: str,
        id: str,
        data: Optional[dict[str, Any]] = None,
        errors: Optional[dict[str, Any]] = None,
        error_summary: Optional[dict[str, Any]] = None,
    ) -> Union[Response, str]:
        context = self._prepare()
        package_type = _get_package_type(id) or package_type

        try:
            view_context = context.copy()
            view_context["for_view"] = True
            pkg_dict = get_action("package_show")(view_context, {"id": id})
            context["for_edit"] = True
            old_data = get_action("package_show")(context, {"id": id})
            # old data is from the database and data is passed from the
            # user if there is a validation error. Use users data if there.
            if data:
                old_data.update(data)
            data = old_data
        except (NotFound, NotAuthorized):
            return base.abort(404, _("Dataset not found"))
        assert data is not None
        # are we doing a multiphase add?
        if data.get("state", "").startswith("draft"):
            g.form_action = h.url_for("{}.new".format(package_type))
            g.form_style = "new"

            return CreateView().get(
                package_type, data=data, errors=errors, error_summary=error_summary
            )

        pkg = context.get("package")
        resources_json = h.dump_json(data.get("resources", []))
        user = current_user.name
        try:
            check_access("package_update", context, {"id": pkg_dict.get("id")})
        except NotAuthorized:
            return base.abort(403, _("User %r not authorized to edit %s") % (user, id))
        # convert tags if not supplied in data
        if data and not data.get("tag_string"):
            data["tag_string"] = ", ".join(
                h.dict_list_reduce(pkg_dict.get("tags", {}), "name")
            )
        errors = errors or {}
        form_snippet = _get_pkg_template("package_form", package_type=package_type)
        form_vars: dict[str, Any] = {
            "data": data,
            "errors": errors,
            "error_summary": error_summary,
            "action": "edit",
            "dataset_type": package_type,
            "form_style": "edit",
        }
        errors_json = h.dump_json(errors)

        # TODO: remove
        g.pkg = pkg
        g.resources_json = resources_json
        g.errors_json = errors_json

        _setup_template_variables(context, {"id": id}, package_type=package_type)

        # we have already completed stage 1
        form_vars["stage"] = ["active"]
        if data.get("state", "").startswith("draft"):
            form_vars["stage"] = ["active", "complete"]

        edit_template = _get_pkg_template("edit_template", package_type)
        return base.render(
            edit_template,
            extra_vars={
                "form_vars": form_vars,
                "form_snippet": form_snippet,
                "dataset_type": package_type,
                "pkg_dict": pkg_dict,
                "pkg": pkg,
                "resources_json": resources_json,
                "errors_json": errors_json,
            },
        )


def register_dataset_plugin_rules(blueprint: Blueprint):
    blueprint.add_url_rule("/new", view_func=CreateView.as_view(str("new")))
    blueprint.add_url_rule("/edit/<id>", view_func=EditView.as_view(str("edit")))


register_dataset_plugin_rules(dataset)
# remove this when we improve blueprint registration to be explicit:
dataset.auto_register = False  # type: ignore
