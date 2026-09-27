# CivicPulse AI schema migration

The existing SQLite database is preserved.

On application startup, `init_db()`:
1. Creates missing tables if needed.
2. Adds only missing columns to `citizen_requests` and `request_analysis`.
3. Adds required indexes.
4. Preserves all existing records.
5. Backfills missing SLA due dates without deleting data.

New request fields include multilingual/voice provenance:
- `original_language`
- `language_override`
- `original_text`
- `normalized_text`
- `voice_transcript`
- `input_mode`

New analysis fields include human review and explainability metadata:
- `review_status`
- `officer_decision`
- `officer_modification`
- `reviewer_id`
- `confidence_details`

No destructive migration is used.


## Added in Hack2Skill closed-loop update
- `citizen_feedback.reopened_requested` BOOLEAN
- `citizen_feedback.reopened_reason` TEXT
- Migration is idempotent and preserves existing records.


## Feature 39–44
No destructive schema change is required for these additions. They reuse the existing request, analysis, feedback, project, department, SLA and audit tables. Search language filtering uses existing `original_language` / `language_override` fields. Impact, quality, insight and transparency metrics are calculated at request time from stored records.
