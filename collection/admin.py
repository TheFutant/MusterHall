from django.contrib import admin

from .models import CollectionEntry, SourceProduct, Tag


@admin.register(SourceProduct)
class SourceProductAdmin(admin.ModelAdmin):
    list_display = ("name", "owner")
    list_filter = ("owner",)
    search_fields = ("name",)


@admin.register(Tag)
class TagAdmin(admin.ModelAdmin):
    list_display = ("name", "owner")
    list_filter = ("owner",)
    search_fields = ("name",)


@admin.register(CollectionEntry)
class CollectionEntryAdmin(admin.ModelAdmin):
    list_display = (
        "name", "owner", "faction", "subfaction", "quantity",
        "assembly_state", "paint_state", "ready_for_game", "updated",
    )
    list_filter = (
        "owner", "faction", "subfaction", "assembly_state",
        "paint_state", "ready_for_game", "backlog_priority", "tags",
    )
    search_fields = ("name", "notes", "paint_scheme", "storage_location")
    autocomplete_fields = ("faction", "subfaction", "source_product")
    filter_horizontal = ("tags",)
    raw_id_fields = ("owner",)
    date_hierarchy = "created"
    list_select_related = ("owner", "faction", "subfaction")
