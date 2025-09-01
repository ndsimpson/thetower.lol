import os
from datetime import datetime, timezone

from django.conf import settings
from rest_framework import permissions, status
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import ApiKey, SusPerson
from .serializers import BanPlayerSerializer


class APIKeyPermission(permissions.BasePermission):
    """Custom permission to check for a valid API key in the header and user permissions."""

    def has_permission(self, request, view):
        api_key = request.headers.get("X-API-KEY")
        if not api_key:
            return False
        try:
            key_obj = ApiKey.objects.get(key=api_key, active=True)
        except ApiKey.DoesNotExist:
            return False
        # Update last_used_at
        key_obj.last_used_at = datetime.now(timezone.utc)
        key_obj.save(update_fields=["last_used_at"])
        user = key_obj.user
        # Check user permission for changing SusPerson
        if not user.has_perm("sus.change_susperson"):
            return False
        request.api_key_user = user
        request.api_key_obj = key_obj
        return True


def log_api_request(api_key_user, player_id, action, success, note=None):
    data_dir = getattr(settings, "DATA_DIR", None) or os.environ.get("DATA_DIR", ".")
    log_path = os.path.join(str(data_dir), "api_requests.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "a", encoding="utf-8") as f:
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        status_str = "SUCCESS" if success else "FAIL"
        note_str = note.replace("\n", " ") if note else ""
        f.write(f"{ts}\t{api_key_user}\t{player_id}\t{action}\t{status_str}\t{note_str}\n")


class BanPlayerAPI(APIView):
    permission_classes = [APIKeyPermission]

    def post(self, request):
        serializer = BanPlayerSerializer(data=request.data)
        if not serializer.is_valid():
            log_api_request(
                getattr(request, "api_key_user", "UNKNOWN"),
                request.data.get("player_id", ""),
                request.data.get("action", ""),
                False,
                note="Invalid data",
            )
            return Response({"detail": "Invalid data", "errors": serializer.errors}, status=status.HTTP_400_BAD_REQUEST)

        # Check permission again for extra safety (DRF best practice)
        user = getattr(request, "api_key_user", None)
        if not user or not user.has_perm("sus.change_susperson"):
            log_api_request(user or "UNKNOWN", request.data.get("player_id", ""), request.data.get("action", ""), False, note="Permission denied")
            return Response({"detail": "Permission denied."}, status=status.HTTP_403_FORBIDDEN)

        player_id = serializer.validated_data["player_id"]
        action = serializer.validated_data["action"]
        note = serializer.validated_data.get("note", "")
        api_key_user = getattr(request, "api_key_user", None)
        api_key_obj = getattr(request, "api_key_obj", None)

        try:
            sus_person, created = SusPerson.objects.get_or_create(player_id=player_id)
            # Use SusPerson methods which enforce provenance rules and append structured notes
            if action == "ban":
                sus_person.mark_banned_by_api(api_key_user, api_key_obj=api_key_obj, note=note)
            elif action == "sus":
                sus_person.mark_sus_by_api(api_key_user, api_key_obj=api_key_obj, note=note)
            elif action == "unban":
                sus_person.unban_by_api(api_key_user, api_key_obj=api_key_obj, note=note)
            elif action == "unsus":
                sus_person.unsus_by_api(api_key_user, api_key_obj=api_key_obj, note=note)
            else:
                log_api_request(api_key_user, player_id, action, False, note="Unknown action")
                return Response({"detail": "Unknown action."}, status=status.HTTP_400_BAD_REQUEST)
            log_api_request(api_key_user, player_id, action, True, note=note)
            return Response({"detail": f"Player {player_id} marked as {action}."}, status=status.HTTP_200_OK)
        except Exception as e:
            log_api_request(api_key_user, player_id, action, False, note=str(e))
            return Response({"detail": "Internal server error."}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)
