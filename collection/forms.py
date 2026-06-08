from django import forms

from reference.models import Faction, SubFaction

from .models import BacklogPriority, CollectionEntry, SourceProduct, Tag


class CollectionEntryForm(forms.ModelForm):
    """Fast-entry form.

    Source product and tags are typed as free text (autocompleted from the
    user's existing values) and get-or-created on save, so adding a unit feels
    lighter than a spreadsheet. Owner is forced server-side, never rendered.
    """

    source_text = forms.CharField(
        label="Source product / box",
        required=False,
        widget=forms.TextInput(attrs={"list": "source-options", "autocomplete": "off"}),
    )
    tags_text = forms.CharField(
        label="Tags",
        required=False,
        help_text="Comma-separated, e.g. WIP, magnetised",
        widget=forms.TextInput(attrs={"list": "tag-options", "autocomplete": "off"}),
    )

    class Meta:
        model = CollectionEntry
        fields = [
            "name",
            "faction",
            "subfaction",
            "quantity",
            "assembly_state",
            "paint_state",
            "paint_scheme",
            "storage_location",
            "ready_for_game",
            "backlog_priority",
            "photo",
            "notes",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
            "storage_location": forms.TextInput(attrs={"list": "storage-options", "autocomplete": "off"}),
            "paint_scheme": forms.TextInput(attrs={"autocomplete": "off"}),
        }

    def __init__(self, *args, owner=None, **kwargs):
        self.owner = owner
        super().__init__(*args, **kwargs)

        self.fields["faction"].queryset = Faction.objects.all()
        self.fields["faction"].empty_label = "— Faction —"
        self.fields["subfaction"].queryset = SubFaction.objects.select_related("faction")
        self.fields["subfaction"].empty_label = "— Chapter / subfaction —"
        self.fields["backlog_priority"].choices = [("", "— No priority —")] + list(BacklogPriority.choices)

        if self.instance and self.instance.pk:
            if self.instance.source_product_id:
                self.fields["source_text"].initial = self.instance.source_product.name
            self.fields["tags_text"].initial = ", ".join(
                self.instance.tags.values_list("name", flat=True)
            )

    def _resolve_source(self):
        name = (self.cleaned_data.get("source_text") or "").strip()
        if not name:
            return None
        source, _ = SourceProduct.objects.get_or_create(owner=self.owner, name=name)
        return source

    def _apply_tags(self, entry):
        raw = self.cleaned_data.get("tags_text") or ""
        names, seen = [], set()
        for chunk in raw.split(","):
            name = chunk.strip()
            if name and name.lower() not in seen:
                seen.add(name.lower())
                names.append(name)
        tags = [Tag.objects.get_or_create(owner=self.owner, name=name)[0] for name in names]
        entry.tags.set(tags)

    def save(self, commit=True):
        entry = super().save(commit=False)
        entry.owner = self.owner
        entry.source_product = self._resolve_source()
        if commit:
            entry.save()
            self._apply_tags(entry)
        return entry
