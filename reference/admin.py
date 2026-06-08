from django.contrib import admin

from .models import (
    Detachment,
    DetachmentCostProfile,
    Faction,
    GameSystemVersion,
    Keyword,
    SubFaction,
    UnitCatalog,
    UnitPointProfile,
)


@admin.register(GameSystemVersion)
class GameSystemVersionAdmin(admin.ModelAdmin):
    list_display = ("name", "code", "release_date", "is_active")
    list_filter = ("is_active",)
    search_fields = ("name", "code")
    prepopulated_fields = {"code": ("name",)}


class SubFactionInline(admin.TabularInline):
    model = SubFaction
    extra = 0
    prepopulated_fields = {"slug": ("name",)}


@admin.register(Faction)
class FactionAdmin(admin.ModelAdmin):
    list_display = ("name", "slug")
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}
    inlines = [SubFactionInline]


@admin.register(SubFaction)
class SubFactionAdmin(admin.ModelAdmin):
    list_display = ("name", "faction")
    list_filter = ("faction",)
    search_fields = ("name",)


@admin.register(Keyword)
class KeywordAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)
    prepopulated_fields = {"slug": ("name",)}


class UnitPointProfileInline(admin.TabularInline):
    model = UnitPointProfile
    extra = 0


@admin.register(UnitCatalog)
class UnitCatalogAdmin(admin.ModelAdmin):
    list_display = ("name", "faction", "unit_type", "game_system_version")
    list_filter = ("faction", "game_system_version")
    search_fields = ("name",)
    filter_horizontal = ("keywords",)
    inlines = [UnitPointProfileInline]


class DetachmentCostProfileInline(admin.TabularInline):
    model = DetachmentCostProfile
    extra = 0


@admin.register(Detachment)
class DetachmentAdmin(admin.ModelAdmin):
    list_display = ("name", "faction", "game_system_version")
    list_filter = ("faction", "game_system_version")
    search_fields = ("name",)
    inlines = [DetachmentCostProfileInline]


@admin.register(UnitPointProfile)
class UnitPointProfileAdmin(admin.ModelAdmin):
    list_display = ("unit", "model_count", "points", "game_system_version", "faq_update_date")
    list_filter = ("game_system_version",)
    search_fields = ("unit__name",)


@admin.register(DetachmentCostProfile)
class DetachmentCostProfileAdmin(admin.ModelAdmin):
    list_display = ("detachment", "points", "game_system_version", "faq_update_date")
    list_filter = ("game_system_version",)
    search_fields = ("detachment__name",)
