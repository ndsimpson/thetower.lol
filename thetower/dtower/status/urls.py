from django.urls import path

from .views import services, index

urlpatterns = [
    # ex: /status/
    path("", index, name="index"),
    # ex: /status/service_name1/
    path("<str:services>/", services, name="services"),
]