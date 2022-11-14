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
import ckan.lib.mailer as mailer

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

        # Verify user is an admin or we're doing a password reset
        # else redirect to the home page
        if not user_has_admin_access(False) and action != 'request_reset':
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
            # NOTE: On ODDK, we don't need a captcha as there's
            # no public registration.
            # captcha.check_recaptcha(request)
            user = get_action('user_create')(context, data_dict)
        except NotAuthorized:
            abort(403, _('Unauthorized to create user %s') % '')
        except NotFound, e:
            abort(404, _('User not found'))
        except DataError:
            abort(400, _(u'Integrity Error'))

        # NOTE: On ODDK, we don't need a captcha as there's
        # no public registration.
        #
        # except captcha.CaptchaError:
        #     error_msg = _(u'Bad Captcha. Please try again.')
        #     h.flash_error(error_msg)
        #     return self.new(data_dict)

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
                except mailer.MailerException, e:
                    h.flash_error(_('Could not send reset link: %s') %
                                  unicode(e))

            h.flash_success(
                _('A reset link has been emailed to you '
                  '(unless the account specified does not exist)'))
            h.redirect_to('/')

        return render('user/request_reset.html')
