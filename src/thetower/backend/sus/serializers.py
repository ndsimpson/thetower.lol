from rest_framework import serializers


class BanPlayerSerializer(serializers.Serializer):
    player_id = serializers.CharField(max_length=32)
    action = serializers.ChoiceField(choices=[("ban", "Ban"), ("sus", "Sus")])
    note = serializers.CharField(max_length=500, required=False, allow_blank=True)
