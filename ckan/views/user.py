# encoding: utf-8
from __future__ import annotations

import logging
from typing import Any, Optional, Union

from flask import Blueprint
from flask.views import MethodView
from ckan.common import asbool

import ckan.lib.authenticator as authenticator
import ckan.lib.base as base
import ckan.lib.captcha as captcha
from ckan.lib.helpers import helper_functions as h
from ckan.lib.helpers import Page
from ckan.lib.dictization import model_dictize
import ckan.lib.mailer as mailer
import ckan.lib.navl.dictization_functions as dictization_functions
import ckan.logic as logic
import ckan.logic.schema as schema
import ckan.model as model
import ckan.plugins as plugins
from ckan import authz
from ckan.common import (
    _, config, g, request, current_user, login_user, logout_user, session,
    repr_untrusted
)
from ckan.types import Context, Schema, Response
from ckan.lib import signals

log = logging.getLogger(__name__)

# hooks for subclasses
new_user_form = u'user/new_user_form.html'
edit_user_form = u'user/edit_user_form.html'

user = Blueprint(u'user', __name__, url_prefix=u'/user')


def _edit_form_to_db_schema() -> Schema:
    return schema.user_edit_form_schema()


def _new_form_to_db_schema() -> Schema:
    return schema.user_new_form_schema()


def _perform_reset_form_to_db_schema() -> Schema:
    return schema.user_perform_reset_form_schema()


def _extra_template_variables(context: Context,
                              data_dict: dict[str, Any]) -> dict[str, Any]:
    is_sysadmin = False
    if current_user.is_authenticated:
        is_sysadmin = authz.is_sysadmin(current_user.name)
    try:
        user_dict = logic.get_action(u'user_show')(context, data_dict)
    except logic.NotFound:
        base.abort(404, _(u'User not found'))
    except logic.NotAuthorized:
        base.abort(403, _(u'Not authorized to see this page'))

    is_myself = user_dict[u'name'] == current_user.name
    about_formatted = h.render_markdown(user_dict[u'about'])
    extra: dict[str, Any] = {
        u'is_sysadmin': is_sysadmin,
        u'user_dict': user_dict,
        u'is_myself': is_myself,
        u'about_formatted': about_formatted
    }
    return extra


def index():
    page_number = h.get_page_number(request.args)
    q = request.args.get('q', '')
    order_by = request.args.get('order_by', 'name')
    default_limit: int = config.get('ckan.user_list_limit')
    limit = int(request.args.get('limit', default_limit))
    offset = page_number * limit - limit

    # get SQLAlchemy Query object from the action to avoid dictizing all
    # existing users at once
    context: Context = {
        u'return_query': True,
        u'user': current_user.name,
        u'auth_user_obj': current_user
    }

    data_dict = {
        'q': q,
        'order_by': order_by,
    }

    try:
        logic.check_access(u'user_list', context, data_dict)
    except logic.NotAuthorized:
        base.abort(403, _(u'Not authorized to see this page'))

    users_list = logic.get_action(u'user_list')(context, data_dict)

    # in template we don't need complex row objects from query. Let's dictize
    # subset of users that are shown on the current page
    users = [
        model_dictize.user_dictize(user[0], context)
        for user in
        users_list.limit(limit).offset(offset)
    ]

    page = Page(
        collection=users,
        page=page_number,
        presliced_list=True,
        url=h.pager_url,
        item_count=users_list.count(),
        items_per_page=limit)

    extra_vars: dict[str, Any] = {
        u'page': page, u'q': q, u'order_by': order_by}
    return base.render(u'user/list.html', extra_vars)


def me() -> Response:
    return h.redirect_to(
        config.get(u'ckan.auth.route_after_login'))


def read(id: str) -> Union[Response, str]:
    context: Context = {
        u'user': current_user.name,
        u'auth_user_obj': current_user,
        u'for_view': True
    }
    data_dict: dict[str, Any] = {
        u'id': id,
        u'user_obj': current_user,
        u'include_datasets': True,
        u'include_num_followers': True
    }
    # FIXME: line 331 in multilingual plugins expects facets to be defined.
    # any ideas?
    g.fields = []

    extra_vars = _extra_template_variables(context, data_dict)

    am_following: bool = False
    if not extra_vars['is_myself']:
        try:
            am_following = logic.get_action('am_following_user')(
                {'user': current_user.name}, {"id": id})
        except logic.NotAuthorized:
            am_following = False

    extra_vars["am_following"] = am_following
    return base.render(u'user/read.html', extra_vars)


