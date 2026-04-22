-- =========================================
-- analytical_queries.sql
-- Analytical queries for shelter management
-- SQLite is the official execution target.
-- =========================================

-- Q1: Analyze current occupancy of each shelter
-- Purpose: Managers monitor how full each shelter is and identify capacity pressure.
-- Example: Run directly to compare shelters by current active occupancy.
-- Result characteristics: Includes shelters with zero active pets and orders by occupancy rate.
SELECT
    s.shelter_id,
    s.name AS shelter_name,
    s.capacity,
    COUNT(p.pet_id) AS current_pet_count,
    ROUND(COUNT(p.pet_id) * 100.0 / s.capacity, 2) AS occupancy_rate
FROM SHELTER s
LEFT JOIN PET p
    ON s.shelter_id = p.shelter_id
   AND p.status IN ('available', 'reserved', 'medical_hold')
GROUP BY s.shelter_id, s.name, s.capacity
ORDER BY occupancy_rate DESC, s.shelter_id;


-- Q2: Analyze pets that have stayed the longest in the shelter
-- Purpose: Staff identifies long-stay pets that may need promotion or special adoption support.
-- Example: Run directly to list the available pets with the highest shelter stay durations.
-- Result characteristics: Returns only adoptable pets and calculates days_in_shelter in SQLite.
SELECT
    pet_id,
    name,
    species,
    breed,
    shelter_id,
    intake_date,
    CAST(julianday(date('now', '+8 hours')) - julianday(intake_date) AS INTEGER) AS days_in_shelter
FROM PET
WHERE status = 'available'
ORDER BY days_in_shelter DESC, pet_id;


-- Q3: Analyze adoption application results by housing type
-- Purpose: Managers examine whether applicant housing type is related to approval outcomes.
-- Example: Run directly to compare adoption approvals across housing profiles.
-- Result characteristics: Returns one aggregate row per housing type with approval and rejection counts.
SELECT
    ap.housing_type,
    COUNT(a.application_id) AS total_applications,
    SUM(CASE WHEN a.status = 'Approved' THEN 1 ELSE 0 END) AS approved_count,
    SUM(CASE WHEN a.status = 'Rejected' THEN 1 ELSE 0 END) AS rejected_count,
    ROUND(
        SUM(CASE WHEN a.status = 'Approved' THEN 1 ELSE 0 END) * 100.0
        / COUNT(a.application_id),
        2
    ) AS approval_rate
FROM APPLICANT ap
JOIN ADOPTION_APPLICATION a
    ON ap.applicant_id = a.applicant_id
GROUP BY ap.housing_type
ORDER BY approval_rate DESC, ap.housing_type;


-- Q4: Analyze adoption demand and success rate by pet species
-- Purpose: Shelter management studies which types of pets attract more applications and achieve higher adoption success.
-- Example: Run directly to compare species-level demand and conversion.
-- Result characteristics: Returns one row per species with application volume and adoption success rate.
SELECT
    p.species,
    COUNT(aa.application_id) AS total_applications,
    COUNT(ar.adoption_id) AS successful_adoptions,
    ROUND(
        COUNT(ar.adoption_id) * 100.0 / COUNT(aa.application_id),
        2
    ) AS adoption_success_rate
FROM PET p
JOIN ADOPTION_APPLICATION aa
    ON p.pet_id = aa.pet_id
LEFT JOIN ADOPTION_RECORD ar
    ON aa.application_id = ar.application_id
GROUP BY p.species
ORDER BY total_applications DESC, adoption_success_rate DESC, p.species;


-- Q5: Analyze volunteer workload based on care assignments
-- Purpose: Coordinators review volunteer participation and task completion.
-- Example: Run directly to compare assignment load and completion counts across volunteers.
-- Result characteristics: Includes volunteers with zero assignments and separates completed, scheduled, and cancelled totals.
SELECT
    v.volunteer_id,
    v.full_name,
    COUNT(c.assignment_id) AS total_assignments,
    SUM(CASE WHEN c.status = 'Completed' THEN 1 ELSE 0 END) AS completed_tasks,
    SUM(CASE WHEN c.status = 'Cancelled' THEN 1 ELSE 0 END) AS cancelled_tasks,
    SUM(CASE WHEN c.status = 'Scheduled' THEN 1 ELSE 0 END) AS scheduled_tasks
FROM VOLUNTEER v
LEFT JOIN CARE_ASSIGNMENT c
    ON v.volunteer_id = c.volunteer_id
GROUP BY v.volunteer_id, v.full_name
ORDER BY completed_tasks DESC, total_assignments DESC, v.volunteer_id;


-- Q6: Analyze post-adoption follow-up outcomes
-- Purpose: Managers evaluate whether adopted pets are adjusting well after adoption.
-- Example: Run directly to summarize follow-up outcomes across all completed adoptions.
-- Result characteristics: Returns one row per follow-up result status.
SELECT
    f.result_status,
    COUNT(f.followup_id) AS total_followups
FROM FOLLOW_UP f
GROUP BY f.result_status
ORDER BY total_followups DESC, f.result_status;
