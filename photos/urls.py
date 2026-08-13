from django.urls import path
from . import views

urlpatterns = [
    path("", views.photo_list, name="photo_list"),
    path("signup/", views.signup, name="signup"),
    path("upload/", views.upload, name="upload"),
    path("photos/<uuid:photo_id>/delete/", views.delete_photo, name="delete_photo"),
    path("internal/process-image/", views.worker, name="worker"),
]
