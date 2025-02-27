import json
import logging
from flask import Blueprint, request, abort, Response
from ckan.plugins import toolkit
from ckan.common import config
from ckanext.dcat.utils import CONTENT_TYPES, parse_accept_header
from ckanext.dcat.processors import RDFProfileException

log = logging.getLogger(__name__)

dcat_blueprint = Blueprint("dcat", __name__, url_prefix="/dcat")

def check_access_header():
    """Checks the Accept headers to determine the format."""
    accept_header = request.headers.get("Accept", "")
    return parse_accept_header(accept_header) if accept_header else None

@dcat_blueprint.route("/catalog", methods=["GET"])
def read_catalog():
    """Returns the DCAT catalog in the requested format."""
    _format = request.args.get("format") or check_access_header()

    if not _format:
        return abort(400, "Format not specified")

    _profiles = request.args.get("profiles", "danish_dcat_ap").split(",")

    fq = request.args.get("fq")
    if config.get("ckanext.portalopendatadk.dcat_data_directory_only", False):
        fq = f"{fq} +data_directory:true" if fq else "data_directory:true"

    data_dict = {
        "page": request.args.get("page"),
        "modified_since": request.args.get("modified_since"),
        "q": request.args.get("q"),
        "fq": fq,
        "format": _format,
        "profiles": _profiles,
    }

    try:
        result = toolkit.get_action("dcat_catalog_show")({"from_dcat": True}, data_dict)
        return Response(result, content_type=CONTENT_TYPES.get(_format, "application/json"))
    except (toolkit.ValidationError, RDFProfileException) as e:
        abort(409, str(e))

@dcat_blueprint.route("/dataset/<_id>", methods=["GET"])
def read_dataset(_id):
    """Returns the dataset in the requested DCAT format."""
    _format = request.args.get("format") or check_access_header()

    if not _format:
        return abort(400, "Format not specified")

    _profiles = request.args.get("profiles", "").split(",") if request.args.get("profiles") else []

    try:
        result = toolkit.get_action("dcat_dataset_show")({}, {"id": _id, "format": _format, "profiles": _profiles})
        return Response(result, content_type=CONTENT_TYPES.get(_format, "application/json"))
    except toolkit.ObjectNotFound:
        abort(404, "Dataset not found")
    except (toolkit.ValidationError, RDFProfileException) as e:
        abort(409, str(e))

@dcat_blueprint.route("/datasets.json", methods=["GET"])
def dcat_json():
    """Returns a JSON list of datasets."""
    data_dict = {
        "page": request.args.get("page"),
        "modified_since": request.args.get("modified_since"),
    }

    try:
        datasets = toolkit.get_action("dcat_datasets_list")({}, data_dict)
        content = json.dumps(datasets)
        return Response(content, content_type="application/json")
    except toolkit.ValidationError as e:
        abort(409, str(e))
