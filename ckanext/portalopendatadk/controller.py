from ckan.controllers.user import UserController
import logging as log
from ckan import authz
from ckan.common import c
import ckan.lib.helpers as h



class ODDKUserController(UserController):
    def __before__(self, action, **env):
        UserController.__before__(self, action, **env)

        log.error(authz.is_sysadmin(c.user))

        # Verify user is a sysadmin, else redirect to the home page
        if not authz.is_sysadmin(c.user):
            h.redirect_to(controller='home', action='index')
