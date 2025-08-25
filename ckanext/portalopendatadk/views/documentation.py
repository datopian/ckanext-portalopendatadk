# encoding: utf-8
import logging
import mimetypes
import os

from flask import Blueprint, make_response
from botocore.exceptions import ClientError

import ckan.model as model
from ckan.common import _, current_user, config
import ckan.logic as logic
import ckan.lib.helpers as h
from ckan import plugins as toolkit
from ckan.lib.base import abort
from ckan.plugins.toolkit import get_action

import ckan.lib.uploader as uploader
from ckan.lib import munge

log = logging.getLogger(__name__)

doc_blueprint = Blueprint("oddk_docs", __name__)


def documentation_download(dataset_name, documentation_id):
    context = {
        "model": model,
        "session": model.Session,
        "user": current_user.name,
        "auth_user_obj": current_user,
    }

    try:
        rsc = get_action("package_show")(context, {"id": dataset_name})
    except (logic.NotFound, logic.NotAuthorized):
        abort(404, _("Resource not found"))

    documentation = rsc.get("documentation")

    if documentation and "http" in documentation:
        return h.redirect_to(documentation)

    if documentation:
        raw_plugins = config.get("ckan.plugins")
        enabled_plugins = (
            raw_plugins.split()
            if isinstance(raw_plugins, str)
            else raw_plugins if isinstance(raw_plugins, list) else []
        )
        if "s3filestore" not in enabled_plugins:
            path = uploader.get_storage_path()
            filepath = os.path.join(
                path,
                "resources",
                documentation_id[0:3],
                documentation_id[3:6],
                documentation_id[6:],
            )

            if not os.path.exists(filepath):
                abort(404, _("Resource data not found"))

            content_type, _encoding = mimetypes.guess_type(documentation)
            with open(filepath, "rb") as f:
                data = f.read()

            return make_response(
                data,
                headers={
                    "Content-Type": content_type or "application/octet-stream",
                    "Content-Disposition": f'attachment; filename="{os.path.basename(documentation)}"',
                },
            )
        else:
            rsc["url"] = documentation
            upload = uploader.get_resource_uploader(rsc)
            bucket_name = config.get("ckanext.s3filestore.aws_bucket_name")
            host_name = config.get("ckanext.s3filestore.host_name")
            signed_url_expiry = int(
                config.get("ckanext.s3filestore.signed_url_expiry", "60")
            )

            munged_doc = munge.munge_filename(documentation)
            key_path = os.path.join("resources", documentation_id, munged_doc)

            try:
                s3 = upload.get_s3_session()
                client = s3.client(service_name="s3", endpoint_url=host_name)
                url = client.generate_presigned_url(
                    ClientMethod="get_object",
                    Params={
                        "Bucket": bucket_name,
                        "Key": key_path,
                        "ResponseContentDisposition": f"attachment; filename={documentation}",
                        "ResponseContentType": "application/octet-stream",
                    },
                    ExpiresIn=signed_url_expiry,
                )
                return h.redirect_to(url)
            except ClientError as ex:
                if ex.response.get("Error", {}).get("Code") == "NoSuchKey":
                    if config.get(
                        "ckanext.s3filestore.filesystem_download_fallback", False
                    ):
                        log.info(
                            f"Attempting filesystem fallback for resource {documentation_id}"
                        )
                        return h.redirect_to(
                            toolkit.url_for(
                                controller="ckanext.s3filestore.controller:S3Controller",
                                action="filesystem_resource_download",
                                id=id,
                                documentation_id=documentation_id,
                                filename=documentation,
                            )
                        )
                    abort(404, _("Resource data not found"))
                raise ex

    abort(404, _("No documentation found"))


doc_blueprint.add_url_rule(
    "/dataset/<dataset_name>/documentation/<documentation_id>",
    view_func=documentation_download,
)
