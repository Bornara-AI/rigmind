from django.contrib import admin
from django.http import HttpRequest

from apps.production.models import (
    Facility,
    FacilityActivityMonthly,
    Operator,
    PetrinexLoad,
    ProductionMonthly,
    Well,
)


class ReadOnlyAdmin(admin.ModelAdmin):
    """Loaded data is changed only by load_petrinex, never by hand."""

    def has_add_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False

    def has_change_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False

    def has_delete_permission(self, request: HttpRequest, obj: object = None) -> bool:
        return False


@admin.register(Operator)
class OperatorAdmin(ReadOnlyAdmin):
    list_display = ("baid", "name", "last_seen_month")
    search_fields = ("baid", "name")


@admin.register(Facility)
class FacilityAdmin(ReadOnlyAdmin):
    list_display = ("facility_id", "name", "facility_type", "subtype", "operator")
    list_filter = ("facility_type",)
    search_fields = ("facility_id", "name")


@admin.register(Well)
class WellAdmin(ReadOnlyAdmin):
    list_display = ("uwi", "well_name", "licensee_name", "field_name", "status_fluid")
    list_filter = ("status_fluid", "drill_direction", "is_orphan")
    search_fields = ("well_id", "uwi", "well_name", "licence_number")


@admin.register(ProductionMonthly)
class ProductionMonthlyAdmin(ReadOnlyAdmin):
    list_display = ("well_id", "month", "product", "volume", "hours", "is_masked")
    list_filter = ("month", "product", "is_masked")
    search_fields = ("well_id",)


@admin.register(FacilityActivityMonthly)
class FacilityActivityMonthlyAdmin(ReadOnlyAdmin):
    list_display = ("facility", "month", "activity", "product", "volume", "from_to_id")
    list_filter = ("month", "activity", "product")
    search_fields = ("facility__facility_id", "from_to_id")


@admin.register(PetrinexLoad)
class PetrinexLoadAdmin(ReadOnlyAdmin):
    list_display = (
        "source_file",
        "month",
        "rows_staged",
        "production_rows",
        "activity_rows",
        "loaded_at",
    )
