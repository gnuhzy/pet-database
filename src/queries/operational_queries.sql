-- =========================================
-- operational_queries.sql
-- Daily practical operations for shelter staff
-- =========================================

-- Q1: View all pets currently housed in a specific shelter
-- Purpose: Shelter staff checks the current pet list in one shelter
-- Params: shelter_id:int:A shelter ID
SELECT pet_id, name, species, breed, sex, status, intake_date
FROM PET
WHERE shelter_id = :shelter_id
ORDER BY intake_date DESC;


-- Q2: View all pets that are currently available for adoption
-- Purpose: Staff prepares the list of adoptable pets for visitors
SELECT pet_id, name, species, breed, sex, color, special_needs
FROM PET
WHERE status = 'available'
ORDER BY species, name;


-- Q3: View the full health information of a specific pet
-- Purpose: Staff reviews both vaccination and medical history before adoption or treatment
-- Params: pet_id:int:A pet ID
SELECT
    p.pet_id,
    p.name,
    p.species,
    p.breed,
    v.vaccine_name,
    v.vaccination_date,
    v.next_due_date,
    m.visit_date,
    m.record_type,
    m.diagnosis,
    m.treatment
FROM PET p
LEFT JOIN VACCINATION v ON p.pet_id = v.pet_id
LEFT JOIN MEDICAL_RECORD m ON p.pet_id = m.pet_id
WHERE p.pet_id = :pet_id
ORDER BY m.visit_date DESC, v.vaccination_date DESC;


-- Q4: View pets whose vaccination due date is approaching
-- Purpose: Staff identifies pets that need vaccination follow-up soon
-- Params: days_ahead:int:Number of days ahead to look (default 30)
SELECT
    p.pet_id,
    p.name,
    p.species,
    v.vaccine_name,
    v.next_due_date
FROM PET p
JOIN VACCINATION v ON p.pet_id = v.pet_id
WHERE v.next_due_date <= DATE_ADD(CURDATE(), INTERVAL :days_ahead DAY)
ORDER BY v.next_due_date;


-- Q5: View upcoming care assignments for a volunteer
-- Purpose: Volunteer coordinator checks a volunteer's scheduled tasks
-- Params: volunteer_id:int:A volunteer ID
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
WHERE c.volunteer_id = :volunteer_id
ORDER BY c.assignment_date DESC, c.shift;


-- Q6: View all adoption applications that are currently under review
-- Purpose: Adoption manager checks pending applications waiting for decision
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
ORDER BY a.application_date;


-- Q7: Approve a selected adoption application
-- Purpose: Approve an adoption application that is currently under review
-- Params: application_id:int:An application ID, reviewer_name:string:Reviewer name, decision_note:string:Decision note
UPDATE ADOPTION_APPLICATION
SET status = 'Approved',
    reviewed_date = CURDATE(),
    reviewer_name = :reviewer_name,
    decision_note = :decision_note
WHERE application_id = :application_id
  AND status = 'Under Review';


-- Q8: Insert a follow-up record after a completed adoption
-- Purpose: Staff records a follow-up for a completed adoption
-- Params: adoption_id:int:An adoption ID, followup_type:string:Follow-up type (e.g. Phone Check), pet_condition:string:Pet condition, adopter_feedback:string:Adopter feedback, result_status:string:Result status, staff_note:string:Staff note
INSERT INTO FOLLOW_UP (
    followup_id,
    adoption_id,
    followup_date,
    followup_type,
    pet_condition,
    adopter_feedback,
    result_status,
    staff_note
) VALUES (
    (SELECT COALESCE(MAX(followup_id), 0) + 1 FROM FOLLOW_UP),
    :adoption_id,
    CURDATE(),
    :followup_type,
    :pet_condition,
    :adopter_feedback,
    :result_status,
    :staff_note
);
