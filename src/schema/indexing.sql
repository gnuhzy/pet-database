-- =========================================
-- indexing.sql
-- Representative indexes for the
-- animal shelter management database
-- =========================================

-- Primary keys are indexed automatically.
-- These indexes support common joins, filters, scheduling checks, and
-- workflow uniqueness constraints used by the web application.

CREATE INDEX IF NOT EXISTS idx_pet_shelter_id
ON PET(shelter_id);

CREATE INDEX IF NOT EXISTS idx_pet_status
ON PET(status);

CREATE INDEX IF NOT EXISTS idx_pet_intake_date
ON PET(intake_date);

CREATE INDEX IF NOT EXISTS idx_vaccination_pet_id
ON VACCINATION(pet_id);

CREATE INDEX IF NOT EXISTS idx_vaccination_next_due_date
ON VACCINATION(next_due_date);

CREATE INDEX IF NOT EXISTS idx_adoption_application_applicant_id
ON ADOPTION_APPLICATION(applicant_id);

CREATE INDEX IF NOT EXISTS idx_adoption_application_pet_id
ON ADOPTION_APPLICATION(pet_id);

CREATE INDEX IF NOT EXISTS idx_adoption_application_status
ON ADOPTION_APPLICATION(status);

CREATE UNIQUE INDEX IF NOT EXISTS idx_adoption_record_application_unique
ON ADOPTION_RECORD(application_id);

CREATE UNIQUE INDEX IF NOT EXISTS idx_applicant_email_unique
ON APPLICANT(lower(email))
WHERE email IS NOT NULL AND email != '';

CREATE UNIQUE INDEX IF NOT EXISTS idx_volunteer_email_unique
ON VOLUNTEER(lower(email))
WHERE email IS NOT NULL AND email != '';

CREATE INDEX IF NOT EXISTS idx_care_assignment_volunteer_id
ON CARE_ASSIGNMENT(volunteer_id);

CREATE INDEX IF NOT EXISTS idx_care_assignment_pet_id
ON CARE_ASSIGNMENT(pet_id);

CREATE INDEX IF NOT EXISTS idx_care_assignment_volunteer_date
ON CARE_ASSIGNMENT(volunteer_id, assignment_date);

CREATE UNIQUE INDEX IF NOT EXISTS idx_care_assignment_unique_slot
ON CARE_ASSIGNMENT(volunteer_id, pet_id, assignment_date, shift);

CREATE INDEX IF NOT EXISTS idx_follow_up_adoption_id
ON FOLLOW_UP(adoption_id);
