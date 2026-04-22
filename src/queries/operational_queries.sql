-- =========================================
-- operational_queries.sql
-- Daily practical operations for shelter staff
-- SQLite is the official execution target.
-- =========================================

-- Q1: View all pets currently housed in a specific shelter
-- Purpose: Shelter staff checks the current pet list in one shelter.
-- Example: Change shelter_id = 1 to inspect a different shelter branch.
-- Result characteristics: Returns one row per pet, ordered by the newest intake first.
SELECT
    pet_id,
    name,
    species,
    breed,
    sex,
    status,
    intake_date
FROM PET
WHERE shelter_id = 1
ORDER BY date(intake_date) DESC, pet_id DESC;


-- Q2: View all pets that are currently available for adoption
-- Purpose: Staff prepares the list of adoptable pets for visitors.
-- Example: Run directly in SQLite to list the current adoptable roster.
-- Result characteristics: Returns only PET rows whose workflow status is available.
SELECT
    pet_id,
    name,
    species,
    breed,
    sex,
    color,
    special_needs
FROM PET
WHERE status = 'available'
ORDER BY species, name;


-- Q3: View the full health information of a specific pet
-- Purpose: Staff reviews a single pet's medical and vaccination history on one timeline.
-- Example: Change pet_id = 5 to inspect another pet.
-- Result characteristics: Returns one row per health event; no vaccination-medical cross product is produced.
SELECT
    pet_id,
    pet_name,
    species,
    breed,
    event_kind,
    event_date,
    event_title,
    event_details,
    due_or_followup_date,
    staff_name,
    notes
FROM (
    SELECT
        p.pet_id AS pet_id,
        p.name AS pet_name,
        p.species AS species,
        p.breed AS breed,
        'Vaccination' AS event_kind,
        v.vaccination_date AS event_date,
        v.vaccine_name AS event_title,
        CASE
            WHEN v.dose_no IS NULL THEN 'Dose not recorded'
            ELSE 'Dose ' || v.dose_no
        END AS event_details,
        v.next_due_date AS due_or_followup_date,
        COALESCE(v.vet_name, 'Unknown') AS staff_name,
        COALESCE(v.notes, '') AS notes
    FROM PET p
    JOIN VACCINATION v ON p.pet_id = v.pet_id

    UNION ALL

    SELECT
        p.pet_id AS pet_id,
        p.name AS pet_name,
        p.species AS species,
        p.breed AS breed,
        'Medical' AS event_kind,
        m.visit_date AS event_date,
        COALESCE(m.record_type, 'Medical visit') AS event_title,
        TRIM(
            COALESCE(m.diagnosis, '')
            || CASE WHEN m.diagnosis IS NOT NULL AND m.treatment IS NOT NULL THEN ' | ' ELSE '' END
            || COALESCE(m.treatment, '')
        ) AS event_details,
        NULL AS due_or_followup_date,
        COALESCE(m.vet_name, 'Unknown') AS staff_name,
        COALESCE(m.notes, '') AS notes
    FROM PET p
    JOIN MEDICAL_RECORD m ON p.pet_id = m.pet_id
)
WHERE pet_id = 5
ORDER BY date(event_date) DESC, event_kind, event_title;


-- Q4: View pets whose vaccination due date is approaching
-- Purpose: Staff identifies pets that need vaccination follow-up soon.
-- Example: Returns vaccinations due within the next 30 days from the execution date.
-- Result characteristics: Excludes records with no due date and sorts by the nearest deadline first.
SELECT
    p.pet_id,
    p.name,
    p.species,
    v.vaccine_name,
    v.next_due_date
FROM PET p
JOIN VACCINATION v ON p.pet_id = v.pet_id
WHERE v.next_due_date IS NOT NULL
  AND date(v.next_due_date) <= date('now', '+8 hours', '+30 day')
ORDER BY date(v.next_due_date), p.pet_id;


-- Q5: View upcoming care assignments for a volunteer
-- Purpose: Volunteer coordinators check one volunteer's schedule.
-- Example: Change volunteer_id = 2 to inspect a different volunteer.
-- Result characteristics: Returns one row per assignment, newest dates first.
SELECT
    c.assignment_id,
    c.assignment_date,
    c.shift,
    c.task_type,
    c.status,
    p.pet_id,
    p.name AS pet_name,
    p.species
FROM CARE_ASSIGNMENT c
JOIN PET p ON c.pet_id = p.pet_id
WHERE c.volunteer_id = 2
ORDER BY date(c.assignment_date) DESC, c.shift, c.assignment_id DESC;


-- Q6: View all adoption applications that are currently under review
-- Purpose: Adoption managers check applications waiting for a final decision.
-- Example: Run directly to inspect the pending review queue.
-- Result characteristics: Returns only the active review queue, oldest applications first.
SELECT
    a.application_id,
    ap.full_name AS applicant_name,
    p.name AS pet_name,
    p.species,
    a.application_date,
    a.status,
    a.reviewer_name
FROM ADOPTION_APPLICATION a
JOIN APPLICANT ap ON a.applicant_id = ap.applicant_id
JOIN PET p ON a.pet_id = p.pet_id
WHERE a.status = 'Under Review'
ORDER BY date(a.application_date), a.application_id;
