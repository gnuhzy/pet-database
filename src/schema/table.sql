-- =========================================
-- 1. SHELTER
-- =========================================
CREATE TABLE SHELTER (
    shelter_id INT PRIMARY KEY,
    name VARCHAR(100) NOT NULL UNIQUE,
    address VARCHAR(255),
    phone VARCHAR(20),
    capacity INT NOT NULL,
    CONSTRAINT chk_shelter_capacity_positive
        CHECK (capacity > 0)
);


-- =========================================
-- 2. APPLICANT
-- =========================================
CREATE TABLE APPLICANT (
    applicant_id INT PRIMARY KEY,
    full_name VARCHAR(100) NOT NULL,
    phone VARCHAR(20) UNIQUE,
    email VARCHAR(100) UNIQUE,
    address VARCHAR(255),
    housing_type VARCHAR(50),
    has_pet_experience BOOLEAN,
    created_at DATE
);


-- =========================================
-- 3. VOLUNTEER
-- each volunteer belongs to one shelter
-- =========================================
CREATE TABLE VOLUNTEER (
    volunteer_id INT PRIMARY KEY,
    shelter_id INT NOT NULL,
    full_name VARCHAR(100) NOT NULL,
    phone VARCHAR(20) UNIQUE,
    email VARCHAR(100) UNIQUE,
    join_date DATE,
    availability_note VARCHAR(255),
    CONSTRAINT fk_volunteer_shelter
        FOREIGN KEY (shelter_id) REFERENCES SHELTER(shelter_id)
);


-- =========================================
-- 4. PET
-- each pet is housed in one shelter
-- =========================================
CREATE TABLE PET (
    pet_id INT PRIMARY KEY,
    shelter_id INT NOT NULL,
    name VARCHAR(100) NOT NULL,
    species VARCHAR(50) NOT NULL,
    breed VARCHAR(50),
    sex VARCHAR(20),
    color VARCHAR(50),
    estimated_birth_date DATE,
    intake_date DATE NOT NULL,
    status VARCHAR(50) NOT NULL,
    is_sterilized BOOLEAN,
    special_needs VARCHAR(255),
    CONSTRAINT chk_pet_status
        CHECK (status IN ('available', 'reserved', 'medical_hold', 'adopted')),
    CONSTRAINT chk_pet_species
        CHECK (species IN ('Dog', 'Cat', 'Rabbit', 'Bird')),
    CONSTRAINT chk_pet_sex
        CHECK (sex IS NULL OR sex IN ('Male', 'Female', 'Unknown')),
    CONSTRAINT chk_pet_birth_before_intake
        CHECK (
            estimated_birth_date IS NULL
            OR date(estimated_birth_date) <= date(intake_date)
        ),
    CONSTRAINT fk_pet_shelter
        FOREIGN KEY (shelter_id) REFERENCES SHELTER(shelter_id)
);


-- =========================================
-- 5. VACCINATION
-- each vaccination record belongs to one pet
-- =========================================
CREATE TABLE VACCINATION (
    vaccination_id INT PRIMARY KEY,
    pet_id INT NOT NULL,
    vaccine_name VARCHAR(100) NOT NULL,
    dose_no INT,
    vaccination_date DATE NOT NULL,
    next_due_date DATE,
    vet_name VARCHAR(100),
    notes VARCHAR(255),
    CONSTRAINT chk_vaccination_dose_positive
        CHECK (dose_no IS NULL OR dose_no > 0),
    CONSTRAINT chk_vaccination_due_after_given
        CHECK (
            next_due_date IS NULL
            OR date(next_due_date) >= date(vaccination_date)
        ),
    CONSTRAINT fk_vaccination_pet
        FOREIGN KEY (pet_id) REFERENCES PET(pet_id)
);


-- =========================================
-- 6. MEDICAL_RECORD
-- each medical record belongs to one pet
-- =========================================
CREATE TABLE MEDICAL_RECORD (
    record_id INT PRIMARY KEY,
    pet_id INT NOT NULL,
    visit_date DATE NOT NULL,
    record_type VARCHAR(50),
    diagnosis VARCHAR(255),
    treatment VARCHAR(255),
    vet_name VARCHAR(100),
    notes VARCHAR(255),
    CONSTRAINT chk_medical_record_type
        CHECK (
            record_type IS NULL
            OR record_type IN ('Check-up', 'Surgery', 'Treatment', 'Injury', 'Dental')
        ),
    CONSTRAINT fk_medical_record_pet
        FOREIGN KEY (pet_id) REFERENCES PET(pet_id)
);


