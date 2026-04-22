## 1. Introduction

The proposed system is a **Pet Adoption Center Management System** designed to support the internal operations of a pet adoption center. The system must manage pet profiles, applicant information, adoption applications, confirmed adoptions, post-adoption follow-up, medical and vaccination records, and volunteer care arrangements. Part 3 "functional requirements" formalize the operational expectations of the organization and define the scope of the database application. 
## 2. Design Rationale

The database is designed for a pet adoption center that manages rescued animals, adoption requests, post-adoption follow-up, medical care, vaccination history, and volunteer care scheduling. The design aims to achieve four goals at the same time:

1. to reflect the real operational workflow of a pet adoption center,
    
2. to maintain a clear and normalized conceptual structure,
    
3. to support practical SQL queries for daily management,
    
4. to remain manageable for later implementation.
    
---
## 3. Functional Requirements

**FR-1. Shelter Information Management**

The system shall store and maintain basic information about each shelter, including shelter name, address, phone number, and capacity.

**FR-2. Pet Registration and Profile Management**

The system shall allow staff to register each pet that enters the shelter and maintain its profile, including name, species, breed, sex, color, estimated birth date, intake date, sterilization status, special needs, and current operational status.

**FR-3. Pet Status Tracking**

The system shall record the current status of each pet, such as available, reserved, medical_hold, or adopted, so that staff can identify which pets are currently eligible for adoption.

**FR-4. Applicant Registration and Information Management**

The system shall store applicant information, including full name, phone number, email address, address, housing type, and prior pet-care experience.

**FR-5. Adoption Application Submission**

The system shall record each adoption application submitted by an applicant for a specific pet, including the application date and the applicant’s reason for adoption.

**FR-6. Adoption Application Review and Decision Recording**

The system shall support the review of adoption applications and store the review status, review date, reviewer name, and decision note for each application.

**FR-7. Successful Adoption Recording**

The system shall create a confirmed adoption record only when an adoption application is successfully completed. The adoption record shall store the adoption date, final adoption fee, and handover-related notes.

**FR-8. Post-Adoption Follow-Up Management**

The system shall allow staff to record multiple follow-up activities for each confirmed adoption, including follow-up date, follow-up type, pet condition, adopter feedback, result status, and staff notes.

**FR-9. Medical Record Management**

The system shall maintain general medical records for each pet, including medical visit date, record type, diagnosis, treatment, veterinarian name, and notes.

**FR-10. Vaccination Record Management**

The system shall maintain vaccination records for each pet, including vaccine name, dose number, vaccination date, next due date, veterinarian name, and notes.

**FR-11. Volunteer Registration and Management**

The system shall store volunteer information, including the shelter to which the volunteer belongs, full name, phone number, email address, join date, and availability note.

**FR-12. Volunteer Care Assignment Scheduling**

The system shall support assignment of volunteers to pets for specific dates, shifts, and task types, and shall record the assignment status and optional notes.

**FR-13. Relationship Consistency Enforcement**

The system shall enforce referential integrity among shelters, pets, applicants, applications, adoption records, follow-up records, medical records, vaccination records, volunteers, and care assignments.

**FR-14. Adoption Uniqueness Control**

The system shall ensure that each successful adoption record corresponds to exactly one adoption application, and that each adoption application can generate at most one adoption record.

**FR-15. Query Support for Daily Operations**

The system shall support practical operational queries, including but not limited to:

·        retrieving currently adoptable pets,

·        listing all applications for a given pet,

·        retrieving the medical and vaccination history of a pet,

·        retrieving all follow-up records for an adopted pet,

·        viewing volunteer assignments by date or shift.

## 4. Main Entities and Their Meanings

### 4.1 Shelter

The **Shelter** entity represents a physical pet adoption center or branch. It stores basic administrative information such as the shelter name, address, phone number, and capacity. 

### 4.2 Pet

