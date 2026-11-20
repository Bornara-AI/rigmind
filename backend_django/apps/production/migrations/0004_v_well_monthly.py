from django.db import migrations

CREATE_VIEW = """
CREATE VIEW v_well_monthly AS
WITH pivot AS (
    SELECT well_id,
           month,
           SUM(volume) FILTER (WHERE product = 'OIL')   AS oil_m3,
           SUM(volume) FILTER (WHERE product = 'GAS')   AS gas_e3m3,
           SUM(volume) FILTER (WHERE product = 'WATER') AS water_m3,
           SUM(volume) FILTER (WHERE product = 'COND')  AS cond_m3,
           MAX(hours)                                   AS hours_on,
           bool_or(is_masked)                           AS is_masked
    FROM production_monthly
    GROUP BY well_id, month
)
SELECT p.well_id,
       w.uwi,
       w.well_name,
       w.licensee_name,
       w.field_name,
       p.month,
       p.oil_m3,
       p.gas_e3m3,
       p.water_m3,
       p.cond_m3,
       p.hours_on,
       ROUND(p.gas_e3m3 * 1000 / NULLIF(p.oil_m3, 0), 1) AS gor_m3_m3,
       ROUND(p.water_m3 / NULLIF(COALESCE(p.oil_m3, 0) + p.water_m3, 0), 4)
           AS water_cut,
       p.is_masked
FROM pivot p
LEFT JOIN wells w USING (well_id);

COMMENT ON VIEW v_well_monthly IS
    'One row per well and month (first day of month), pivoted from production_monthly.';
COMMENT ON COLUMN v_well_monthly.oil_m3 IS 'Oil volume, m3';
COMMENT ON COLUMN v_well_monthly.gas_e3m3 IS 'Gas volume, thousand m3 (e3m3)';
COMMENT ON COLUMN v_well_monthly.water_m3 IS 'Water volume, m3';
COMMENT ON COLUMN v_well_monthly.cond_m3 IS 'Condensate volume, m3';
COMMENT ON COLUMN v_well_monthly.hours_on IS 'Producing hours in the month (max over products)';
COMMENT ON COLUMN v_well_monthly.gor_m3_m3 IS 'Gas-oil ratio, m3 gas per m3 oil';
COMMENT ON COLUMN v_well_monthly.water_cut IS 'Water / (oil + water), 0-1';
COMMENT ON COLUMN v_well_monthly.is_masked IS 'Some source values were confidential';
"""


class Migration(migrations.Migration):
    """Staging for wells is UNLOGGED; v_well_monthly pivots production per well."""

    dependencies = [("production", "0003_wells")]

    operations = [
        migrations.RunSQL(
            "ALTER TABLE stg_wells SET UNLOGGED",
            reverse_sql="ALTER TABLE stg_wells SET LOGGED",
        ),
        migrations.RunSQL(CREATE_VIEW, reverse_sql="DROP VIEW v_well_monthly"),
    ]