def read_organizations(id: str) -> Union[Response, str]:
    context: Context = {
        u'user': current_user.name,
        u'auth_user_obj': current_user,
        u'for_view': True
    }
    data_dict: dict[str, Any] = {
        u'id': id,
        u'user_obj': current_user,
        u'include_datasets': False,
        u'include_num_followers': True
    }
    # FIXME: line 331 in multilingual plugins expects facets to be defined.
    # any ideas?
    g.fields = []

    extra_vars = _extra_template_variables(context, data_dict)
    return base.render(u'user/read_organizations.html', extra_vars)


def read_groups(id: str) -> Union[Response, str]:
    context: Context = {
        u'user': current_user.name,
        u'auth_user_obj': current_user,
        u'for_view': True
    }
    data_dict: dict[str, Any] = {
        u'id': id,
        u'user_obj': current_user,
        u'include_datasets': False,
        u'include_num_followers': True
    }
    # FIXME: line 331 in multilingual plugins expects facets to be defined.
    # any ideas?

    extra_vars = _extra_template_variables(context, data_dict)
    return base.render(u'user/read_groups.html', extra_vars)


class ApiTokenView(MethodView):
    def get(self, id: str) -> Union[Response, str]:
        try:
            tokens = logic.get_action('api_token_list')(
                {}, {'user': id}
            )
        except logic.NotAuthorized:
            base.abort(403, _('Unauthorized to view API tokens.'))

        data_dict: dict[str, Any] = {
            'id': id,
            'user_obj': current_user,
        }
        extra_vars = _extra_template_variables({}, data_dict)
        extra_vars['tokens'] = reversed(tokens)
        extra_vars['data'] = data_dict
        extra_vars['errors'] = None
        return base.render('user/api_tokens.html', extra_vars)

    def post(self, id: str) -> Union[Response, str]:
        data_dict = logic.clean_dict(
            dictization_functions.unflatten(
                logic.tuplize_dict(logic.parse_params(request.form))))

        data_dict['user'] = id
        token = None
        errors = None

        try:
            token = logic.get_action('api_token_create')({}, data_dict)
        except logic.NotAuthorized:
            base.abort(403, _('Unauthorized to create API tokens.'))
        except logic.ValidationError as e:
            errors = e.error_dict
        else:
            token['name'] = data_dict['name']
            data_dict = {}  # clear form

        data_dict: dict[str, Any] = {
            'id': id,
            'user_obj': current_user,
        }
        extra_vars = _extra_template_variables({}, data_dict)
        extra_vars.update({
            'user': extra_vars['user_dict'],  # renamed in user/read_base.html
            'data': data_dict,
            'created': token,
            'errors': errors,
        })
        return base.render('user/snippets/api_token_create_form.html', extra_vars)


def api_tokens_revoke(id: str) -> Union[Response, str]:
    tokens = request.form.getlist('token')
    for jti in tokens:
        try:
            logic.get_action('api_token_revoke')({}, {'jti': jti})
        except logic.NotAuthorized:
            base.abort(403, _('Unauthorized to revoke API tokens.'))
        except logic.NotFound:
            pass  # ignore already-deleted tokens
    return base.render('user/snippets/api_tokens_revoke.html', {
        'tokens': tokens
    })


