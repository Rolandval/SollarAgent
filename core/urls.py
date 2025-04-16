# core/urls.py
from django.urls import path
from core.views import home, chat

urlpatterns = [
    path('', home),
    path('chat/', chat),
]
