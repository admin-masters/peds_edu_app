from __future__ import annotations

from django.contrib import messages
from django.contrib.admin.views.decorators import staff_member_required
from django.db.models import Prefetch
from django.shortcuts import get_object_or_404, redirect, render

from catalog.constants import LANGUAGE_CODES
from catalog.models import Video, VideoLanguage, VideoCluster, VideoClusterLanguage, VideoClusterVideo, VideoTriggerMap

from .forms import (
    VideoForm, make_video_language_formset,
    VideoClusterForm, make_cluster_language_formset, make_cluster_video_formset,
    VideoTriggerMapForm
)


@staff_member_required
def dashboard(request):
    return render(request, "publisher/dashboard.html")


@staff_member_required
def video_list(request):
    q = (request.GET.get("q") or "").strip()
    qs = Video.objects.prefetch_related("langs").all().order_by("code")
    if q:
        qs = qs.filter(code__icontains=q) | qs.filter(search_keywords__icontains=q)

    rows = []
    for v in qs:
        en = next((l.title for l in v.langs.all() if l.language_code == "en"), "")
        rows.append({"obj": v, "title": en})

    return render(request, "publisher/video_list.html", {"rows": rows, "q": q})


@staff_member_required
def video_create(request):
    FormSet = make_video_language_formset(extra=len(LANGUAGE_CODES))
    video = Video()

    if request.method == "POST":
        form = VideoForm(request.POST, instance=video)
        formset = FormSet(request.POST, instance=video)
        if form.is_valid() and formset.is_valid():
            v = form.save()
            formset.instance = v
            formset.save()
            messages.success(request, "Video created.")
            return redirect("publisher:video_edit", pk=v.pk)
    else:
        form = VideoForm(instance=video)
        initial = [{"language_code": c} for c in LANGUAGE_CODES]
        formset = FormSet(instance=video, initial=initial)

    return render(request, "publisher/video_form.html", {"form": form, "formset": formset, "is_new": True})


@staff_member_required
def video_edit(request, pk: int):
    video = get_object_or_404(Video.objects.prefetch_related("langs"), pk=pk)

    existing = {l.language_code for l in video.langs.all()}
    missing = [c for c in LANGUAGE_CODES if c not in existing]

    FormSet = make_video_language_formset(extra=len(missing))
    if request.method == "POST":
        form = VideoForm(request.POST, instance=video)
        formset = FormSet(request.POST, instance=video, initial=[{"language_code": c} for c in missing])
        if form.is_valid() and formset.is_valid():
            form.save()
            formset.save()
            messages.success(request, "Video saved.")
            return redirect("publisher:video_edit", pk=video.pk)
    else:
        form = VideoForm(instance=video)
        formset = FormSet(instance=video, initial=[{"language_code": c} for c in missing])

    return render(request, "publisher/video_form.html", {"form": form, "formset": formset, "is_new": False, "video": video})


@staff_member_required
def cluster_list(request):
    q = (request.GET.get("q") or "").strip()
    qs = VideoCluster.objects.prefetch_related("langs").select_related("trigger").all().order_by("sort_order", "code")
    if q:
        qs = qs.filter(code__icontains=q) | qs.filter(search_keywords__icontains=q)

    rows = []
    for c in qs:
        en = next((l.name for l in c.langs.all() if l.language_code == "en"), "")
        rows.append({"obj": c, "name": en, "trigger": c.trigger})

    return render(request, "publisher/cluster_list.html", {"rows": rows, "q": q})


@staff_member_required
def cluster_create(request):
    LangFS = make_cluster_language_formset(extra=len(LANGUAGE_CODES))
    VidFS = make_cluster_video_formset(extra=5)
    cluster = VideoCluster()

    if request.method == "POST":
        form = VideoClusterForm(request.POST, instance=cluster)
        lang_fs = LangFS(request.POST, instance=cluster)
        vid_fs = VidFS(request.POST, instance=cluster)
        if form.is_valid() and lang_fs.is_valid() and vid_fs.is_valid():
            c = form.save()
            lang_fs.instance = c
            vid_fs.instance = c
            lang_fs.save()
            vid_fs.save()
            messages.success(request, "Bundle created.")
            return redirect("publisher:cluster_edit", pk=c.pk)
    else:
        form = VideoClusterForm(instance=cluster)
        lang_fs = LangFS(instance=cluster, initial=[{"language_code": c} for c in LANGUAGE_CODES])
        vid_fs = VidFS(instance=cluster)

    return render(request, "publisher/cluster_form.html", {"form": form, "lang_fs": lang_fs, "vid_fs": vid_fs, "is_new": True})


@staff_member_required
def cluster_edit(request, pk: int):
    cluster = get_object_or_404(
        VideoCluster.objects.select_related("trigger").prefetch_related("langs", "cluster_videos"),
        pk=pk,
    )

    existing = {l.language_code for l in cluster.langs.all()}
    missing = [c for c in LANGUAGE_CODES if c not in existing]

    LangFS = make_cluster_language_formset(extra=len(missing))
    VidFS = make_cluster_video_formset(extra=3)

    if request.method == "POST":
        form = VideoClusterForm(request.POST, instance=cluster)
        lang_fs = LangFS(request.POST, instance=cluster, initial=[{"language_code": c} for c in missing])
        vid_fs = VidFS(request.POST, instance=cluster)
        if form.is_valid() and lang_fs.is_valid() and vid_fs.is_valid():
            form.save()
            lang_fs.save()
            vid_fs.save()
            messages.success(request, "Bundle saved.")
            return redirect("publisher:cluster_edit", pk=cluster.pk)
    else:
        form = VideoClusterForm(instance=cluster)
        lang_fs = LangFS(instance=cluster, initial=[{"language_code": c} for c in missing])
        vid_fs = VidFS(instance=cluster)

    return render(request, "publisher/cluster_form.html", {"form": form, "lang_fs": lang_fs, "vid_fs": vid_fs, "is_new": False, "cluster": cluster})


@staff_member_required
def map_list(request):
    q = (request.GET.get("q") or "").strip()
    qs = VideoTriggerMap.objects.select_related("trigger", "video").all().order_by("trigger__code", "sort_order")
    if q:
        qs = qs.filter(trigger__code__icontains=q) | qs.filter(video__code__icontains=q)
    return render(request, "publisher/map_list.html", {"rows": qs, "q": q})


@staff_member_required
def map_create(request):
    if request.method == "POST":
        form = VideoTriggerMapForm(request.POST)
        if form.is_valid():
            m = form.save()
            messages.success(request, "Trigger map created.")
            return redirect("publisher:map_edit", pk=m.pk)
    else:
        form = VideoTriggerMapForm()
    return render(request, "publisher/map_form.html", {"form": form, "is_new": True})


@staff_member_required
def map_edit(request, pk: int):
    obj = get_object_or_404(VideoTriggerMap, pk=pk)
    if request.method == "POST":
        form = VideoTriggerMapForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Trigger map saved.")
            return redirect("publisher:map_edit", pk=obj.pk)
    else:
        form = VideoTriggerMapForm(instance=obj)
    return render(request, "publisher/map_form.html", {"form": form, "is_new": False, "obj": obj})