The **Pet** entity is the core operational entity of the system. It stores the profile and current operational status of each animal, including its name, species, breed, sex, color, estimated birth date, intake date, current status, sterilization status, and special needs. Each pet belongs to exactly one shelter.

### 4.3 Applicant

The **Applicant** entity represents a person who applies to adopt a pet. It stores contact details and background information relevant to adoption review, such as full name, phone number, email address, home address, housing type, and prior pet-care experience.

### 4.4 AdoptionApplication

The **AdoptionApplication** entity represents an adoption request submitted by an applicant for a specific pet. It records the application date, the applicant’s reason, the review status, the review date, the reviewer’s name, and the decision note. This entity models the application and evaluation workflow only. It does **not** store the final confirmed adoption event.

### 4.5 AdoptionRecord

The **AdoptionRecord** entity represents a successful adoption. It is created only after an application has been approved and completed. It records the adoption date, final adoption fee, and handover-related notes. Each adoption record must correspond to exactly one application, and each successful application can generate at most one adoption record.

### 4.6 FollowUp

The **FollowUp** entity stores post-adoption follow-up activities. Each follow-up record is linked to one adoption record, and one adoption record may have multiple follow-up records over time. This reflects the real practice that shelters often perform several welfare checks after a pet has been adopted.

### 4.7 MedicalRecord

The **MedicalRecord** entity stores general medical history for a pet. Each record describes a medical event such as a check-up, illness, injury, surgery, or sterilization procedure. It typically includes the visit date, record type, diagnosis, treatment, veterinarian name, and notes.

### 4.8 Vaccination

The **Vaccination** entity stores vaccination-specific information for a pet. It is modeled separately from MedicalRecord because vaccination events have a more specialized structure, including vaccine name, dose number, vaccination date, and next due date.

### 4.9 Volunteer

The **Volunteer** entity represents a volunteer who helps the shelter with daily tasks. Each volunteer belongs to one shelter and has basic information such as full name, phone number, email address, join date, and availability notes.

### 4.10 CareAssignment

The **CareAssignment** entity is an associative entity that resolves the many-to-many relationship between volunteers and pets. It records which volunteer is assigned to which pet, on which date, during which shift, for what task, and with what assignment status.

---

## 5. Relationships and Cardinalities

### 5.1 Shelter–Pet

One shelter can house many pets, but each pet belongs to exactly one shelter.  
This is a **one-to-many (1:N)** relationship.

### 5.2 Shelter–Volunteer

One shelter can manage many volunteers, but each volunteer is associated with exactly one shelter.  
This is a **one-to-many (1:N)** relationship.

### 5.3 Applicant–AdoptionApplication

One applicant can submit multiple adoption applications, but each application is submitted by exactly one applicant.  
This is a **one-to-many (1:N)** relationship.

### 5.4 Pet–AdoptionApplication

One pet may receive multiple applications over time, but each application concerns exactly one pet.  
This is a **one-to-many (1:N)** relationship.

### 5.5 AdoptionApplication–AdoptionRecord

One application may or may not lead to a successful adoption. If the adoption is confirmed, one adoption record is created. Each adoption record must correspond to exactly one application.  
This is a **one-to-zero-or-one (1:0..1)** relationship.

### 5.6 AdoptionRecord–FollowUp

One adoption record may have multiple follow-up records, but each follow-up record belongs to exactly one adoption record.  
This is a **one-to-many (1:N)** relationship.

### 5.7 Pet–MedicalRecord

One pet may have many medical records, but each medical record belongs to exactly one pet.  
This is a **one-to-many (1:N)** relationship.

### 5.8 Pet–Vaccination

One pet may have many vaccination records, but each vaccination record belongs to exactly one pet.  
This is a **one-to-many (1:N)** relationship.

### 5.9 Volunteer–Pet through CareAssignment

One volunteer may care for multiple pets, and one pet may be cared for by multiple volunteers.  
This is a **many-to-many (M:N)** relationship resolved through **CareAssignment**.

---

## 6. Core Business Rules and Assumptions

The following assumptions define the operational logic of the system.

