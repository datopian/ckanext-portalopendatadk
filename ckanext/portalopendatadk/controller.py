import logging as log

from ckan.controllers.user import UserController, set_repoze_user
from ckan import authz
from ckan.common import c
import ckan.lib.helpers as h
import ckan.lib.base as base
import ckan.model as model
import ckan.logic as logic
from ckan.common import _, c, request
import ckan.lib.navl.dictization_functions as dictization_functions
import ckan.lib.captcha as captcha

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


class ODDKUserController(UserController):
    def __before__(self, action, **env):
        UserController.__before__(self, action, **env)

        # Verify user is an admin, else redirect to the home page
        if not user_has_admin_access(False):
            h.redirect_to(controller='home', action='index')

    def new(self, data=None, errors=None, error_summary=None):
        '''GET to display a form for registering a new user.
           or POST the form data to actually do the user registration.
        '''
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
            captcha.check_recaptcha(request)
            user = get_action('user_create')(context, data_dict)
        except NotAuthorized:
            abort(403, _('Unauthorized to create user %s') % '')
        except NotFound, e:
            abort(404, _('User not found'))
        except DataError:
            abort(400, _(u'Integrity Error'))
        except captcha.CaptchaError:
            error_msg = _(u'Bad Captcha. Please try again.')
            h.flash_error(error_msg)
            return self.new(data_dict)
        except ValidationError, e:
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
