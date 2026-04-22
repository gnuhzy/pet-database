# Workflow SQL Examples

These examples document the write-side business workflows used by the web API.
They are **not** part of the LLM/MCP query registry and are not exposed through
`/api/llm-query`.

## Approve an adoption application

The official path is `PATCH /api/applications/{id}/review`. The workflow updates
the application, inserts the final adoption record if needed, and closes other
pending applications for the same pet in one transaction.

```sql
UPDATE ADOPTION_APPLICATION
SET status = 'Approved',
    reviewed_date = '2026-04-23',
    reviewer_name = 'Staff Reviewer',
    decision_note = 'Applicant meets the adoption requirements.'
WHERE application_id = 3
  AND status = 'Under Review';

INSERT INTO ADOPTION_RECORD (
    adoption_id,
    application_id,
    adoption_date,
    final_adoption_fee,
    handover_note
) VALUES (
    7,
    3,
    '2026-04-23',
    120.00,
    'Handover completed after approval.'
);
```

## Add a post-adoption follow-up

The official path is `POST /api/follow-ups`. The workflow records a follow-up
only for an existing adoption record and validates that the follow-up date is
not earlier than the adoption date.

```sql
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
    17,
    2,
    '2026-04-23',
    'Phone Check',
    'Healthy and energetic',
    'The pet has adapted well to the new routine.',
    'Good',
    'No immediate concerns reported.'
);
```
