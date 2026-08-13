from django.contrib import admin
from .models import Photo

@admin.register(Photo)
class PhotoAdmin(admin.ModelAdmin):
    list_display = ("id", "owner", "color_tag", "status", "created_at")
    list_filter = ("color_tag", "status")
    search_fields = ("owner__username",)
