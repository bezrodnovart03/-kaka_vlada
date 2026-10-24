"""
URL configuration for config project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.0/topics/http/urls/
"""

from django.contrib import admin
from django.urls import path

from apps.core.logs import logs_view

from .api import api

urlpatterns = [
    # До admin.site.urls: иначе /admin/logs/ поймает catch-all админки.
    path("admin/logs/", admin.site.admin_view(logs_view), name="admin_logs"),
    path("admin/", admin.site.urls),
    path("api/v1/", api.urls),
]
