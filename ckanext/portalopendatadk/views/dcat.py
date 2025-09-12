# -*- coding: utf-8 -*-
from flask import Blueprint, jsonify, make_response, Response
import json
from ckantoolkit import config
import logging

from ckan.views.dataset import CreateView

import ckan.plugins.toolkit as toolkit
import ckanext.dcat.utils as utils
from ckan.views.home import index as index_endpoint
from ckan.views.dataset import read as read_endpoint
from ckanext.dcat.utils import CONTENT_TYPES, parse_accept_header
from ckanext.dcat.helpers import endpoints_enabled
from ckanext.dcat.processors import RDFProfileException
import ckan.model as model
log = logging.getLogger(__name__)


dcat = Blueprint(
    "dcat_oddk",
    __name__
)


def _get_package_type(id):
    """
    Given the id of a package this method will return the type of the
    package, or 'dataset' if no type is currently set
    """
    pkg = model.Package.get(id)
    if pkg:
        return pkg.type or "dataset"
    return None


def check_access_header():
    _format = None

    # Check Accept headers
    accept_header = toolkit.request.headers.get("Accept", "")
    if accept_header:
        _format = parse_accept_header(accept_header)
    return _format


def read_catalog(_format=None):
    if not _format:
        _format = check_access_header()

    if not _format:
        return index_endpoint()

    # Default to 'danish_dcat_ap' for now
    # _profiles = toolkit.request.params.get('profiles')
    # if _profiles:
    #    _profiles = _profiles.split(',')
    _profiles = ["danish_dcat_ap"]

    fq = toolkit.request.params.get("fq")

    if config.get("ckanext.portalopendatadk.dcat_data_directory_only", False):
        if fq:
            fq = fq + " +data_directory:true"
        else:
            fq = "data_directory:true"

    data_dict = {
        "page": toolkit.request.params.get("page"),
        "modified_since": toolkit.request.params.get("modified_since"),
        "q": toolkit.request.params.get("q"),
        "fq": fq,
        "format": _format,
        "profiles": _profiles,
    }

    try:
        result = toolkit.get_action("dcat_catalog_show")(
            {"from_dcat": True}, data_dict
        )

        response = Response(result)
        response.headers["Content-Type"] = CONTENT_TYPES[_format]
        return response

    except (toolkit.ValidationError, RDFProfileException) as e:
        toolkit.abort(409, str(e))


def read_dataset(_id, _format=None):

    if not _format:
        _format = check_access_header()

    if not _format:
        return read_endpoint(_get_package_type(_id), _id)

    _profiles = toolkit.request.params.get("profiles")
    if _profiles:
        _profiles = _profiles.split(",")


    try:
        result = toolkit.get_action("dcat_dataset_show")(
            {}, {"id": _id, "format": _format, "profiles": _profiles}
        )
        response = Response(result)
        response.headers["Content-Type"] = CONTENT_TYPES[_format]

        return response
    except toolkit.ObjectNotFound:
        toolkit.abort(404)
    except (toolkit.ValidationError, RDFProfileException) as e:
        toolkit.abort(409, str(e))

    return result



dcat.add_url_rule(
    config.get(
        "ckanext.dcat.catalog_endpoint", utils.DEFAULT_CATALOG_ENDPOINT
    ).replace("{_format}", "<_format>"),
    view_func=read_catalog,
)
dcat.add_url_rule("/dataset/<_id>.<_format>", view_func=read_dataset)

dcat.add_url_rule("/", view_func=read_catalog)
dcat.add_url_rule("/dataset/<_id>", view_func=read_dataset)

dcat_json_interface = Blueprint("dcat_json_interface_oddk", __name__)


def dcat_json():
    data_dict = {
        "page": toolkit.request.params.get("page"),
        "modified_since": toolkit.request.params.get("modified_since"),
    }

    try:
        datasets = toolkit.get_action("dcat_datasets_list")({}, data_dict)
    except toolkit.ValidationError as e:
        toolkit.abort(409, str(e))

    content = json.dumps(datasets)

    response = Response(content, content_type="application/json")
    response.headers["Content-Length"] = str(len(content))

    return response


dcat_json_interface.add_url_rule(
    config.get("ckanext.dcat.json_endpoint", "/dcat.json"), view_func=dcat_json
)
