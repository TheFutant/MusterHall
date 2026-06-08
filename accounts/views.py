from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login
from django.http import Http404
from django.shortcuts import redirect, render

from .forms import SignUpForm


def signup(request):
    """Self-service registration, gated by the REGISTRATION_OPEN setting."""
    if not settings.REGISTRATION_OPEN:
        raise Http404("Registration is closed on this instance.")

    if request.user.is_authenticated:
        return redirect("collection:dashboard")

    if request.method == "POST":
        form = SignUpForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            messages.success(request, "Welcome to MusterHall! Your account is ready.")
            return redirect("collection:dashboard")
    else:
        form = SignUpForm()

    return render(request, "registration/signup.html", {"form": form})