class EditView(MethodView):
    def _prepare(self, id: Optional[str]) -> tuple[Context, str]:
        context: Context = {
            u'save': u'save' in request.form,
            u'schema': _edit_form_to_db_schema(),
            u'user': current_user.name,
            u'auth_user_obj': current_user
        }
        if id is None:
            if current_user.is_authenticated:
                id = current_user.id
            else:
                base.abort(400, _(u'No user specified'))
        assert id
        data_dict = {u'id': id}

        try:
            logic.check_access(u'user_update', context, data_dict)
        except logic.NotAuthorized:
            base.abort(403, _(u'Unauthorized to edit a user.'))
        return context, id

    def post(self, id: Optional[str] = None) -> Union[Response, str]:
        context, id = self._prepare(id)
        if not context[u'save']:
            return self.get(id)

        try:
            data_dict = logic.clean_dict(
                dictization_functions.unflatten(
                    logic.tuplize_dict(logic.parse_params(request.form))))
            data_dict.update(logic.clean_dict(
                dictization_functions.unflatten(
                    logic.tuplize_dict(logic.parse_params(request.files))))
            )

        except dictization_functions.DataError:
            base.abort(400, _(u'Integrity Error'))
        data_dict.setdefault(u'activity_streams_email_notifications', False)

        data_dict[u'id'] = id
        # deleted user can be reactivated by sysadmin on WEB-UI
        is_deleted = False
        if asbool(data_dict.get('activate_user', False)):
            user_dict = logic.get_action('user_show')(context, {'id': id})
            # set the flag so if validation error happens we will
            # change back the user state to deleted
            is_deleted = user_dict.get('state') == 'deleted'
            # if activate_user is checked, change the user's state to active
            data_dict['state'] = 'active'
            # pop the value as we don't want to send it for
            # validation on user_update
            data_dict.pop('activate_user')
        # we need this comparison when sysadmin edits a user,
        # this will return True
        # and we can utilize it for later use.
        email_changed = data_dict[u'email'] != current_user.email

        # common users can edit their own profiles without providing
        # password, but if they want to change
        # their old password with new one... old password must be provided..
        # so we are checking here if password1
        # and password2 are filled so we can enter the validation process.
        # when sysadmins edits a user he MUST provide sysadmin password.
        # We are recognizing sysadmin user
        # by email_changed variable.. this returns True
        # and we are entering the validation.
        password_changed = (
            data_dict.get('password1') and data_dict.get('password2')
        )
        if password_changed or email_changed:
            # getting the identity for current logged user
            identity = {
                u'login': current_user.name,
                u'password': data_dict[u'old_password'],
                u'check_captcha': False
            }
            auth_user = authenticator.ckan_authenticator(identity)

            # we are checking if the identity is not the
            # same with the current logged user if so raise error.
            auth_username = auth_user.name if auth_user else ''
            if auth_username != current_user.name:
                errors = {"oldpassword": [_("Password entered was incorrect")]}
                error_summary = (
                    {_("Old Password"): _("incorrect password")}
                    if not current_user.sysadmin  # type: ignore
                    else {_("Sysadmin Password"): _("incorrect password")}
                )
                return self.get(id, data_dict, errors, error_summary)

        try:
            user = logic.get_action(u'user_update')(context, data_dict)
        except logic.NotAuthorized:
            base.abort(403, _(u'Unauthorized to edit user %s') % id)
        except logic.NotFound:
            base.abort(404, _(u'User not found'))
        except logic.ValidationError as e:
            errors = e.error_dict
            error_summary = e.error_summary
            # the user state was deleted, we are trying to reactivate it but
            # validation error happens so we want to change back the state
            # to deleted, as it was before
            if is_deleted and data_dict.get('state') == 'active':
                data_dict['state'] = 'deleted'
            return self.get(id, data_dict, errors, error_summary)

        h.flash_success(_(u'Profile updated'))
        resp = h.redirect_to(u'user.read', id=user[u'name'])

        return resp

    def get(self,
            id: Optional[str] = None,
            data: Optional[dict[str, Any]] = None,
            errors: Optional[dict[str, Any]] = None,
            error_summary: Optional[dict[str, Any]] = None) -> str:
        context, id = self._prepare(id)
        data_dict = {u'id': id}
        try:

            old_data = logic.get_action(u'user_show')(context, data_dict)
            data = data or old_data

        except logic.NotAuthorized:
            base.abort(403, _(u'Unauthorized to edit user %s') % u'')
        except logic.NotFound:
            base.abort(404, _(u'User not found'))

        errors = errors or {}
        vars: dict[str, Any] = {
            u'data': data,
            u'errors': errors,
            u'error_summary': error_summary
        }

        extra_vars = _extra_template_variables({
            u'session': model.Session,
            u'user': current_user.name
        }, data_dict)

        vars.update(extra_vars)
        extra_vars[u'form'] = base.render(edit_user_form, extra_vars=vars)

        return base.render(u'user/edit.html', extra_vars)


