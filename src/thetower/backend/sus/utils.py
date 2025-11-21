# Utility functions for the SUS (Suspicious Users System) app

from django.contrib.auth import get_user_model

User = get_user_model()


def is_known_user(user):
    """
    Check if a Django user is linked to a KnownPlayer record.

    Args:
        user: Django User instance

    Returns:
        bool: True if the user has a linked KnownPlayer, False otherwise
    """
    if not user or not user.is_authenticated:
        return False

    return hasattr(user, 'known_player') and user.known_player is not None


def get_known_player_for_user(user):
    """
    Get the KnownPlayer record for a Django user.

    Args:
        user: Django User instance

    Returns:
        KnownPlayer or None: The linked KnownPlayer if it exists, None otherwise
    """
    if not user or not user.is_authenticated:
        return None

    try:
        return user.known_player
    except AttributeError:
        return None


def link_user_to_known_player(user, known_player):
    """
    Link a Django user to a KnownPlayer record.

    Args:
        user: Django User instance
        known_player: KnownPlayer instance

    Returns:
        bool: True if linking was successful, False if already linked or invalid

    Raises:
        ValueError: If the KnownPlayer is already linked to another user
    """
    if not user or not known_player:
        return False

    # Check if KnownPlayer is already linked
    if known_player.django_user:
        if known_player.django_user == user:
            return True  # Already linked to this user
        else:
            raise ValueError(f"KnownPlayer {known_player} is already linked to user {known_player.django_user}")

    # Check if user is already linked to a KnownPlayer
    if hasattr(user, 'known_player') and user.known_player:
        raise ValueError(f"User {user} is already linked to KnownPlayer {user.known_player}")

    # Link them
    known_player.django_user = user
    known_player.save()
    return True


def unlink_user_from_known_player(user):
    """
    Unlink a Django user from their KnownPlayer record.

    Args:
        user: Django User instance

    Returns:
        bool: True if unlinking was successful, False if not linked
    """
    if not user or not hasattr(user, 'known_player') or not user.known_player:
        return False

    known_player = user.known_player
    known_player.django_user = None
    known_player.save()
    return True
