import logging as log
import json
import mimetypes
#import paste.fileapp
import os
from botocore.exceptions import ClientError

from ckan.controllers.user import UserController, set_repoze_user
from ckan import authz
from ckan.common import c
import ckan.lib.helpers as h
import ckan.lib.base as base
import ckan.model as model
import ckan.logic as logic
from ckan.common import _, c, request, config, response
import ckan.lib.navl.dictization_functions as dictization_functions
import ckan.lib.captcha as captcha
import ckan.lib.mailer as mailer
from ckan.plugins import toolkit
import ckan.lib.uploader as uploader
from ckan.lib import munge

if toolkit.check_ckan_version(min_version='2.1'):
    BaseController = toolkit.BaseController
else:
    from ckan.lib.base import BaseController

if toolkit.check_ckan_version(max_version='2.8.99'):
    from ckan.controllers.package import PackageController
    from ckan.controllers.home import HomeController
    read_endpoint = PackageController().read
    index_endpoint = HomeController().index
else:
    from ckan.views.home import index as index_endpoint
    from ckan.views.dataset import read as read_endpoint

from ckanext.dcat.utils import CONTENT_TYPES, parse_accept_header
from ckanext.dcat.processors import RDFProfileException

from ckanext.portalopendatadk.helpers import user_has_admin_access

abort = base.abort
render = base.render

check_access = logic.check_access
get_action = logic.get_action
NotAuthorized = logic.NotAuthorized
NotFound = logic.NotFound
ValidationError = logic.ValidationError

DataError = dictization_functions.DataError
unflatten = dictization_functions.unflatten

log = log.getLogger(__name__)

def _get_package_type(id):
    """
    Given the id of a package this method will return the type of the
    package, or 'dataset' if no type is currently set
    """
    pkg = model.Package.get(id)
    if pkg:
        return pkg.type or 'dataset'
    return None


def check_access_header():
    _format = None

    # Check Accept headers
    accept_header = toolkit.request.headers.get('Accept', '')
    if accept_header:
        _format = parse_accept_header(accept_header)
    return _format