class RegisterView(MethodView):
    def _prepare(self):
        context: Context = {
            u'user': current_user.name,
            u'auth_user_obj': current_user,
            u'schema': _new_form_to_db_schema(),
            u'save': u'save' in request.form
        }
        try:
            logic.check_access(u'user_create', context)
        except logic.NotAuthorized:
            base.abort(403, _(u'Unauthorized to register as a user.'))
        return context

    def post(self) -> Union[Response, str]:
        context = self._prepare()
        try:
            data_dict = logic.clean_dict(
                dictization_functions.unflatten(
                    logic.tuplize_dict(logic.parse_params(request.form))))
            data_dict.update(logic.clean_dict(
                dictization_functions.unflatten(
                    logic.tuplize_dict(logic.parse_params(request.files)))
            ))

        except dictization_functions.DataError:
            base.abort(400, _(u'Integrity Error'))

        try:
            captcha.check_recaptcha(request)
        except captcha.CaptchaError:
            error_msg = _(u'Bad Captcha. Please try again.')
            h.flash_error(error_msg)
            return self.get(data_dict)

        try:
            user_dict = logic.get_action(u'user_create')(context, data_dict)
        except logic.NotAuthorized:
            base.abort(403, _(u'Unauthorized to create user %s') % u'')
        except logic.NotFound:
            base.abort(404, _(u'User not found'))
        except logic.ValidationError as e:
            errors = e.error_dict
            error_summary = e.error_summary
            return self.get(data_dict, errors, error_summary)

        user = current_user.name
        if user:
            # #1799 User has managed to register whilst logged in - warn user
            # they are not re-logged in as new user.
            h.flash_success(
                _(u'User "%s" is now registered but you are still '
                  u'logged in as "%s" from before') % (data_dict[u'name'],
                                                       user))
            if authz.is_sysadmin(user):
                # the sysadmin created a new user. We redirect him to the
                # activity page for the newly created user
                if "activity" in g.plugins:
                    return h.redirect_to(
                        u'activity.user_activity', id=data_dict[u'name'])
                return h.redirect_to(u'user.read', id=data_dict[u'name'])
            else:
                return base.render(u'user/logout_first.html')

        # log the user in programatically
        userobj = model.User.get(user_dict["id"])
        if userobj:
            login_user(userobj)
            rotate_token()
        resp = h.redirect_to(u'user.me')
        return resp

    def get(self,
            data: Optional[dict[str, Any]] = None,
            errors: Optional[dict[str, Any]] = None,
            error_summary: Optional[dict[str, Any]] = None) -> str:
        self._prepare()
        user = current_user.name

        if user and not data and not authz.is_sysadmin(user):
            # #1799 Don't offer the registration form if already logged in
            return base.render(u'user/logout_first.html', {})

        form_vars = {
            u'data': data or {},
            u'errors': errors or {},
            u'error_summary': error_summary or {}
        }

        extra_vars: dict[str, Any] = {
            u'is_sysadmin': authz.is_sysadmin(user),
            u'form': base.render(new_user_form, form_vars)
        }
        return base.render(u'user/new.html', extra_vars)


def next_page_or_default(target: Optional[str]) -> Response:
    if target and h.url_is_local(target):
        return h.redirect_to(target)
    return me()


def rotate_token():
    """
    Change the CSRF token - should be done on login
    for security purposes.
    """
    from flask_wtf.csrf import generate_csrf

    field_name = config.get("WTF_CSRF_FIELD_NAME")
    if session.get(field_name):
        session.pop(field_name)
        generate_csrf()


def login() -> Union[Response, str]:
    for item in plugins.PluginImplementations(plugins.IAuthenticator):
        response = item.login()
        if response:
            return response

    extra_vars: dict[str, Any] = {}

    if current_user.is_authenticated:
        return base.render("user/logout_first.html", extra_vars)

    if request.method == "POST":
        username_or_email = request.form.get("login")
        password = request.form.get("password")
        _remember = request.form.get("remember")

        identity = {
            u"login": username_or_email,
            u"password": password
        }

        user_obj = authenticator.ckan_authenticator(identity)
        if user_obj:
            next = request.args.get('next', request.args.get('came_from'))
            if _remember:
                from datetime import timedelta
                duration_time = timedelta(milliseconds=int(_remember))
                login_user(user_obj, remember=True, duration=duration_time)
                rotate_token()
                return next_page_or_default(next)
            else:
                login_user(user_obj)
                rotate_token()
                return next_page_or_default(next)
        else:
            if config.get('ckan.recaptcha.privatekey'):
                err = _(u"Login failed. Bad username or password or CAPTCHA.")
            else:
                err = _(u"Login failed. Bad username or password.")
            h.flash_error(err)
            return base.render("user/login.html", extra_vars)

    return base.render("user/login.html", extra_vars)


