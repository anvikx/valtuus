# Catalog rollout

Deploy in two stages. The current main image always runs Alembic at startup and cannot
resolve catalog revision 0008. Adding columns alone cannot make that image a working rollback
target. Main's session migrations retain revisions 0006 and 0007; the catalog follows them.

1. First land the separate PR from branch agent-deploy-skip-migrations. It adds
   SKIP_DATABASE_MIGRATIONS (false by default) to startup, Compose and deploy.sh. Deploy it on
   the existing schema, verify health, and confirm its tag is saved in .last_good_tag.
2. Then land and deploy the catalog changes and additive migration 0008. Normal deployments
   explicitly run migrations. Failed deployments start the prerequisite image with
   SKIP_DATABASE_MIGRATIONS=true, leaving the database revision unchanged.

Never use the original main image as the rollback target for stage 2. Keep the legacy allergen
array until a later rollout no longer needs an image that reads it. Do not stamp the revision
backward: migrations remain forward only.

A local database migrated with an earlier draft of this change (catalog revision 0006) must be
recreated. That revision number now belongs to sessions.
