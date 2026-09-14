from django.urls import path

from apps.accounts.views import FirebaseLoginView, LogoutView, MeView, TokenRefreshView

urlpatterns = [
    path("login/", FirebaseLoginView.as_view(), name="firebase-login"),
    path("token/refresh/", TokenRefreshView.as_view(), name="token-refresh"),
    path("logout/", LogoutView.as_view(), name="logout"),
    path("me/", MeView.as_view(), name="me"),
]
