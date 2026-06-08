from django.urls import path

from . import views

app_name = "collection"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("collection/", views.CollectionListView.as_view(), name="list"),
    path("collection/add/", views.CollectionCreateView.as_view(), name="create"),
    path("collection/export.csv", views.export_csv, name="export"),
    path("collection/<int:pk>/", views.CollectionDetailView.as_view(), name="detail"),
    path("collection/<int:pk>/edit/", views.CollectionUpdateView.as_view(), name="update"),
    path("collection/<int:pk>/delete/", views.CollectionDeleteView.as_view(), name="delete"),
]
