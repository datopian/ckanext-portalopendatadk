from ckan.controllers.user import UserController
import logging as log
from ckan import authz
from ckan.common import c
import ckan.lib.helpers as h
from ckanext.portalopendatadk.helpers import user_has_admin_access



class ODDKUserController(UserController):
    def __before__(self, action, **env):
        UserController.__before__(self, action, **env)

        # Verify user is an admin, else redirect to the home page
        if not user_has_admin_access(False):
            h.redirect_to(controller='home', action='index')
