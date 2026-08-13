import json
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from .forms import PhotoUploadForm
from .models import Photo
from .tasks import enqueue_processing, process_pubsub_body

COLORS = [(value, label) for value, label in Photo.Color.choices]


def photo_list(request):
    # 未処理・失敗した画像を公開一覧に混ぜない。
    selected = request.GET.get("color", "")
    photos = Photo.objects.filter(status=Photo.Status.READY).select_related("owner")
    if selected in dict(COLORS):
        photos = photos.filter(color_tag=selected)
    return render(request, "photos/photo_list.html", {"photos": photos, "colors": COLORS, "selected": selected})


def signup(request):
    if request.method == "POST":
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect("photo_list")
    else:
        form = UserCreationForm()
    return render(request, "registration/signup.html", {"form": form})


@login_required
def upload(request):
    if request.method == "POST":
        form = PhotoUploadForm(request.POST, request.FILES)
        if form.is_valid():
            photo = Photo.objects.create(owner=request.user, original=form.cleaned_data["image"])
            try:
                enqueue_processing(photo)
                messages.success(request, "写真を受け付けました。処理後に公開されます。")
            except Exception:
                messages.error(request, "画像処理の受付に失敗しました。")
            return redirect("photo_list")
    else:
        form = PhotoUploadForm()
    return render(request, "photos/upload.html", {"form": form})


@login_required
@require_POST
def delete_photo(request, photo_id):
    # URL を直接指定されても、DB検索時点で投稿者本人だけに限定する。
    photo = get_object_or_404(Photo, pk=photo_id, owner=request.user)
    for field in (photo.original, photo.display, photo.thumbnail):
        if field:
            field.delete(save=False)
    photo.delete()
    messages.success(request, "写真を削除しました。")
    return redirect("photo_list")


@csrf_exempt
@require_POST
def worker(request):
    # このエンドポイントは非公開 Cloud Run Worker に対する Pub/Sub push 専用。
    try:
        process_pubsub_body(json.loads(request.body))
    except (KeyError, ValueError, UnicodeDecodeError) as error:
        return HttpResponseBadRequest(str(error))
    except Exception as error:
        return JsonResponse({"error": str(error)}, status=500)
    return JsonResponse({"status": "ok"})
