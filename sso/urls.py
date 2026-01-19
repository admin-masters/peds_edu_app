from django.urls import path
from . import views

urlpatterns = [
    path("consume/", views.consume, name="sso_consume"),
]