def logout() -> Response:
    for item in plugins.PluginImplementations(plugins.IAuthenticator):
        response = item.logout()
        if response:
            return response
    user = current_user.name
    if not user:
        return h.redirect_to('user.login')

    came_from = request.args.get('came_from', '')
    logout_user()

    field_name = config.get("WTF_CSRF_FIELD_NAME")
    if session.get(field_name):
        session.pop(field_name)

    if h.url_is_local(came_from):
        return h.redirect_to(str(came_from))

    return h.redirect_to('user.logged_out_page')


def logged_out_page() -> str:
    return base.render(u'user/logout.html', {})


def delete(id: str) -> Union[Response, Any]:
    u'''Delete user with id passed as parameter'''
    context: Context = {
        u'user': current_user.name,
        u'auth_user_obj': current_user
    }
    data_dict = {u'id': id}

    if u'cancel' in request.form:
        return h.redirect_to(u'user.edit', id=id)

    try:
        if request.method == u'POST':
            logic.get_action(u'user_delete')(context, data_dict)
        user_dict = logic.get_action(u'user_show')(context, {u'id': id})
    except logic.NotAuthorized:
        msg = _(u'Unauthorized to delete user with id "{user_id}".')
        return base.abort(403, msg.format(user_id=id))
    except logic.NotFound as e:
        return base.abort(404, _(e.message))

    if request.method == 'POST' and current_user.is_authenticated:
        if current_user.id == id:
            return logout()
        else:
            user_index = h.url_for(u'user.index')
            return h.redirect_to(user_index)

    # TODO: Remove
    # ckan 2.9: Adding variables that were removed from c object for
    # compatibility with templates in existing extensions
    g.user_dict = user_dict
    g.user_id = id

    extra_vars = {
        u"user_id": id,
        u"user_dict": user_dict
    }
    return base.render(u'user/confirm_delete.html', extra_vars)


class RequestResetView(MethodView):
    def _prepare(self):
        context: Context = {
            u'user': current_user.name,
            u'auth_user_obj': current_user
        }
        try:
            logic.check_access(u'request_reset', context)
        except logic.NotAuthorized:
            base.abort(403, _(u'Unauthorized to request reset password.'))

    def post(self) -> Response:
        self._prepare()

        try:
            captcha.check_recaptcha(request)
        except captcha.CaptchaError:
            error_msg = _(u'Bad Captcha. Please try again.')
            h.flash_error(error_msg)
            return h.redirect_to(u'user.request_reset')

        id = request.form.get(u'user', '')
        if id in (None, u''):
            h.flash_error(_(u'Email is required'))
            return h.redirect_to(u'user.request_reset')
        log.info('Password reset requested for user %s', repr_untrusted(id))

        context: Context = {
            'user': current_user.name,
            'ignore_auth': True,
        }

        user_objs: list[model.User] = []

        # Usernames cannot contain '@' symbols
        if u'@' in id:
            # Search by email address
            # (You can forget a user id, but you don't tend to forget your
            # email)
            user_list = logic.get_action(u'user_list')(context, {
                u'email': id
            })
            if user_list:
                # send reset emails for *all* user accounts with this email
                # (otherwise we'd have to silently fail - we can't tell the
                # user, as that would reveal the existence of accounts with
                # this email address)
                for user_dict in user_list:
                    # This is ugly, but we need the user object for the mailer,
                    # and user_list does not return them
                    logic.get_action(u'user_show')(
                        context, {u'id': user_dict[u'id']})
                    user_objs.append(context[u'user_obj'])

        else:
            # Search by user name
            # (this is helpful as an option for a user who has multiple
            # accounts with the same email address and they want to be
            # specific)
            try:
                logic.get_action(u'user_show')(context, {u'id': id})
                user_objs.append(context[u'user_obj'])
            except logic.NotFound:
                pass

        if not user_objs:
            log.info('User requested reset link for unknown user: %s',
                     repr_untrusted(id))

        for user_obj in user_objs:
            log.info('Emailing reset link to user: %s', user_obj.name)
            try:
                # FIXME: How about passing user.id instead? Mailer already
                # uses model and it allow to simplify code above
                mailer.send_reset_link(user_obj)
                signals.request_password_reset.send(
                    user_obj.name, user=user_obj)
            except mailer.MailerException as e:
                # SMTP is not configured correctly or the server is
                # temporarily unavailable
                h.flash_error(_(u'Error sending the email. Try again later '
                                'or contact an administrator for help'))
                log.exception(e)
                return h.redirect_to(config.get(
                    u'ckan.user_reset_landing_page'))

        # always tell the user it succeeded, because otherwise we reveal
        # which accounts exist or not
        h.flash_success(
            _(u'A reset link has been emailed to you '
              '(unless the account specified does not exist)'))
        return h.redirect_to(config.get(
            u'ckan.user_reset_landing_page'))

    def get(self) -> str:
        self._prepare()
        return base.render(u'user/request_reset.html', {})


