"""Production data loaded from Petrinex public volumetrics (see docs/DATA_PLAN.md).

IDs are kept as text exactly as Petrinex publishes them. Units: liquids m3,
gas e3m3 (thousand m3), energy GJ. Months are stored as the first day of the month.
"""

from django.contrib.postgres.fields import ArrayField
from django.db import models

VOLUME = {"max_digits": 16, "decimal_places": 4}


class Operator(models.Model):
    """Business associate that operates a reporting facility."""

    baid = models.CharField(primary_key=True, max_length=10)
    name = models.CharField(max_length=200)
    last_seen_month = models.DateField()

    class Meta:
        db_table = "operators"
        ordering = ["name"]

    def __str__(self) -> str:
        return f"{self.name} ({self.baid})"


class Facility(models.Model):
    """Reporting facility (battery, gas plant, ...), e.g. ABBT0051211."""

    facility_id = models.CharField(primary_key=True, max_length=20)
    name = models.CharField(max_length=200)
    facility_type = models.CharField(max_length=4)
    subtype = models.CharField(max_length=10)
    operator = models.ForeignKey(
        Operator,
        on_delete=models.PROTECT,
        db_column="operator_baid",
        related_name="facilities",
    )
    last_seen_month = models.DateField()

    class Meta:
        db_table = "facilities"
        ordering = ["facility_id"]
        verbose_name_plural = "facilities"

    def __str__(self) -> str:
        return f"{self.facility_id} {self.name}"


class ProductionMonthly(models.Model):
    """One row per well x month x product (OIL, GAS, WATER, COND, ...).

    A well reported at two facilities in the same month is summed into one row;
    facility_ids keeps both.
    """

    well_id = models.CharField(max_length=20)  # e.g. ABWI100010206504W400
    month = models.DateField()
    product = models.CharField(max_length=10)
    volume = models.DecimalField(null=True, **VOLUME)
    hours = models.IntegerField(null=True)
    facility_ids = ArrayField(models.CharField(max_length=20))
    is_masked = models.BooleanField(default=False)
    submission_date = models.DateField(null=True)
    source_file = models.CharField(max_length=100)

    class Meta:
        db_table = "production_monthly"
        constraints = [
            models.UniqueConstraint(
                fields=["well_id", "month", "product"],
                name="uniq_production_well_month_product",
            )
        ]
        indexes = [models.Index(fields=["month", "product"])]

    def __str__(self) -> str:
        return f"{self.well_id} {self.month:%Y-%m} {self.product}"


class FacilityActivityMonthly(models.Model):
    """Flare, vent and fuel volumes per facility x month x activity x product.

    from_to_id is the well or facility the volume is attributed to ("" if none).
    """

    facility = models.ForeignKey(
        Facility, on_delete=models.PROTECT, related_name="activities"
    )
    month = models.DateField()
    activity = models.CharField(max_length=10)  # FLARE, VENT, FUEL
    product = models.CharField(max_length=10)
    from_to_id = models.CharField(max_length=20, blank=True, default="")
    from_to_id_type = models.CharField(max_length=4, blank=True, default="")
    volume = models.DecimalField(null=True, **VOLUME)
    energy = models.DecimalField(null=True, **VOLUME)
    hours = models.IntegerField(null=True)
    is_masked = models.BooleanField(default=False)
    submission_date = models.DateField(null=True)
    source_file = models.CharField(max_length=100)

    class Meta:
        db_table = "facility_activity_monthly"
        constraints = [
            models.UniqueConstraint(
                fields=["facility", "month", "activity", "product", "from_to_id"],
                name="uniq_activity_facility_month",
            )
        ]
        indexes = [models.Index(fields=["month", "activity"])]

    def __str__(self) -> str:
        return f"{self.facility_id} {self.month:%Y-%m} {self.activity} {self.product}"


class StgVolumetric(models.Model):
    """Staging table: filtered rows of one volumetrics file, loaded with COPY.

    Emptied at the start of every load; holds the columns petrinex.read produces.
    NULL here means "blank or masked in the source file", as in petrinex.read.
    """

    production_month = models.DateField()
    operator_baid = models.TextField()
    operator_name = models.TextField()
    reporting_facility_id = models.TextField()
    reporting_facility_type = models.TextField()
    reporting_facility_name = models.TextField()
    reporting_facility_subtype = models.TextField()
    submission_date = models.DateField(null=True)
    activity_id = models.TextField()
    product_id = models.TextField()
    from_to_id = models.TextField(null=True)  # noqa: DJ001 (mirrors the source)
    from_to_id_type = models.TextField(null=True)  # noqa: DJ001 (mirrors the source)
    volume = models.DecimalField(null=True, **VOLUME)
    energy = models.DecimalField(null=True, **VOLUME)
    hours = models.IntegerField(null=True)
    is_masked = models.BooleanField()

    class Meta:
        db_table = "stg_volumetric"

    def __str__(self) -> str:
        return f"{self.reporting_facility_id} {self.activity_id} {self.product_id}"


class PetrinexLoad(models.Model):
    """Audit record of one file load (lineage for every number we show)."""

    month = models.DateField()
    source_file = models.CharField(max_length=100)
    sha256 = models.CharField(max_length=64)
    rows_staged = models.IntegerField()
    production_rows = models.IntegerField()
    activity_rows = models.IntegerField()
    loaded_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "petrinex_loads"
        ordering = ["-loaded_at"]

    def __str__(self) -> str:
        return f"{self.source_file} @ {self.loaded_at:%Y-%m-%d %H:%M}"