class ODDKUserController(UserController):
    def __before__(self, action, **env):
        UserController.__before__(self, action, **env)

        # Verify user is an admin or we're doing a password reset
        # else redirect to the home page
        if not user_has_admin_access(False) and action != 'request_reset':
            h.redirect_to(controller='home', action='index')
        if not authz.is_sysadmin(c.user) and action == 'register':
            h.redirect_to(controller='home', action='index')

    def new(self, data=None, errors=None, error_summary=None):
        """GET to display a form for registering a new user.
           or POST the form data to actually do the user registration.
        """
        context = {'model': model,
                   'session': model.Session,
                   'user': c.user,
                   'auth_user_obj': c.userobj,
                   'schema': self._new_form_to_db_schema(),
                   'save': 'save' in request.params}

        try:
            check_access('user_create', context)
        except NotAuthorized:
            abort(403, _('Unauthorized to create a user'))

        if context['save'] and not data and request.method == 'POST':
            return self._save_new(context)

        # NOTE: On ODDK, we need to check if the user is a sysadmin _or_ an
        # organization admin. We should never pass this check, but I'll
        # leave it here for now, just in case.
        if c.user and not data and not user_has_admin_access(False):
            # #1799 Don't offer the registration form if already logged in
            return render('user/logout_first.html')

        data = data or {}
        errors = errors or {}
        error_summary = error_summary or {}
        vars = {'data': data, 'errors': errors, 'error_summary': error_summary}

        c.is_sysadmin = authz.is_sysadmin(c.user)
        c.form = render(self.new_user_form, extra_vars=vars)
        return render('user/new.html')

    def _save_new(self, context):
        try:
            data_dict = logic.clean_dict(unflatten(
                logic.tuplize_dict(logic.parse_params(request.params))))
            context['message'] = data_dict.get('log_message', '')
            # NOTE: On ODDK, we don't need a captcha as there's
            # no public registration.
            # captcha.check_recaptcha(request)
            user = get_action('user_create')(context, data_dict)
        except NotAuthorized:
            abort(403, _('Unauthorized to create user %s') % '')
        except NotFound as e:
            abort(404, _('User not found'))
        except DataError:
            abort(400, _('Integrity Error'))

        # NOTE: On ODDK, we don't need a captcha as there's
        # no public registration.
        #
        # except captcha.CaptchaError:
        #     error_msg = _(u'Bad Captcha. Please try again.')
        #     h.flash_error(error_msg)
        #     return self.new(data_dict)

        except ValidationError as e:
            errors = e.error_dict
            error_summary = e.error_summary
            return self.new(data_dict, errors, error_summary)
        if not c.user:
            # log the user in programatically
            set_repoze_user(data_dict['name'])
            h.redirect_to(controller='user', action='me')
        else:
            # NOTE: On ODDK, we bypass this. Only sysadmins and organization admins
            # can register new users.
            #
            # #1799 User has managed to register whilst logged in - warn user
            # they are not re-logged in as new user.
            #
            # h.flash_success(_('User "%s" is now registered but you are still '
            #                 'logged in as "%s" from before') %
            #                 (data_dict['name'], c.user))

            # NOTE: On ODDK, we should always redirect to the activity page
            # for the newly created user.
            #
            #if authz.is_sysadmin(c.user):
            #    # the sysadmin created a new user. We redirect him to the
            #    # activity page for the newly created user
            #    h.redirect_to(controller='user',
            #                  action='activity',
            #                  id=data_dict['name'])
            #else:
            #    return render('user/logout_first.html')

            h.flash_success(_('User "%s" is now registered.' % data_dict['name']))
            h.redirect_to(controller='user', action='activity', id=data_dict['name'])

    def request_reset(self):
        context = {
            'model': model, 'session': model.Session,
            'user': c.user, 'auth_user_obj': c.userobj,
            'ignore_auth': True
        }
        data_dict = {'id': request.params.get('user')}

        try:
            # NOTE: we need a new variable to knonw this is a reset
            context['from_request_reset'] = True
            check_access('request_reset', context)
        except NotAuthorized:
            abort(403, _('Unauthorized to request reset password.'))

        if request.method == 'POST':
            id = request.params.get('user')

            context = {
                'model': model,
                'user': c.user,
                'ignore_auth': True,
            }

            data_dict = {'id': id}
            user_obj = None
            try:
                user_dict = get_action('user_show')(context, data_dict)
                user_obj = context['user_obj']
            except NotFound:
                # Try searching the user
                del data_dict['id']
                data_dict['q'] = id

                if id and len(id) > 2:
                    user_list = get_action('user_list')(context, data_dict)
                    if len(user_list) == 1:
                        # This is ugly, but we need the user object for the
                        # mailer,
                        # and user_list does not return them
                        del data_dict['q']
                        data_dict['id'] = user_list[0]['id']
                        user_dict = get_action('user_show')(context, data_dict)
                        user_obj = context['user_obj']
                # NOTE: We override core behavior because we don't want to give 
                # away any information about the existence of a user
                #    elif len(user_list) > 1:
                #        h.flash_error(_('"%s" matched several users') % (id))
                #    else:
                #        h.flash_error(_('No such user: %s') % id)
                #else:
                #    h.flash_error(_('No such user: %s') % id)

            if user_obj:
                try:
                    mailer.send_reset_link(user_obj)
                except mailer.MailerException as e:
                    h.flash_error(_('Could not send reset link: %s') %
                                  str(e))

            h.flash_success(
                _('A reset link has been emailed to you '
                  '(unless the account specified does not exist)'))
            h.redirect_to('/')

        return render('user/request_reset.html')


class DCATController(BaseController):
    def read_catalog(self, _format=None):

        if not _format:
            _format = check_access_header()

        if not _format:
            return index_endpoint()

        # Default to 'danish_dcat_ap' for now
        #_profiles = toolkit.request.params.get('profiles')
        #if _profiles:
        #    _profiles = _profiles.split(',')
        _profiles = ['danish_dcat_ap']

        fq = toolkit.request.params.get('fq')

        if config.get('ckanext.portalopendatadk.dcat_data_directory_only', False):
            if fq:
                fq = fq + ' +data_directory:true'
            else:
                fq = 'data_directory:true'

        data_dict = {
            'page': toolkit.request.params.get('page'),
            'modified_since': toolkit.request.params.get('modified_since'),
            'q': toolkit.request.params.get('q'),
            'fq': fq,
            'format': _format,
            'profiles': _profiles
        }

        toolkit.response.headers.update(
            {'Content-type': CONTENT_TYPES[_format]})
        try:
            return toolkit.get_action('dcat_catalog_show')({'from_dcat': True}, data_dict)
        except (toolkit.ValidationError, RDFProfileException) as e:
            toolkit.abort(409, str(e))

    def read_dataset(self, _id, _format=None):

        if not _format:
            _format = check_access_header()

        if not _format:
            if toolkit.check_ckan_version(max_version='2.8.99'):
                return read_endpoint(_id)
            else:
                return read_endpoint(_get_package_type(_id), _id)

        _profiles = toolkit.request.params.get('profiles')
        if _profiles:
            _profiles = _profiles.split(',')

        toolkit.response.headers.update(
            {'Content-type': CONTENT_TYPES[_format]})

        try:
            result = toolkit.get_action('dcat_dataset_show')({}, {'id': _id,
                'format': _format, 'profiles': _profiles})
        except toolkit.ObjectNotFound:
            toolkit.abort(404)
        except (toolkit.ValidationError, RDFProfileException) as e:
            toolkit.abort(409, str(e))

        return result

    def dcat_json(self):

        data_dict = {
            'page': toolkit.request.params.get('page'),
            'modified_since': toolkit.request.params.get('modified_since'),
        }

        try:
            datasets = toolkit.get_action('dcat_datasets_list')({},
                                                                data_dict)
        except toolkit.ValidationError as e:
            toolkit.abort(409, str(e))

        content = json.dumps(datasets)

        toolkit.response.headers['Content-Type'] = 'application/json'
        toolkit.response.headers['Content-Length'] = len(content)

        return content


