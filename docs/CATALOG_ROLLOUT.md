# Catalog rollout

Deploy in two stages. The current main image always runs Alembic at startup and cannot
resolve catalog revision 0008. Adding columns alone cannot make that image a working rollback
target. Main's session migrations retain revisions 0006 and 0007; the catalog follows them.

1. First land only the changes to backend/app/config.py, backend/app/main.py,
   docker-compose.yml and scripts/deploy.sh, plus the startup and deployment regression tests.
   This prerequisite adds SKIP_DATABASE_MIGRATIONS (false by default). Deploy it on the
   existing schema, verify health, and confirm its tag is saved in .last_good_tag.
2. Then land and deploy the catalog changes and additive migration 0008. Normal deployments
   explicitly run migrations. Failed deployments start the prerequisite image with
   SKIP_DATABASE_MIGRATIONS=true, leaving the database revision unchanged.

Never use the original main image as the rollback target for stage 2. Keep the legacy allergen
array until a later rollout no longer needs an image that reads it. Do not stamp the revision
backward: migrations remain forward only.

Earlier unmerged catalog migrations used revision 0006, which main now uses for sessions.
The original catalog migration also changed the array type in place. Databases that applied
either unmerged catalog revision must be disposable and recreated before testing this
replacement. Do not run this migration chain against a retained database already stamped
with catalog revision 0006.

Suggested stage 1 commit: `fix(deploy): skip schema migrations during image rollback`

Suggested stage 2 title: `fix(catalog): preserve allergen declarations and multilingual names`

Suggested PR description:

Restore KNOWN for products with explicit FREE_FROM declarations, keep CONTAINS and MAY_CONTAIN
separate, and preserve English, Finnish and Swedish names through Postgres round trips and search.
Add nullable columns while retaining the legacy allergen array and snapshot fields for rollback.
Deploy the migration-skipping startup prerequisite before this schema change.
