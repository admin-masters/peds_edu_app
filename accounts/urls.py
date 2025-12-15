from django.urls import path

from . import views

app_name = "accounts"

urlpatterns = [
    path("register/", views.register_doctor, name="register"),
    path("login/", views.doctor_login, name="login"),
    path("logout/", views.doctor_logout, name="logout"),
    path("forgot/", views.request_password_reset, name="forgot"),
    path("reset/<uidb64>/<token>/", views.password_reset, name="password_reset"),
]