- Each pet must belong to one shelter.
    
- Each volunteer must belong to one shelter.
    
- Each application must refer to exactly one applicant and one pet.
    
- One applicant may submit multiple applications.
    
- One pet may receive multiple applications over time.
    
- An adoption record can only be created for an approved and completed application.
    
- A follow-up record can only exist if there is a confirmed adoption record.
    
- Each pet may have multiple medical and vaccination records.
    
- The current sterilization state of a pet is stored directly in the Pet entity, while a sterilization procedure may also appear as a medical record.
    
- The reviewer field represents a staff member rather than a volunteer. 
    
- Staff reviewers are permitted to conduct cross-shelter reviews.
    
- Multiple adoption applications may be submitted for the same pet. But only one application could be finally accepted.
    
- Post-adoption medical records and vaccination records are allowed and are considered part of the follow-up stage.

---

# ER Diagram

See [mermaid-ER-diagram.png](https://github.com/gnuhzy/pet-database/blob/59b4e221aef3d1786b2dce3482cd23be1c500ea3/mermaid-ER-diagram.png)

---

# 7. Functional Dependencies

## 7.1 Assumptions for Functional Dependency Analysis

The following functional dependencies are stated **under the assumptions of the current project scope**. In particular:

- surrogate IDs are treated as the primary keys of the relations,
- only dependencies intended by the schema are assumed,
- descriptive fields such as `reviewer_name` and `vet_name` are treated as ordinary attributes in this project version rather than references to separate entities,
- unless explicitly stated, no additional uniqueness constraints are assumed for attributes such as email or phone number.

Under these assumptions, the following dependencies characterize the relations and support the normalization discussion required by the project brief.

## 7.1.1 Implementation Alignment Note (April 23, 2026)

The current repository implementation keeps the ER design, entity set, table set, attributes, and primary/foreign-key relationships unchanged. The delivered SQLite implementation adds only non-structural hardening that is consistent with this design:

- `CHECK` constraints for documented controlled domains such as pet status and application status,
- same-row temporal `CHECK` constraints such as birth date before intake date,
- `UNIQUE` on `AdoptionRecord.application_id`, which matches FR-14 and the documented 1:0..1 relationship,
- runtime validation and audits for cross-table rules that cannot be expressed directly as SQLite `CHECK` constraints,
- no new uniqueness assumptions for applicant or volunteer email addresses.

SQLite is the official execution target for this repository version. The SQL deliverables in `src/queries/` are therefore written directly in SQLite syntax rather than relying on runtime dialect translation.

---

## 7.2 Functional Dependencies by Relation

### 7.2.1 Shelter

Shelter(*shelter_id*​, name,address, phone,capacity)
Functional dependencies:

- `shelter_id -> name, address, phone, capacity`

Candidate key:

- `{shelter_id}`

No other nontrivial functional dependency is assumed.

---

### 7.2.2 Pet

Pet(*pet_id*, shelter_id, name, species, breed, sex, color, estimated_birth_date, intake_date, status, is_sterilized, special_needs)

Functional dependencies:

- `pet_id -> shelter_id, name, species, breed, sex, color, estimated_birth_date, intake_date, status, is_sterilized, special_needs`

Candidate key:

- `{pet_id}`

No other nontrivial functional dependency is assumed.

---

### 7.2.3 Applicant

Applicant(*applicant_id*​, full_name, phone, email, address, housing_type, has_pet_experience, created_at)

Functional dependencies:

- `applicant_id -> full_name, phone, email, address, housing_type, has_pet_experience, created_at`

Candidate key:

- `{applicant_id}`

No other nontrivial functional dependency is assumed.

---

### 7.2.4 AdoptionApplication

AdoptionApplication(*application_id*​, applicant_id, pet_id, application_date, status, reason, reviewed_date, reviewer_name, decision_note)

Functional dependencies:

- `application_id -> applicant_id, pet_id, application_date, status, reason, reviewed_date, reviewer_name, decision_note`

Candidate key:

- `{application_id}`

No other nontrivial functional dependency is assumed in the baseline design.

---

### 7.2.5 AdoptionRecord

AdoptionRecord(*adoption_id​*, application_id, adoption_date, final_adoption_fee, handover_note)

Functional dependencies:

- `adoption_id -> application_id, adoption_date, final_adoption_fee, handover_note`
- `application_id -> adoption_id, adoption_date, final_adoption_fee, handover_note`

Explanation:  
The second dependency holds because `application_id` is required to be **UNIQUE** in `AdoptionRecord`, reflecting the business rule that one application can generate at most one adoption record.

Candidate keys:

- `{adoption_id}`
- `{application_id}`

This relation therefore has two candidate keys in the optimized design.

---

### 7.2.6 FollowUp

FollowUp(*followup_id*​, adoption_id, followup_date, followup_type, pet_condition, adopter_feedback, result_status, staff_note)

Functional dependencies:

- `followup_id -> adoption_id, followup_date, followup_type, pet_condition, adopter_feedback, result_status, staff_note`

Candidate key:

- `{followup_id}`

No other nontrivial functional dependency is assumed.

---

### 7.2.7 MedicalRecord

MedicalRecord(*record_id​*, pet_id, visit_date, record_type, diagnosis, treatment, vet_name,  notes)

Functional dependencies:

- `record_id -> pet_id, visit_date, record_type, diagnosis, treatment, vet_name, notes`

Candidate key:

- `{record_id}`

No other nontrivial functional dependency is assumed.

---

### 7.2.8 Vaccination

Vaccination(*vaccination_id*​, pet_id, vaccine_name, dose_no, vaccination_date, next_due_date, vet_name, notes)

Functional dependencies:

- `vaccination_id -> pet_id, vaccine_name, dose_no, vaccination_date, next_due_date, vet_name, notes`

Candidate key:

- `{vaccination_id}`

No other nontrivial functional dependency is assumed in the baseline design.

---

### 7.2.9 Volunteer

Volunteer(volunteer_id​, shelter_id, full_name, phone,email, join_date, availability_note)

Functional dependencies:

- `volunteer_id -> shelter_id, full_name, phone, email, join_date, availability_note`

Candidate key:

- `{volunteer_id}`

No other nontrivial functional dependency is assumed.

---

### 7.2.10 CareAssignment

CareAssignment(*assignment_id​*, volunteer_id, pet_id, assignment_date, shift, task_type, status, notes)

Functional dependencies:

- `assignment_id -> volunteer_id, pet_id, assignment_date, shift, task_type, status, notes`

Candidate key:

- `{assignment_id}`

No other nontrivial functional dependency is required in the baseline version.

---

## 7.3 Optional Stronger Assumptions 

We can also choose to enforce stricter business constraints, then additional functional dependencies may arise:

- if each applicant email must be unique, then `email -> applicant_id, full_name, phone, address, housing_type, has_pet_experience, created_at`;
- if each volunteer email must be unique, then `email -> volunteer_id, shelter_id, full_name, phone, join_date, availability_note`;
- if each care assignment is unique for a given `(volunteer_id, pet_id, assignment_date, shift)`, then  
    `(volunteer_id, pet_id, assignment_date, shift) -> task_type, status, notes`.

---
## 7.4 Normalization Analysis Based on the Functional Dependencies

Under the functional dependencies listed above, each relation is designed so that the primary determinant is a candidate key, and no intended non-key attribute depends on another non-key attribute within the same relation. In particular:

- historical multi-valued information is decomposed into separate relations,
- the many-to-many relationship between volunteers and pets is resolved by `CareAssignment`,
- the adoption workflow is normalized by separating `AdoptionApplication` from `AdoptionRecord`,
- follow-up data depends on a confirmed adoption event rather than on an application request.

Therefore, under the stated assumptions, the schema is well aligned with a **3NF-style design**, and several relations are in fact close to **BCNF** under the baseline dependency set.