class ODDKDocumentationController(base.BaseController):
    def documentation_download(self, id, resource_id, filename=None):
        """
        Provides a direct download by either redirecting the user to the url
        stored or downloading an uploaded file directly.
        """
        context = {'model': model, 'session': model.Session,
                   'user': c.user, 'auth_user_obj': c.userobj}

        try:
            rsc = get_action('package_show')(context, {'id': id})
        except (NotFound, NotAuthorized):
            abort(404, _('Resource not found'))

        documentation = rsc.get('documentation')

        if 'http' in documentation:
            h.redirect_to(documentation)
        elif documentation is not None:
            ckan_plugins = config.get('ckan.plugins', '').split()
            if 's3filestore' not in ckan_plugins:
                path = uploader.get_storage_path()
                filepath = os.path.join(
                    path, 'resources', resource_id[0:3], resource_id[3:6], resource_id[6:]
                )
                #fileapp = paste.fileapp.FileApp(filepath)

                try:
                    status, headers, app_iter = None, None, None #request.call_application(fileapp)
                except OSError:
                    abort(404, _('Resource data not found'))

                response.headers.update(dict(headers))
                content_type, content_enc = mimetypes.guess_type(
                    documentation)

                if content_type:
                    response.headers['Content-Type'] = content_type

                response.status = status
                return app_iter
            else:
                rsc['url'] = documentation
                upload = uploader.get_resource_uploader(rsc)
                bucket_name = config.get("ckanext.s3filestore.aws_bucket_name")
                host_name = config.get("ckanext.s3filestore.host_name")
                bucket = upload.get_s3_bucket(bucket_name)
                signed_url_expiry = int(
                    config.get("ckanext.s3filestore.signed_url_expiry", "60")
                )

                if documentation is None:
                    documentation = os.path.basename(rsc["url"])

                munged_documentation = munge.munge_filename(documentation)

                key_path = os.path.join(
                    'resources', resource_id, munged_documentation
                )

                key = munged_documentation

                if key is None:
                    log.warn(
                        "Key '{0}' not found in bucket '{1}'".format(key_path, bucket_name)
                    )

                try:
                    # Small workaround to manage downloading of large files
                    # We are using redirect to minio's resource public URL
                    s3 = upload.get_s3_session()
                    client = s3.client(service_name="s3", endpoint_url=host_name)
                    contentDeposition = "attachment; filename=" + documentation
                    url = client.generate_presigned_url(
                        ClientMethod="get_object",
                        Params={
                            "Bucket": bucket.name,
                            "Key": key_path,
                            "ResponseContentDisposition": contentDeposition,
                            "ResponseContentType": "application/octet-stream",
                        },
                        ExpiresIn=signed_url_expiry,
                    )
                    toolkit.redirect_to(url)

                except ClientError as ex:
                    if ex.response["Error"]["Code"] == "NoSuchKey":
                        # attempt fallback
                        if config.get(
                            "ckanext.s3filestore.filesystem_download_fallback", False
                        ):
                            log.info(
                                "Attempting filesystem fallback for resource {0}".format(
                                    resource_id
                                )
                            )
                            url = toolkit.url_for(
                                controller="ckanext.s3filestore.controller:S3Controller",
                                action="filesystem_resource_download",
                                id=id,
                                resource_id=resource_id,
                                filename=documentation
                            )
                            toolkit.redirect_to(url)

                        abort(404, _("Resource data not found"))
                    else:
                        raise ex
