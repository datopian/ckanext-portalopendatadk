ckanext-portalopendata
=========
Theme for portal.opendata.dk

## Custom user access permissions

This extension has custom code that prevents users other than organization admins and sysadmins from viewing user-related pages and API calls. The following can only be accessed by admins:

- Pages:
  - User list page (`/user`)
  - User edit pages (`/user/edit/<USERNAME>`)
  - User registration (`/user/register`)
- API calls:
  - `user_list`
  - `user_show` (blocked for any user other than themselves)

If a user doesn't have the correct permissions, they will be re-directed to the home page.

**New user registration** is not longer visible for users that aren't logged in, and registration of new users is limited to sysadmins and organization admins. For sysadmins, it can be found both on `/ckan-admin` and `/dashboard`. Organization admins can find it on `/dashboard`.

If any future custom work needs to change this behavior, see the functions in [`auth_functions.py`](ckanext/portalopendatadk/auth_functions.py), `user_has_admin_access` in [`helpers.py`](ckanext/portalopendatadk/helpers.py), the class (`ODDKUserController`) in [`controller.py`](ckanext/portalopendatadk/controller.py), and `before_map` in [`plugin.py`](ckanext/portalopendatadk/plugin.py).
