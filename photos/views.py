import json
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.http import HttpResponseBadRequest, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST
from .forms import PhotoUploadForm
from .models import Photo
from .rate_limits import clear, client_ip, consume, is_limited
from .tasks import enqueue_processing, process_pubsub_body

COLORS = [(value, label) for value, label in Photo.Color.choices]


def _rate_limit_message(retry_after):
    minutes = max(1, (retry_after + 59) // 60)
    return f"試行回数が多すぎます。約{minutes}分後にもう一度お試しください。"


class RateLimitedLoginView(LoginView):
    """失敗ログインをアカウント名ごとに制限し、成功時には失敗履歴を消す。"""

    template_name = "registration/login.html"

    def dispatch(self, request, *args, **kwargs):
        self.login_identifier = request.POST.get("username", "").strip()
        if request.method == "POST" and self.login_identifier:
            limited, retry_after = is_limited(
                "login-account",
                self.login_identifier,
                settings.RATE_LIMIT_LOGIN_ATTEMPTS,
                settings.RATE_LIMIT_LOGIN_WINDOW_SECONDS,
            )
            if limited:
                form = self.get_form()
                messages.error(request, _rate_limit_message(retry_after))
                return self.render_to_response(self.get_context_data(form=form), status=429)
        return super().dispatch(request, *args, **kwargs)

    def form_invalid(self, form):
        # パスワード不一致のときだけ試行を数え、存在しないユーザー名も同じ扱いにする。
        if self.login_identifier:
            consume(
                "login-account",
                self.login_identifier,
                settings.RATE_LIMIT_LOGIN_ATTEMPTS,
                settings.RATE_LIMIT_LOGIN_WINDOW_SECONDS,
            )
        return super().form_invalid(form)

    def form_valid(self, form):
        if self.login_identifier:
            clear("login-account", self.login_identifier)
        return super().form_valid(form)


def photo_list(request):
    # 未処理・失敗した画像を公開一覧に混ぜない。
    selected = request.GET.get("color", "")
    photos = Photo.objects.filter(status=Photo.Status.READY).select_related("owner")
    if selected in dict(COLORS):
        photos = photos.filter(color_tag=selected)
    return render(request, "photos/photo_list.html", {"photos": photos, "colors": COLORS, "selected": selected})


def signup(request):
    if request.method == "POST":
        allowed, retry_after = consume(
            "signup-ip",
            client_ip(request),
            settings.RATE_LIMIT_SIGNUP_ATTEMPTS,
            settings.RATE_LIMIT_SIGNUP_WINDOW_SECONDS,
        )
        if not allowed:
            form = UserCreationForm(request.POST)
            messages.error(request, _rate_limit_message(retry_after))
            return render(request, "registration/signup.html", {"form": form}, status=429)
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
        # 画像を開く前に上限到達済みかを確認し、無駄な画像変換コストを避ける。
        limited, retry_after = is_limited(
            "upload-account",
            str(request.user.pk),
            settings.RATE_LIMIT_UPLOAD_ATTEMPTS,
            settings.RATE_LIMIT_UPLOAD_WINDOW_SECONDS,
        )
        if limited:
            form = PhotoUploadForm()
            messages.error(request, _rate_limit_message(retry_after))
            return render(request, "photos/upload.html", {"form": form}, status=429)
        form = PhotoUploadForm(request.POST, request.FILES)
        if form.is_valid():
            allowed, retry_after = consume(
                "upload-account",
                str(request.user.pk),
                settings.RATE_LIMIT_UPLOAD_ATTEMPTS,
                settings.RATE_LIMIT_UPLOAD_WINDOW_SECONDS,
            )
            if not allowed:
                messages.error(request, _rate_limit_message(retry_after))
                return render(request, "photos/upload.html", {"form": form}, status=429)
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
