-- Create MySQL DB and user for the Django app
-- Edit DB name/user/password before running.

CREATE DATABASE peds_edu CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER 'peds_edu'@'%' IDENTIFIED BY 'CHANGE_ME_STRONG_PASSWORD';
GRANT ALL PRIVILEGES ON peds_edu.* TO 'peds_edu'@'%';
FLUSH PRIVILEGES;