class PerformResetView(MethodView):
    def _prepare(self, id: str) -> tuple[Context, dict[str, Any]]:
        # FIXME 403 error for invalid key is a non helpful page
        context: Context = {
            'user': id,
            'schema': _perform_reset_form_to_db_schema(),
            'keep_email': True,
        }

        try:
            logic.check_access(u'user_reset', context)
        except logic.NotAuthorized:
            base.abort(403, _(u'Unauthorized to reset password.'))

        try:
            user_dict = logic.get_action(u'user_show')(context, {u'id': id})
        except logic.NotFound:
            base.abort(404, _(u'User not found'))
        user_obj = context[u'user_obj']
        g.reset_key = request.args.get(u'key')
        if not mailer.verify_reset_link(user_obj, g.reset_key):
            msg = _(u'Invalid reset key. Please try again.')
            h.flash_error(msg)
            base.abort(403, msg)
        return context, user_dict

    def post(self, id: str) -> Union[Response, str]:
        context, user_dict = self._prepare(id)
        context[u'reset_password'] = True
        user_state = user_dict[u'state']
        try:
            user_dict['password1'] = request.form.get('password1')
            user_dict['password2'] = request.form.get('password2')
            username = request.form.get(u'name')
            if (username is not None and username != u''):
                user_dict[u'name'] = username
            user_dict[u'reset_key'] = g.reset_key
            updated_user = logic.get_action("user_update")(context, user_dict)
            # Users can not change their own state, so we need another edit
            if (updated_user["state"] == model.State.PENDING):
                patch_context: Context = {
                    'user': logic.get_action("get_site_user")(
                        {"ignore_auth": True}, {})["name"]
                }
                logic.get_action("user_patch")(
                    patch_context,
                    {"id": user_dict['id'], "state": model.State.ACTIVE}
                )
            mailer.create_reset_key(context[u'user_obj'])
            signals.perform_password_reset.send(
                username, user=context[u'user_obj'])

            h.flash_success(_(u'Your password has been reset.'))
            return h.redirect_to(config.get(
                u'ckan.user_reset_landing_page'))

        except logic.NotAuthorized:
            h.flash_error(_(u'Unauthorized to edit user %s') % id)
        except logic.NotFound:
            h.flash_error(_(u'User not found'))
        except dictization_functions.DataError:
            h.flash_error(_(u'Integrity Error'))
        except logic.ValidationError as e:
            errors = e.error_dict
            error_summary = e.error_summary
            return self.get(id, errors, error_summary)
        except ValueError as e:
            h.flash_error(str(e))
        user_dict[u'state'] = user_state
        return base.render(u'user/perform_reset.html', {
            u'user_dict': user_dict
        })

    def get(self, id: str,
            errors: Optional[dict[str, Any]] = None,
            error_summary: Optional[dict[str, Any]] = None) -> str:
        user_dict = self._prepare(id)[1]
        return base.render(u'user/perform_reset.html', {
            u'user_dict': user_dict,
            'errors': errors or {},
            'error_summary': error_summary or {},
        })


def follow(id: str) -> str:
    '''Start following this user.'''
    error_message = ''
    am_following = False
    extra_vars = _extra_template_variables({}, {'id': id})

    try:
        logic.get_action('follow_user')({}, {'id': id})
        am_following = True
    except logic.ValidationError as e:
        error_message = e.error_dict['message']

    extra_vars.update({
        'am_following': am_following,
        'error_message': error_message,
        'dataset_type': h.default_package_type(),
        'group_type': h.default_group_type('group'),
        'org_type': h.default_group_type('organization'),
    })
    return base.render('user/snippets/info.html', extra_vars)


