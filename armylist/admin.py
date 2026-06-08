from django.contrib import admin

from .models import ArmyList, ArmyListEntry


class ArmyListEntryInline(admin.TabularInline):
    model = ArmyListEntry
    extra = 0
    raw_id_fields = ("collection_entry", "unit_catalog")


@admin.register(ArmyList)
class ArmyListAdmin(admin.ModelAdmin):
    list_display = ("name", "owner", "game_system_version", "detachment", "points_limit", "is_experimental")
    list_filter = ("is_experimental", "game_system_version")
    search_fields = ("name",)
    raw_id_fields = ("owner",)
    inlines = [ArmyListEntryInline]


@admin.register(ArmyListEntry)
class ArmyListEntryAdmin(admin.ModelAdmin):
    list_display = ("name", "army_list", "quantity", "points")
    search_fields = ("name",)
    raw_id_fields = ("army_list", "collection_entry", "unit_catalog")
