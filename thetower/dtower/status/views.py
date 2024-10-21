#  from django.shortcuts import render
from django.http import HttpResponse


def index(request):
    return HttpResponse("Hello, world. You're at the services index.")


def services(request, service_name):
    return HttpResponse("You're looking service %s." % service_name)
    #  return HttpResponse("Hello, world. You're at the bot index.")