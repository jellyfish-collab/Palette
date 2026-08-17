from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from photos.views import RateLimitedLoginView

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accounts/login/", RateLimitedLoginView.as_view(), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("", include("photos.urls")),
]
if settings.DEBUG and not settings.GCP_PROJECT_ID:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
