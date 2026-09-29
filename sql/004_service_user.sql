-- Attach RSA public key to your existing Snowsight user (TBPANDA).
-- Key-pair auth from Railway bypasses interactive MFA — no new user needed.
--
-- Prefer running .secrets/004_service_user_READY.sql (key already filled in).
-- In Snowsight: worksheet role = ACCOUNTADMIN (or SECURITYADMIN), then Run All.
-- After ALTER, DESC USER TBPANDA and confirm RSA_PUBLIC_KEY_FP =
--   SHA256:p0eE9CdNOUepfrzUUgNGeDlejCfrWN7eIR94ThXX5DM=
-- Empty/mismatched FP → Railway error 390144 "JWT token is invalid".

USE ROLE ACCOUNTADMIN;

ALTER USER TBPANDA SET RSA_PUBLIC_KEY='PASTE_PUBLIC_KEY_BODY_HERE';

-- Confirm fingerprint matches the value above
DESC USER TBPANDA;
