-- Attach RSA public key to your existing Snowsight user (TBPANDA).
-- Key-pair auth from Railway bypasses interactive MFA — no new user needed.
--
-- In Snowsight: worksheet role = ACCOUNTADMIN (or SECURITYADMIN), then Run All.

USE ROLE ACCOUNTADMIN;

ALTER USER TBPANDA SET RSA_PUBLIC_KEY='PASTE_PUBLIC_KEY_BODY_HERE';

-- Optional: confirm fingerprint
DESC USER TBPANDA;