-- =========================================
-- 7. CARE_ASSIGNMENT
-- relationship between volunteer and pet
-- =========================================
CREATE TABLE CARE_ASSIGNMENT (
    assignment_id INT PRIMARY KEY,
    volunteer_id INT NOT NULL,
    pet_id INT NOT NULL,
    assignment_date DATE NOT NULL,
    shift VARCHAR(50),
    task_type VARCHAR(50),
    status VARCHAR(50),
    notes VARCHAR(255),
    CONSTRAINT chk_care_assignment_shift
        CHECK (shift IS NULL OR shift IN ('Morning', 'Afternoon', 'Evening')),
    CONSTRAINT chk_care_assignment_task_type
        CHECK (
            task_type IS NULL
            OR task_type IN ('Cleaning', 'Feeding', 'Grooming', 'Socializing', 'Walking', 'Medical support')
        ),
    CONSTRAINT chk_care_assignment_status
        CHECK (status IS NULL OR status IN ('Scheduled', 'Completed', 'Cancelled')),
    CONSTRAINT fk_care_assignment_volunteer
        FOREIGN KEY (volunteer_id) REFERENCES VOLUNTEER(volunteer_id),
    CONSTRAINT fk_care_assignment_pet
        FOREIGN KEY (pet_id) REFERENCES PET(pet_id)
);


-- =========================================
-- 8. ADOPTION_APPLICATION
-- each application is submitted by one applicant for one pet
-- =========================================
CREATE TABLE ADOPTION_APPLICATION (
    application_id INT PRIMARY KEY,
    applicant_id INT NOT NULL,
    pet_id INT NOT NULL,
    application_date DATE NOT NULL,
    status VARCHAR(50) NOT NULL,
    reason VARCHAR(255),
    reviewed_date DATE,
    reviewer_name VARCHAR(100),
    decision_note VARCHAR(255),
    CONSTRAINT chk_adoption_application_status
        CHECK (status IN ('Under Review', 'Approved', 'Rejected')),
    CONSTRAINT chk_adoption_application_reviewed_after_applied
        CHECK (
            reviewed_date IS NULL
            OR date(reviewed_date) >= date(application_date)
        ),
    CONSTRAINT fk_adoption_application_applicant
        FOREIGN KEY (applicant_id) REFERENCES APPLICANT(applicant_id),
    CONSTRAINT fk_adoption_application_pet
        FOREIGN KEY (pet_id) REFERENCES PET(pet_id)
);


-- =========================================
-- 9. ADOPTION_RECORD
-- each adoption record is based on one application
-- =========================================
CREATE TABLE ADOPTION_RECORD (
    adoption_id INT PRIMARY KEY,
    application_id INT NOT NULL UNIQUE,
    adoption_date DATE NOT NULL,
    final_adoption_fee DECIMAL(10,2),
    handover_note VARCHAR(255),
    CONSTRAINT chk_adoption_record_fee_nonnegative
        CHECK (final_adoption_fee IS NULL OR final_adoption_fee >= 0),
    CONSTRAINT fk_adoption_record_application
        FOREIGN KEY (application_id) REFERENCES ADOPTION_APPLICATION(application_id)
);


-- =========================================
-- 10. FOLLOW_UP
-- each follow-up belongs to one adoption record
-- =========================================
CREATE TABLE FOLLOW_UP (
    followup_id INT PRIMARY KEY,
    adoption_id INT NOT NULL,
    followup_date DATE NOT NULL,
    followup_type VARCHAR(50),
    pet_condition VARCHAR(255),
    adopter_feedback VARCHAR(255),
    result_status VARCHAR(50),
    staff_note VARCHAR(255),
    CONSTRAINT chk_followup_type
        CHECK (
            followup_type IS NULL
            OR followup_type IN ('Phone Check', 'Home Visit', 'Vet Check')
        ),
    CONSTRAINT chk_followup_result_status
        CHECK (
            result_status IS NULL
            OR result_status IN ('Excellent', 'Good', 'Satisfactory', 'Needs Improvement')
        ),
    CONSTRAINT fk_follow_up_adoption
        FOREIGN KEY (adoption_id) REFERENCES ADOPTION_RECORD(adoption_id)
);

-- =========================================
-- 11. SYSTEM_LOG
-- =========================================
CREATE TABLE SYSTEM_LOG (
    log_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_date DATETIME NOT NULL,
    event_type VARCHAR(50) NOT NULL,
    event_id INT,
    text VARCHAR(255) NOT NULL,
    dot_class VARCHAR(50) NOT NULL,
    sort_priority INT NOT NULL DEFAULT 50
);

