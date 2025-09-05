from django.contrib import admin, messages
from django.contrib.auth.admin import UserAdmin as DefaultUserAdmin
from django.contrib.auth.models import User
from django.utils.translation import gettext_lazy as _


# Custom admin actions for user management
@admin.action(description="Activate selected users")
def activate_users(modeladmin, request, queryset):
    """Admin action to activate selected users"""
    if not request.user.has_perm('auth.change_user'):
        messages.error(request, _("You don't have permission to modify users."))
        return

    updated_count = queryset.filter(is_active=False).update(is_active=True)
    if updated_count:
        messages.success(request, _(f"Successfully activated {updated_count} user(s)."))
    else:
        messages.info(request, _("No inactive users were selected."))


@admin.action(description="Deactivate selected users")
def deactivate_users(modeladmin, request, queryset):
    """Admin action to deactivate selected users"""
    if not request.user.has_perm('auth.change_user'):
        messages.error(request, _("You don't have permission to modify users."))
        return

    # Prevent users from deactivating themselves
    if request.user in queryset:
        messages.error(request, _("You cannot deactivate your own account."))
        return

    # Prevent deactivating superusers unless the current user is also a superuser
    if not request.user.is_superuser:
        superusers_in_selection = queryset.filter(is_superuser=True)
        if superusers_in_selection.exists():
            messages.error(request, _("You cannot deactivate superuser accounts."))
            return

    updated_count = queryset.filter(is_active=True).update(is_active=False)
    if updated_count:
        messages.success(request, _(f"Successfully deactivated {updated_count} user(s)."))
    else:
        messages.info(request, _("No active users were selected."))


@admin.action(description="Grant staff status to selected users")
def grant_staff_status(modeladmin, request, queryset):
    """Admin action to grant staff status to selected users"""
    if not request.user.has_perm('auth.change_user'):
        messages.error(request, _("You don't have permission to modify users."))
        return

    # Only superusers can grant staff status
    if not request.user.is_superuser:
        messages.error(request, _("Only superusers can grant staff status."))
        return

    updated_count = queryset.filter(is_staff=False).update(is_staff=True)
    if updated_count:
        messages.success(request, _(f"Successfully granted staff status to {updated_count} user(s)."))
    else:
        messages.info(request, _("No non-staff users were selected."))


@admin.action(description="Remove staff status from selected users")
def remove_staff_status(modeladmin, request, queryset):
    """Admin action to remove staff status from selected users"""
    if not request.user.has_perm('auth.change_user'):
        messages.error(request, _("You don't have permission to modify users."))
        return

    # Only superusers can remove staff status
    if not request.user.is_superuser:
        messages.error(request, _("Only superusers can remove staff status."))
        return

    # Prevent users from removing their own staff status
    if request.user in queryset:
        messages.error(request, _("You cannot remove your own staff status."))
        return

    # Prevent removing staff status from superusers (they need staff status)
    superusers_in_selection = queryset.filter(is_superuser=True)
    if superusers_in_selection.exists():
        messages.error(request, _("Cannot remove staff status from superusers."))
        return

    updated_count = queryset.filter(is_staff=True).update(is_staff=False)
    if updated_count:
        messages.success(request, _(f"Successfully removed staff status from {updated_count} user(s)."))
    else:
        messages.info(request, _("No staff users were selected."))


class CustomUserAdmin(DefaultUserAdmin):
    """Custom User admin with additional actions for managing user status"""

    # Add our custom actions
    actions = [
        activate_users,
        deactivate_users,
        grant_staff_status,
        remove_staff_status
    ]

    # Add status indicators to the list display
    list_display = DefaultUserAdmin.list_display + ('last_login',)

    def get_actions(self, request):
        """Only show actions to users with proper permissions"""
        actions = super().get_actions(request)

        # Remove actions if user doesn't have change_user permission
        if not request.user.has_perm('auth.change_user'):
            # Remove all our custom actions
            actions.pop('activate_users', None)
            actions.pop('deactivate_users', None)
            actions.pop('grant_staff_status', None)
            actions.pop('remove_staff_status', None)

        # Remove staff-related actions if user is not superuser
        if not request.user.is_superuser:
            actions.pop('grant_staff_status', None)
            actions.pop('remove_staff_status', None)

        return actions


# Unregister the default User admin and register our custom one
admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)
