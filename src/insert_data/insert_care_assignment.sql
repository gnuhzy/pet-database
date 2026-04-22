-- 07_insert_care_assignment.sql
-- Source: CareAssignment.csv

INSERT INTO CARE_ASSIGNMENT (assignment_id, volunteer_id, pet_id, assignment_date, shift, task_type, status, notes) VALUES
(1, 7, 16, '2025-08-14', 'Morning', 'Cleaning', 'Cancelled', 'Special attention needed'),
(2, 7, 7, '2025-09-16', 'Evening', 'Grooming', 'Scheduled', 'Routine task'),
(3, 1, 11, '2025-08-23', 'Afternoon', 'Feeding', 'Completed', 'Routine task'),
(4, 10, 19, '2025-10-01', 'Afternoon', 'Grooming', 'Completed', 'Friendly pet'),
(5, 6, 11, '2025-09-04', 'Evening', 'Cleaning', 'Completed', 'Routine task'),
(6, 4, 8, '2025-09-09', 'Afternoon', 'Grooming', 'Completed', 'Regular care'),
(7, 4, 16, '2025-07-22', 'Afternoon', 'Grooming', 'Completed', 'Regular care'),
(8, 3, 17, '2025-09-14', 'Afternoon', 'Feeding', 'Completed', 'Regular care'),
(9, 8, 15, '2025-05-18', 'Evening', 'Grooming', 'Completed', 'Special attention needed'),
(10, 7, 16, '2025-06-22', 'Afternoon', 'Socializing', 'Cancelled', 'Friendly pet'),
(11, 2, 11, '2025-10-05', 'Evening', 'Cleaning', 'Completed', 'Friendly pet'),
(12, 9, 2, '2025-09-21', 'Morning', 'Grooming', 'Cancelled', 'Routine task'),
(13, 5, 3, '2025-08-05', 'Morning', 'Feeding', 'Completed', 'Special attention needed'),
(14, 5, 1, '2025-04-27', 'Afternoon', 'Feeding', 'Completed', 'Routine task'),
(15, 6, 14, '2025-05-23', 'Morning', 'Socializing', 'Completed', 'Special attention needed');
