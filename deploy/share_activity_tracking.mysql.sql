-- Manual MySQL fallback for share activity tracking.
-- Use this only if Django migrations cannot be applied.

START TRANSACTION;

CREATE TABLE IF NOT EXISTS `sharing_doctorsharesummary` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `doctor_id` varchar(32) NOT NULL,
  `doctor_name_snapshot` varchar(255) NOT NULL DEFAULT '',
  `clinic_name_snapshot` varchar(255) NOT NULL DEFAULT '',
  `total_shares` bigint unsigned NOT NULL DEFAULT 0,
  `last_shared_at` datetime(6) DEFAULT NULL,
  `created_at` datetime(6) NOT NULL,
  `updated_at` datetime(6) NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `sharing_doctorsharesummary_doctor_id_uniq` (`doctor_id`),
  KEY `sharing_doc_last_sh_fdbd7d_idx` (`last_shared_at`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `sharing_shareactivity` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `public_id` char(32) NOT NULL,
  `doctor_id` varchar(32) NOT NULL,
  `doctor_name_snapshot` varchar(255) NOT NULL DEFAULT '',
  `clinic_name_snapshot` varchar(255) NOT NULL DEFAULT '',
  `share_channel` varchar(30) NOT NULL DEFAULT 'whatsapp',
  `shared_by_role` varchar(30) NOT NULL DEFAULT '',
  `shared_item_type` varchar(20) NOT NULL,
  `shared_item_code` varchar(80) NOT NULL,
  `shared_item_name` varchar(255) NOT NULL,
  `language_code` varchar(10) NOT NULL DEFAULT 'en',
  `recipient_reference` varchar(80) NOT NULL,
  `recipient_reference_version` smallint unsigned NOT NULL DEFAULT 1,
  `shared_at` datetime(6) NOT NULL,
  `doctor_summary_id` bigint NOT NULL,
  PRIMARY KEY (`id`),
  UNIQUE KEY `sharing_shareactivity_public_id_uniq` (`public_id`),
  KEY `sharing_shareactivity_doctor_summary_id_idx` (`doctor_summary_id`),
  KEY `sharing_shareactivity_doctor_id_idx` (`doctor_id`),
  KEY `sharing_shareactivity_shared_item_type_idx` (`shared_item_type`),
  KEY `sharing_shareactivity_recipient_reference_idx` (`recipient_reference`),
  KEY `sharing_shareactivity_shared_at_idx` (`shared_at`),
  KEY `sharing_sha_doctor__d4d086_idx` (`doctor_id`, `shared_at`),
  KEY `sharing_sha_shared__51353f_idx` (`shared_item_type`, `shared_item_code`),
  CONSTRAINT `sharing_shareactivity_doctor_summary_fk`
    FOREIGN KEY (`doctor_summary_id`) REFERENCES `sharing_doctorsharesummary` (`id`)
    ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS `sharing_shareplaybackevent` (
  `id` bigint NOT NULL AUTO_INCREMENT,
  `share_public_id` char(32) DEFAULT NULL,
  `doctor_id` varchar(32) NOT NULL,
  `page_item_type` varchar(20) NOT NULL,
  `event_type` varchar(20) NOT NULL,
  `video_code` varchar(80) NOT NULL,
  `video_name` varchar(255) NOT NULL DEFAULT '',
  `milestone_percent` smallint unsigned DEFAULT NULL,
  `occurred_at` datetime(6) NOT NULL,
  `doctor_summary_id` bigint NOT NULL,
  `share_id` bigint DEFAULT NULL,
  PRIMARY KEY (`id`),
  KEY `sharing_shareplaybackevent_doctor_summary_id_idx` (`doctor_summary_id`),
  KEY `sharing_shareplaybackevent_share_id_idx` (`share_id`),
  KEY `sharing_shareplaybackevent_share_public_id_idx` (`share_public_id`),
  KEY `sharing_shareplaybackevent_doctor_id_idx` (`doctor_id`),
  KEY `sharing_shareplaybackevent_event_type_idx` (`event_type`),
  KEY `sharing_shareplaybackevent_occurred_at_idx` (`occurred_at`),
  KEY `sharing_sha_doctor__9dd63b_idx` (`doctor_id`, `occurred_at`),
  KEY `sharing_sha_video_c_4253f7_idx` (`video_code`, `event_type`),
  CONSTRAINT `sharing_shareplaybackevent_doctor_summary_fk`
    FOREIGN KEY (`doctor_summary_id`) REFERENCES `sharing_doctorsharesummary` (`id`)
    ON DELETE CASCADE,
  CONSTRAINT `sharing_shareplaybackevent_share_fk`
    FOREIGN KEY (`share_id`) REFERENCES `sharing_shareactivity` (`id`)
    ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Reference ALTER statements for partially-created tables:
-- ALTER TABLE `sharing_shareactivity`
--   ADD UNIQUE KEY `sharing_shareactivity_public_id_uniq` (`public_id`),
--   ADD KEY `sharing_shareactivity_doctor_summary_id_idx` (`doctor_summary_id`),
--   ADD KEY `sharing_shareactivity_doctor_id_idx` (`doctor_id`),
--   ADD KEY `sharing_shareactivity_shared_item_type_idx` (`shared_item_type`),
--   ADD KEY `sharing_shareactivity_recipient_reference_idx` (`recipient_reference`),
--   ADD KEY `sharing_shareactivity_shared_at_idx` (`shared_at`),
--   ADD KEY `sharing_sha_doctor__d4d086_idx` (`doctor_id`, `shared_at`),
--   ADD KEY `sharing_sha_shared__51353f_idx` (`shared_item_type`, `shared_item_code`);
--
-- ALTER TABLE `sharing_shareplaybackevent`
--   ADD KEY `sharing_shareplaybackevent_doctor_summary_id_idx` (`doctor_summary_id`),
--   ADD KEY `sharing_shareplaybackevent_share_id_idx` (`share_id`),
--   ADD KEY `sharing_shareplaybackevent_share_public_id_idx` (`share_public_id`),
--   ADD KEY `sharing_shareplaybackevent_doctor_id_idx` (`doctor_id`),
--   ADD KEY `sharing_shareplaybackevent_event_type_idx` (`event_type`),
--   ADD KEY `sharing_shareplaybackevent_occurred_at_idx` (`occurred_at`),
--   ADD KEY `sharing_sha_doctor__9dd63b_idx` (`doctor_id`, `occurred_at`),
--   ADD KEY `sharing_sha_video_c_4253f7_idx` (`video_code`, `event_type`);

COMMIT;