def unfollow(id: str) -> str:
    '''Stop following this user.'''
    error_message = ''
    am_following = True
    extra_vars = _extra_template_variables({}, {'id': id})

    try:
        logic.get_action('unfollow_user')({}, {'id': id})
        am_following = False
    except logic.ValidationError as e:
        error_message = e.error_summary

    extra_vars.update({
        'am_following': am_following,
        'error_message': error_message,
        'dataset_type': h.default_package_type(),
        'group_type': h.default_group_type('group'),
        'org_type': h.default_group_type('organization'),
    })

    return base.render('user/snippets/info.html', extra_vars)


def followers(id: str) -> str:
    context: Context = {
        u'for_view': True,
        u'user': current_user.name,
        u'auth_user_obj': current_user
    }
    data_dict: dict[str, Any] = {
        u'id': id,
        u'user_obj': current_user,
        u'include_num_followers': True
    }
    extra_vars = _extra_template_variables(context, data_dict)
    f = logic.get_action(u'user_follower_list')
    try:
        extra_vars[u'followers'] = f(context, {
            u'id': extra_vars[u'user_dict'][u'id']
        })
    except logic.NotAuthorized:
        base.abort(403, _(u'Unauthorized to view followers %s') % u'')
    return base.render(u'user/followers.html', extra_vars)


def sysadmin() -> Response:
    username = request.form.get(u'username')
    status = asbool(request.form.get(u'status'))

    try:
        context: Context = {
            u'user': current_user.name,
            u'auth_user_obj': current_user,
        }
        data_dict: dict[str, Any] = {u'id': username, u'sysadmin': status}
        user = logic.get_action(u'user_patch')(context, data_dict)
    except logic.NotAuthorized:
        return base.abort(
            403,
            _(u'Not authorized to promote user to sysadmin')
        )
    except logic.NotFound:
        h.flash_error(_(u'User not found'))
        return h.redirect_to(u'admin.index')
    except logic.ValidationError as e:
        h.flash_error((e.message or e.error_summary or e.error_dict))
        return h.redirect_to(u'admin.index')

    if status:
        h.flash_success(
            _(u'Promoted {} to sysadmin'.format(user[u'display_name']))
        )
    else:
        h.flash_success(
            _(
                u'Revoked sysadmin permission from {}'.format(
                    user[u'display_name']
                )
            )
        )
    return h.redirect_to(u'admin.index')


user.add_url_rule(u'/', view_func=index, strict_slashes=False)
user.add_url_rule(u'/me', view_func=me)

_edit_view: Any = EditView.as_view(str(u'edit'))
user.add_url_rule(u'/edit', view_func=_edit_view)
user.add_url_rule(u'/edit/<id>', view_func=_edit_view)

user.add_url_rule(
    u'/register', view_func=RegisterView.as_view(str(u'register')))

user.add_url_rule(u'/login', view_func=login, methods=('GET', 'POST'))
user.add_url_rule(u'/_logout', view_func=logout, methods=('GET', 'POST'))
user.add_url_rule(u'/logged_out_redirect', view_func=logged_out_page)

user.add_url_rule(u'/delete/<id>', view_func=delete, methods=(u'POST', 'GET'))

user.add_url_rule(
    u'/reset', view_func=RequestResetView.as_view(str(u'request_reset')))
user.add_url_rule(
    u'/reset/<id>', view_func=PerformResetView.as_view(str(u'perform_reset')))

user.add_url_rule(u'/follow/<id>', view_func=follow, methods=('POST', ))
user.add_url_rule(u'/unfollow/<id>', view_func=unfollow, methods=('POST', ))
user.add_url_rule(u'/followers/<id>', view_func=followers)

user.add_url_rule(u'/<id>', view_func=read)
user.add_url_rule(u'/<id>/organizations', view_func=read_organizations)
user.add_url_rule(u'/<id>/groups', view_func=read_groups)
user.add_url_rule(
    u'/<id>/api-tokens', view_func=ApiTokenView.as_view(str(u'api_tokens'))
)
user.add_url_rule(
    u'/<id>/api-tokens/revoke', view_func=api_tokens_revoke,
    methods=(u'POST',)
)
user.add_url_rule(rule=u'/sysadmin', view_func=sysadmin, methods=['POST'])
