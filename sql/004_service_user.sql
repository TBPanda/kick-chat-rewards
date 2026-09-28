-- Minimal service user for Railway ingest (uses existing SYSADMIN — no custom role).
-- In Snowsight: set the worksheet role dropdown to ACCOUNTADMIN, then Run All.

USE ROLE ACCOUNTADMIN;

CREATE USER IF NOT EXISTS KICK_INGEST
  TYPE = SERVICE
  COMMENT = 'Railway webhook ingest for amirphanthom chat';

-- Public key body only (no -----BEGIN/END----- lines):
ALTER USER KICK_INGEST SET RSA_PUBLIC_KEY='PASTE_PUBLIC_KEY_BODY_HERE';

GRANT ROLE SYSADMIN TO USER KICK_INGEST;

ALTER USER KICK_INGEST SET
  DEFAULT_ROLE = SYSADMIN
  DEFAULT_WAREHOUSE = COMPUTE_WH
  DEFAULT_NAMESPACE = KICK_CHAT.AMIRPHANTHOM;
