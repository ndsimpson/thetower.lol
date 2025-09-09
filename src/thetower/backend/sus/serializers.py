from rest_framework import serializers


class BanPlayerSerializer(serializers.Serializer):
    player_id = serializers.CharField(max_length=32)
    action = serializers.ChoiceField(choices=[("ban", "Ban"), ("unban", "Unban"), ("sus", "Sus"), ("unsus", "Unsus")])
    note = serializers.CharField(max_length=500, required=False, allow_blank=True)
