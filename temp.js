
const API_BASE = (() => {
  if (window.PAWTRACK_API_BASE) return window.PAWTRACK_API_BASE;
  const protocol = window.location.protocol;
  const host = window.location.host;
  const sameOriginApiHosts = new Set(['127.0.0.1:8000', 'localhost:8000']);
  const isStandardWebOrigin = protocol === 'http:' || protocol === 'https:';
  if (isStandardWebOrigin && sameOriginApiHosts.has(host)) {
    return '';
  }
  return 'http://127.0.0.1:8000';
})();

let pets = [];
let apps = [];
let applicants = [];
let shelters = [];
let adoptionRecords = [];
let followUps = [];
let medicalRecords = [];
let vaccinations = [];
let volunteers = [];
let careAssignments = [];
let analytics = null;
let llmBonus = null;
let dashboard = null;
let reviewingIndex = -1;
let crudContext = null;
let selectedActivityTypes = null;
const APP_TIMEZONE = 'Asia/Shanghai';
const HOUSING_TYPES = ['Apartment','Condo','House','Townhouse','House with garden','House without garden','Shared housing'];
const ACTIVITY_TYPE_ORDER = ['adoption','application_review','application','applicant','medical','vaccination','care_assignment','follow_up','volunteer','pet_intake'];

const crudConfigs = {
  'shelters': {
    label: 'Shelter',
    endpoint: '/api/shelters',
    idField: 'shelterId',
    data: () => shelters,
    fields: [
      {name:'name', label:'Name', required:true},
      {name:'address', label:'Address'},
      {name:'phone', label:'Phone'},
      {name:'capacity', label:'Capacity', type:'number', required:true}
    ]
  },
  'pets': {
    label: 'Pet',
    endpoint: '/api/pets',
    idField: 'petId',
    data: () => pets,
    fields: [
      {name:'shelterId', label:'Shelter', type:'select', required:true, options: () => shelters.map(s => ({value:s.shelterId, label:`${s.id} - ${s.name}`}))},
      {name:'name', label:'Name', required:true},
      {name:'species', label:'Species', type:'select', required:true, options: () => ['Dog','Cat','Rabbit','Bird'].map(v => ({value:v, label:v}))},
      {name:'breed', label:'Breed'},
      {name:'sex', label:'Sex', type:'select', options: () => ['Male','Female','Unknown'].map(v => ({value:v, label:v}))},
      {name:'color', label:'Color'},
      {name:'birth', label:'Estimated birth date', type:'date'},
      {name:'intake', label:'Intake date', type:'date', required:true, defaultValue: todayIso},
      {name:'status', label:'Status', type:'select', required:true, options: petStatusOptions},
      {name:'sterilized', label:'Sterilized', type:'bool'},
      {name:'special', label:'Special needs', type:'textarea', wide:true}
    ]
  },
  'applicants': {
    label: 'Applicant',
    endpoint: '/api/applicants',
    idField: 'applicantId',
    data: () => applicants,
    fields: [
      {name:'name', label:'Full name', required:true},
      {name:'phone', label:'Phone'},
      {name:'email', label:'Email', type:'email'},
      {name:'address', label:'Address', type:'textarea', wide:true},
      {name:'housingType', label:'Housing type', type:'select', options: housingTypeOptions},
      {name:'hasPetExperience', label:'Has pet experience', type:'bool'},
      {name:'createdAt', label:'Created at', type:'date', defaultValue: todayIso}
    ]
  },
  'medical-records': {
    label: 'Medical record',
    endpoint: '/api/medical-records',
    idField: 'recordId',
    data: () => medicalRecords,
    fields: [
      {name:'petId', label:'Pet', type:'select', required:true, options: petOptions},
      {name:'date', label:'Visit date', type:'date', required:true, defaultValue: todayIso},
      {name:'type', label:'Record type', type:'select', options: () => ['Check-up','Surgery','Injury','Dental','Treatment'].map(v => ({value:v, label:v}))},
      {name:'vet', label:'Vet name'},
      {name:'diagnosis', label:'Diagnosis', type:'textarea', wide:true},
      {name:'treatment', label:'Treatment', type:'textarea', wide:true},
      {name:'notes', label:'Notes', type:'textarea', wide:true}
    ]
  },
  'vaccinations': {
    label: 'Vaccination',
    endpoint: '/api/vaccinations',
    idField: 'vaccinationId',
    data: () => vaccinations,
    fields: [
      {name:'petId', label:'Pet', type:'select', required:true, options: petOptions},
      {name:'vaccine', label:'Vaccine name', required:true},
      {name:'doseNo', label:'Dose no.', type:'number'},
      {name:'vaccinationDate', label:'Vaccination date', type:'date', required:true, defaultValue: todayIso},
      {name:'dueDate', label:'Next due date', type:'date'},
      {name:'vet', label:'Vet name'},
      {name:'notes', label:'Notes', type:'textarea', wide:true}
    ]
  },
  'volunteers': {
    label: 'Volunteer',
    endpoint: '/api/volunteers',
    idField: 'volunteerId',
    data: () => volunteers,
    fields: [
      {name:'shelterId', label:'Shelter', type:'select', required:true, options: () => shelters.map(s => ({value:s.shelterId, label:`${s.id} - ${s.name}`}))},
      {name:'name', label:'Full name', required:true},
      {name:'phone', label:'Phone'},
      {name:'email', label:'Email', type:'email'},
      {name:'joined', label:'Join date', type:'date', defaultValue: todayIso},
      {name:'availability', label:'Availability note', type:'textarea', wide:true}
    ]
  },
  'care-assignments': {
    label: 'Care assignment',
    endpoint: '/api/care-assignments',
    idField: 'assignmentId',
    data: () => careAssignments,
    fields: [
      {name:'volunteerId', label:'Volunteer', type:'select', required:true, options: careVolunteerOptions},
      {name:'petId', label:'Pet', type:'select', required:true, options: petOptions},
      {name:'date', label:'Assignment date', type:'date', required:true, defaultValue: todayIso},
      {name:'shift', label:'Shift', type:'select', required:true, options: () => ['Morning','Afternoon','Evening'].map(v => ({value:v, label:v}))},
      {name:'task', label:'Task type', type:'select', required:true, options: () => ['Feeding','Cleaning','Walking','Grooming','Socializing','Medical support'].map(v => ({value:v, label:v}))},
      {name:'status', label:'Status', type:'select', required:true, options: () => ['Scheduled','Completed','Cancelled'].map(v => ({value:v, label:v}))},
      {name:'notes', label:'Notes', type:'textarea', wide:true}
    ]
  },
  'follow-ups': {
    label: 'Follow-up',
    endpoint: '/api/follow-ups',
    idField: 'followupId',
    data: () => followUps,
    fields: [
      {name:'adoptionId', label:'Adoption record', type:'select', required:true, options: () => adoptionRecords.map(r => ({value:r.adoptionId, label:`${r.id} - ${r.pet} / ${r.applicant}`}))},
      {name:'followupDate', label:'Follow-up date', type:'date', required:true, defaultValue: todayIso},
      {name:'followupType', label:'Follow-up type', type:'select', required:true, options: () => ['Phone Check','Home Visit','Vet Check'].map(v => ({value:v, label:v}))},
      {name:'petCondition', label:'Pet condition'},
      {name:'adopterFeedback', label:'Adopter feedback', type:'textarea', wide:true},
      {name:'resultStatus', label:'Result status', type:'select', required:true, options: () => ['Excellent','Good','Satisfactory','Needs Improvement'].map(v => ({value:v, label:v}))},
      {name:'staffNote', label:'Staff note', type:'textarea', wide:true}
    ]
  }
};

function statusBadge(s) {
  const m = {
    'Available':'badge-available',
    'Reserved':'badge-reserved',
    'Adopted':'badge-adopted',
    'Medical hold':'badge-hold',
    'Pending':'badge-pending',
    'Approved':'badge-approved',
    'Rejected':'badge-rejected',
    'Completed':'badge-approved',
    'Scheduled':'badge-pending',
    'Cancelled':'badge-rejected',
    'Active':'badge-active',
    'Inactive':'badge-inactive',
    'Pass':'badge-approved',
    'Review':'badge-pending',
    'Excellent':'badge-approved',
    'Good':'badge-active',
    'Satisfactory':'badge-active',
    'Needs attention':'badge-pending',
    'Needs Improvement':'badge-pending',
    'Yes':'badge-approved',
    'No':'badge-inactive'
  };
  return `<span class="badge ${m[s]||''}">${escapeHtml(s)}</span>`;
}

function showToast(msg, type='success') {
  const t = document.getElementById('toast');
  t.textContent = msg;
  t.className = 'toast show toast-' + type;
  setTimeout(() => t.className = 'toast', 2800);
}

function showPage(id, el) {
  document.querySelectorAll('.page').forEach(p => p.classList.remove('active'));
  document.querySelectorAll('.nav-item').forEach(n => n.classList.remove('active'));
  document.getElementById('page-' + id).classList.add('active');
  el.classList.add('active');
}

function closeOverlay(id) { document.getElementById(id).classList.remove('open'); }

function escapeHtml(value) {
  const div = document.createElement('div');
  div.textContent = value == null || value === '' ? '-' : String(value);
  return div.innerHTML;
}

function escapeFormValue(value) {
  const div = document.createElement('div');
  div.textContent = value == null ? '' : String(value);
  return div.innerHTML;
}

function entityCode(prefix, value) {
  return value ? `${prefix}-${String(value).padStart(3, '0')}` : '';
}

function zonedDateParts(baseDate = new Date()) {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: APP_TIMEZONE,
    year: 'numeric',
    month: '2-digit',
    day: '2-digit'
  }).formatToParts(baseDate);
  return {
    year: Number(parts.find(p => p.type === 'year')?.value || 0),
    month: Number(parts.find(p => p.type === 'month')?.value || 0),
    day: Number(parts.find(p => p.type === 'day')?.value || 0)
  };
}

function formatDateParts(parts) {
  return `${String(parts.year).padStart(4, '0')}-${String(parts.month).padStart(2, '0')}-${String(parts.day).padStart(2, '0')}`;
}

function todayIso() {
  return formatDateParts(zonedDateParts());
}

function housingTypeOptions() {
  return HOUSING_TYPES.map(v => ({value:v, label:v}));
}

function activityTypeLabel(type) {
  const labels = {
    adoption: 'Adoption',
    application_review: 'Review',
    application: 'Application',
    applicant: 'Applicant',
    medical: 'Medical',
    vaccination: 'Vaccination',
    care_assignment: 'Assignment',
    follow_up: 'Follow-up',
    volunteer: 'Volunteer',
    pet_intake: 'Pet intake'
  };
  return labels[type] || String(type || 'Activity').replace(/_/g, ' ');
}

function activityTypeEntries(activities) {
  const counts = new Map();
  activities.forEach(activity => {
    const type = activity.eventType || 'activity';
    counts.set(type, (counts.get(type) || 0) + 1);
  });
  return [...counts.entries()]
    .map(([type, count]) => ({type, count}))
    .sort((a, b) => {
      const leftIndex = ACTIVITY_TYPE_ORDER.indexOf(a.type);
      const rightIndex = ACTIVITY_TYPE_ORDER.indexOf(b.type);
      if (leftIndex !== -1 || rightIndex !== -1) {
        return (leftIndex === -1 ? Number.MAX_SAFE_INTEGER : leftIndex)
          - (rightIndex === -1 ? Number.MAX_SAFE_INTEGER : rightIndex);
      }
      return activityTypeLabel(a.type).localeCompare(activityTypeLabel(b.type));
    });
}

function normalizeSelectedActivityTypes(activities) {
  if (!(selectedActivityTypes instanceof Set)) return;
  const availableTypes = new Set(activityTypeEntries(activities).map(entry => entry.type));
  selectedActivityTypes = new Set([...selectedActivityTypes].filter(type => availableTypes.has(type)));
  if (selectedActivityTypes.size === 0) {
    selectedActivityTypes = null;
  }
}

function filteredActivities(activities) {
  normalizeSelectedActivityTypes(activities);
  if (!(selectedActivityTypes instanceof Set)) return activities;
  return activities.filter(activity => selectedActivityTypes.has(activity.eventType || 'activity'));
}

function toggleActivityType(type) {
  const activities = dashboard?.activities || [];
  const availableTypes = activityTypeEntries(activities).map(entry => entry.type);
  if (type === '__all__') {
    selectedActivityTypes = null;
    renderDashboard();
    return;
  }
  if (!availableTypes.includes(type)) return;
  if (!(selectedActivityTypes instanceof Set)) {
    selectedActivityTypes = new Set([type]);
  } else {
    const next = new Set(selectedActivityTypes);
    if (next.has(type)) {
      next.delete(type);
    } else {
      next.add(type);
    }
    selectedActivityTypes = next.size ? next : null;
  }
  renderDashboard();
}

function setHousingTypeSelectValue(selectEl, value = '') {
  if (!selectEl) return;
  selectEl.innerHTML = '<option value="">Select housing type...</option>' +
    HOUSING_TYPES.map(type => `<option value="${escapeFormValue(type)}">${escapeHtml(type)}</option>`).join('');
  selectEl.value = value && HOUSING_TYPES.includes(value) ? value : '';
}

function isoDateToUtcMs(dateText) {
  const match = /^(\d{4})-(\d{2})-(\d{2})$/.exec(String(dateText || ''));
  if (!match) return NaN;
  return Date.UTC(Number(match[1]), Number(match[2]) - 1, Number(match[3]));
}

function petOptions() {
  return pets.map(p => ({value:p.petId, label:`${p.id} - ${p.name}${p.shelter ? ` (${p.shelter})` : ''}`}));
}

function careVolunteerOptions() {
  return volunteers.map(v => ({value:v.volunteerId, label:`${v.id} - ${v.name}${v.shelter ? ` (${v.shelter})` : ''}`}));
}

function petById(id) {
  return pets.find(p => Number(p.petId) === Number(id));
}

function volunteerById(id) {
  return volunteers.find(v => Number(v.volunteerId) === Number(id));
}

function approvedApplicationsForPet(petId, excludeApplicationId=null) {
  return apps.filter(a =>
    Number(a.petId) === Number(petId)
    && a.rawStatus === 'Approved'
    && Number(a.applicationId) !== Number(excludeApplicationId)
  );
}

function pendingApplicationsForPet(petId, excludeApplicationId=null) {
  return apps.filter(a =>
    Number(a.petId) === Number(petId)
    && a.rawStatus === 'Under Review'
    && Number(a.applicationId) !== Number(excludeApplicationId)
  );
}

function earliestAdoptionDateForPet(petId) {
  const dates = adoptionRecords
    .filter(r => Number(r.petId) === Number(petId) && r.adoptionDate)
    .map(r => r.adoptionDate)
    .sort();
  return dates[0] || '';
}

function petStatusOptions(item) {
  if (!item) {
    return ['Available','Medical hold'].map(v => ({value:v, label:v}));
  }
  const pending = pendingApplicationsForPet(item.petId, item.applicationId).length > 0;
  const approved = approvedApplicationsForPet(item.petId, item.applicationId).length > 0;
  if (pending) return ['Reserved'].map(v => ({value:v, label:v}));
  if (approved) return ['Adopted'].map(v => ({value:v, label:v}));
  return ['Available','Medical hold'].map(v => ({value:v, label:v}));
}

function normalizePetStatusValue(value) {
  const normalized = String(value || '').trim().toLowerCase().replace(/\s+/g, '_');
  const map = {
    'available': 'available',
    'reserved': 'reserved',
    'adopted': 'adopted',
    'medical_hold': 'medical_hold'
  };
  return map[normalized] || normalized;
}

function firstDateConflict(entries, limitDate) {
  return entries
    .filter(([, value]) => value && value < limitDate)
    .sort((a, b) => a[1].localeCompare(b[1]))[0] || null;
}

function clientValidateCrudPayload(resource, payload) {
  const editingId = crudContext?.mode === 'edit' ? Number(crudContext.id) : null;

  if (resource === 'shelters' && editingId != null) {
    const activePets = pets.filter(p =>
      Number(p.shelterId) === editingId
      && ['available', 'reserved', 'medical_hold'].includes(p.rawStatus)
    ).length;
    if (payload.capacity != null && Number(payload.capacity) < activePets) {
      return 'Shelter capacity cannot be lower than its active pet count.';
    }
  }

  if (resource === 'pets') {
    const nextStatus = normalizePetStatusValue(payload.status);
    if (payload.birth && payload.intake && payload.birth > payload.intake) {
      return 'Estimated birth date cannot be after intake date.';
    }
    if (payload.intake && payload.intake > todayIso()) {
      return 'Pet intake date cannot be in the future.';
    }
    if (editingId == null) {
      if (nextStatus === 'reserved' || nextStatus === 'adopted') {
        return 'New pets can start only as Available or Medical hold.';
      }
      return null;
    }

    const pending = pendingApplicationsForPet(editingId).length > 0;
    const approved = approvedApplicationsForPet(editingId).length > 0;
    if (pending && nextStatus !== 'reserved') {
      return 'A pet with a pending application must stay Reserved.';
    }
    if (!pending && approved && nextStatus !== 'adopted') {
      return 'A pet with an approved adoption must stay Adopted.';
    }
    if (!pending && !approved && (nextStatus === 'reserved' || nextStatus === 'adopted')) {
      return 'Reserved and Adopted statuses must come from the adoption workflow, not direct edits.';
    }
    if (payload.intake) {
      const relatedConflict = firstDateConflict([
        ...apps.filter(a => Number(a.petId) === editingId).map(a => ['application', a.date]),
        ...adoptionRecords.filter(r => Number(r.petId) === editingId).map(r => ['adoption', r.adoptionDate]),
        ...medicalRecords.filter(r => Number(r.petId) === editingId).map(r => ['medical visit', r.date]),
        ...vaccinations.filter(v => Number(v.petId) === editingId).map(v => ['vaccination', v.vaccinationDate]),
        ...careAssignments.filter(c => Number(c.petId) === editingId).map(c => ['care assignment', c.date])
      ], payload.intake);
      if (relatedConflict) {
        return `Pet intake date cannot be later than an existing ${relatedConflict[0]} on ${relatedConflict[1]}.`;
      }
    }
    if (payload.shelterId) {
      const conflictingAssignment = careAssignments.find(c =>
        Number(c.petId) === editingId
        && Number(volunteerById(c.volunteerId)?.shelterId) !== Number(payload.shelterId)
      );
      if (conflictingAssignment) {
        return 'Pet shelter cannot be changed because existing care assignments would become cross-shelter.';
      }
    }
    return null;
  }

  if (resource === 'medical-records') {
    const pet = petById(payload.petId);
    if (pet && payload.date && pet.intake && payload.date < pet.intake) {
      return 'Medical visit date cannot be before pet intake date.';
    }
  }

  if (resource === 'vaccinations') {
    const pet = petById(payload.petId);
    if (pet && payload.vaccinationDate && pet.intake && payload.vaccinationDate < pet.intake) {
      return 'Vaccination date cannot be before pet intake date.';
    }
    if (payload.dueDate && payload.vaccinationDate && payload.dueDate < payload.vaccinationDate) {
      return 'Next due date cannot be before vaccination date.';
    }
  }

  if (resource === 'volunteers') {
    if (editingId != null && payload.joined) {
      const earlyAssignment = firstDateConflict(
        careAssignments
          .filter(c => Number(c.volunteerId) === editingId)
          .map(c => ['care assignment', c.date]),
        payload.joined
      );
      if (earlyAssignment) {
        return `Volunteer join date cannot be later than existing ${earlyAssignment[0]} on ${earlyAssignment[1]}.`;
      }
    }
    if (editingId != null && payload.shelterId) {
      const conflictingAssignment = careAssignments.find(c =>
        Number(c.volunteerId) === editingId
        && Number(petById(c.petId)?.shelterId) !== Number(payload.shelterId)
      );
      if (conflictingAssignment) {
        return 'Volunteer shelter cannot be changed because existing care assignments would become cross-shelter.';
      }
    }
  }

  if (resource === 'care-assignments') {
    const volunteer = volunteerById(payload.volunteerId);
    const pet = petById(payload.petId);
    if (volunteer && pet && Number(volunteer.shelterId) !== Number(pet.shelterId)) {
      return 'Volunteer and pet must belong to the same shelter for care assignments.';
    }
    if (pet && payload.date && pet.intake && payload.date < pet.intake) {
      return 'Care assignment date cannot be before pet intake date.';
    }
    if (volunteer && payload.date && volunteer.joined && payload.date < volunteer.joined) {
      return 'Care assignment date cannot be before the volunteer join date.';
    }
    const adoptionDate = earliestAdoptionDateForPet(payload.petId);
    if (adoptionDate && payload.date && payload.date >= adoptionDate && payload.status !== 'Cancelled') {
      return 'Adopted pets cannot receive scheduled care assignments on or after adoption date.';
    }
  }

  if (resource === 'follow-ups') {
    const adoption = adoptionRecords.find(r => Number(r.adoptionId) === Number(payload.adoptionId));
    if (adoption && payload.followupDate && adoption.adoptionDate && payload.followupDate < adoption.adoptionDate) {
      return 'Follow-up date cannot be before adoption date.';
    }
  }

  return null;
}

function clientDeleteGuard(resource, id) {
  if (resource === 'shelters') {
    if (pets.some(p => Number(p.shelterId) === Number(id)) || volunteers.some(v => Number(v.shelterId) === Number(id))) {
      return 'Shelters with linked pets or volunteers cannot be deleted.';
    }
  }
  if (resource === 'applicants') {
    if (apps.some(a => Number(a.applicantId) === Number(id))) {
      return 'Applicants with adoption applications cannot be deleted.';
    }
  }
  if (resource === 'pets') {
    if (
      apps.some(a => Number(a.petId) === Number(id))
      || medicalRecords.some(r => Number(r.petId) === Number(id))
      || vaccinations.some(v => Number(v.petId) === Number(id))
      || careAssignments.some(c => Number(c.petId) === Number(id))
    ) {
      return 'Pets with linked applications, medical records, vaccinations, or care assignments cannot be deleted.';
    }
  }
  if (resource === 'volunteers') {
    if (careAssignments.some(c => Number(c.volunteerId) === Number(id))) {
      return 'Volunteers with care assignments cannot be deleted.';
    }
  }
  return null;
}

function actionButtons(resource, id, includeView=false) {
  const viewButton = includeView ? `<button class="btn-sm" onclick="openPetDetailById(${id})">View</button>` : '';
  return `<div class="action-row">
    ${viewButton}
    <button class="btn-sm" onclick="openCrudModal('${resource}','edit',${id})">Edit</button>
    <button class="btn-reject" onclick="deleteCrudRecord('${resource}',${id})">Delete</button>
  </div>`;
}

function apiPath(path) {
  return API_BASE + path;
}

async function apiRequest(path, options={}) {
  const config = {
    headers: {'Content-Type':'application/json'},
    ...options
  };
  if (config.body && typeof config.body !== 'string') {
    config.body = JSON.stringify(config.body);
  }
  const res = await fetch(apiPath(path), config);
  const text = await res.text();
  const payload = text ? JSON.parse(text) : {};
  if (!res.ok) {
    throw new Error(payload.error || `Request failed with status ${res.status}`);
  }
  return payload;
}

function findCrudItem(resource, id) {
  const config = crudConfigs[resource];
  return config.data().find(item => Number(item[config.idField]) === Number(id));
}

function fieldValue(field, item) {
  if (item && item[field.name] != null) {
    const value = item[field.name];
    return field.type === 'date' && typeof value === 'string' ? value.slice(0, 10) : value;
  }
  if (typeof field.defaultValue === 'function') return field.defaultValue();
  return field.defaultValue ?? '';
}

function renderCrudField(field, item) {
  const value = fieldValue(field, item);
  const required = field.required ? ' required' : '';
  const groupClass = field.wide || field.type === 'textarea' ? 'form-group form-group-wide' : 'form-group';
  const label = `<label class="form-label">${escapeHtml(field.label)}${field.required ? ' *' : ''}</label>`;
  if (field.type === 'textarea') {
    return `<div class="${groupClass}">${label}<textarea class="form-control" id="crud-${field.name}"${required}>${escapeFormValue(value)}</textarea></div>`;
  }
  if (field.type === 'select') {
    const options = (field.options ? field.options(item, crudContext) : []).map(option => {
      const selected = String(option.value) === String(value) ? ' selected' : '';
      return `<option value="${escapeHtml(option.value)}"${selected}>${escapeHtml(option.label)}</option>`;
    }).join('');
    return `<div class="${groupClass}">${label}<select class="form-control" id="crud-${field.name}"${required}><option value="">Select...</option>${options}</select></div>`;
  }
  if (field.type === 'bool') {
    const selectedTrue = value === true || value === 'Yes' || value === 1 ? ' selected' : '';
    const selectedFalse = selectedTrue ? '' : ' selected';
    return `<div class="${groupClass}">${label}<select class="form-control" id="crud-${field.name}"><option value="true"${selectedTrue}>Yes</option><option value="false"${selectedFalse}>No</option></select></div>`;
  }
  const isDate = field.type === 'date';
  if (isDate) {
    const isFilled = value ? 'date' : 'text';
    return `<div class="${groupClass}">${label}<input class="form-control" id="crud-${field.name}" type="${isFilled}" placeholder="YYYY-MM-DD" onfocus="this.type='date'" onblur="if(!this.value) this.type='text'" value="${escapeFormValue(value)}"${required}></div>`;
  }
  const inputType = field.type === 'number' || field.type === 'email' ? field.type : 'text';
  return `<div class="${groupClass}">${label}<input class="form-control" id="crud-${field.name}" type="${inputType}" value="${escapeFormValue(value)}"${required}></div>`;
}

function openCrudModal(resource, mode, id=null) {
  const config = crudConfigs[resource];
  const item = mode === 'edit' ? findCrudItem(resource, id) : null;
  if (mode === 'edit' && !item) {
    showToast('Record not found', 'error');
    return;
  }
  crudContext = {resource, mode, id};
  document.getElementById('crud-title').textContent = `${mode === 'create' ? 'New' : 'Edit'} ${config.label}`;
  document.getElementById('crud-submit').textContent = mode === 'create' ? 'Create' : 'Save changes';
  document.getElementById('crud-fields').innerHTML = config.fields.map(field => renderCrudField(field, item)).join('');
  document.getElementById('crud-overlay').classList.add('open');
}

function readCrudPayload() {
  const config = crudConfigs[crudContext.resource];
  const payload = {};
  for (const field of config.fields) {
    const el = document.getElementById(`crud-${field.name}`);
    let value = el.value;
    if (field.type === 'number') value = value === '' ? null : Number(value);
    if (field.type === 'bool') value = value === 'true';
    payload[field.name] = value;
  }
  return payload;
}

async function submitCrudForm() {
  if (!crudContext) return;
  const config = crudConfigs[crudContext.resource];
  const method = crudContext.mode === 'create' ? 'POST' : 'PATCH';
  const path = crudContext.mode === 'create' ? config.endpoint : `${config.endpoint}/${crudContext.id}`;
  const payload = readCrudPayload();
  const clientError = clientValidateCrudPayload(crudContext.resource, payload);
  if (clientError) {
    showToast(clientError, 'error');
    return;
  }
  try {
    await apiRequest(path, {method, body: payload});
    closeOverlay('crud-overlay');
    await loadData();
    showToast(`${config.label} ${crudContext.mode === 'create' ? 'created' : 'updated'}`, 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function deleteCrudRecord(resource, id) {
  const config = crudConfigs[resource];
  const item = findCrudItem(resource, id);
  const label = item?.name || item?.id || config.label;
  const blockedReason = clientDeleteGuard(resource, id);
  if (blockedReason) {
    showToast(blockedReason, 'error');
    return;
  }
  if (!window.confirm(`Delete ${label}?`)) return;
  try {
    await apiRequest(`${config.endpoint}/${id}`, {method: 'DELETE'});
    await loadData();
    showToast(`${config.label} deleted`, 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
}

async function loadData() {
  const [
    dashboardData,
    shelterData,
    petsData,
    applicantsData,
    applicationsData,
    adoptionRecordData,
    followupData,
    medicalData,
    vaccinationData,
    volunteerData,
    assignmentData,
    analyticsData,
    llmBonusData
  ] = await Promise.all([
    apiRequest('/api/dashboard'),
    apiRequest('/api/shelters'),
    apiRequest('/api/pets'),
    apiRequest('/api/applicants'),
    apiRequest('/api/applications'),
    apiRequest('/api/adoption-records'),
    apiRequest('/api/follow-ups'),
    apiRequest('/api/medical-records'),
    apiRequest('/api/vaccinations'),
    apiRequest('/api/volunteers'),
    apiRequest('/api/care-assignments'),
    apiRequest('/api/analytics'),
    apiRequest('/api/llm-bonus')
  ]);

  dashboard = dashboardData;
  shelters = shelterData.shelters || [];
  pets = petsData.pets || [];
  applicants = applicantsData.applicants || [];
  apps = applicationsData.applications || [];
  adoptionRecords = adoptionRecordData.adoptionRecords || [];
  followUps = followupData.followUps || [];
  medicalRecords = medicalData.medicalRecords || [];
  vaccinations = vaccinationData.vaccinations || [];
  volunteers = volunteerData.volunteers || [];
  careAssignments = assignmentData.careAssignments || [];
  analytics = analyticsData;
  llmBonus = llmBonusData;

  populateSpeciesFilter();
  renderDashboard();
  renderShelters();
  filterPets();
  filterApplicants();
  filterApps();
  renderAdoptions();
  renderMedical();
  renderVolunteers();
  renderAnalytics();
  renderLlmBonus();
}

function renderDashboard() {
  const stats = dashboard?.stats || {};
  document.getElementById('dash-total-pets').textContent = stats.totalPets ?? '--';
  document.getElementById('dash-shelter-count').textContent = `in ${stats.shelterCount ?? 0} shelters`;
  document.getElementById('dash-available-count').textContent = stats.availablePets ?? '--';
  document.getElementById('dash-pending-count').textContent = stats.pendingApplications ?? '--';
  document.getElementById('dash-monthly-adoptions').textContent = stats.monthlyAdoptions ?? '--';

  const statusTb = document.getElementById('status-overview-tbody');
  const statuses = dashboard?.statusOverview || [];
  statusTb.innerHTML = statuses.length ? statuses.map(row => `<tr>
    <td>${statusBadge(row.status)}</td>
    <td>${escapeHtml(row.count)}</td>
    <td>${escapeHtml(row.share)}%</td>
  </tr>`).join('') : '<tr><td colspan="3" style="color:var(--color-text-secondary)">No status data</td></tr>';

  const summary = document.getElementById('activity-summary');
  const filterBar = document.getElementById('activity-filter-bar');
  const feed = document.getElementById('activity-feed');
  const activities = dashboard?.activities || [];
  const filtered = filteredActivities(activities);
  const typeEntries = activityTypeEntries(activities);
  const timezone = dashboard?.timezone || APP_TIMEZONE;
  summary.textContent = activities.length
    ? `${filtered.length} of ${activities.length} events shown`
    : 'No activity yet';
  filterBar.innerHTML = activities.length ? [
    `<button class="activity-filter-chip${selectedActivityTypes instanceof Set ? '' : ' active'}" onclick="toggleActivityType('__all__')">All <span class="activity-filter-count">${escapeHtml(activities.length)}</span></button>`,
    ...typeEntries.map(entry => `<button class="activity-filter-chip${selectedActivityTypes instanceof Set && selectedActivityTypes.has(entry.type) ? ' active' : ''}" onclick="toggleActivityType('${escapeHtml(entry.type)}')">${escapeHtml(activityTypeLabel(entry.type))} <span class="activity-filter-count">${escapeHtml(entry.count)}</span></button>`)
  ].join('') : '';
  feed.innerHTML = filtered.length ? filtered.map(a => `<div class="activity-item">
    <div class="activity-dot ${escapeHtml(a.dotClass)}"></div>
    <div>
      <div class="activity-text">${escapeHtml(a.text)}</div>
      <div class="activity-meta">
        <span class="activity-type">${escapeHtml(activityTypeLabel(a.eventType || 'activity'))}</span>
        <div class="activity-time">${escapeHtml(a.time)} · ${escapeHtml(timezone)}</div>
      </div>
    </div>
  </div>`).join('') : '<div class="activity-empty">No activity matches the current filter.</div>';
}

function renderShelters() {
  document.getElementById('shelter-tbody').innerHTML = renderTableRows(
    shelters,
    9,
    s => `<tr>
      <td style="color:var(--color-text-secondary)">${escapeHtml(s.id)}</td>
      <td style="font-weight:500">${escapeHtml(s.name)}</td>
      <td>${escapeHtml(s.address)}</td>
      <td>${escapeHtml(s.phone)}</td>
      <td>${escapeHtml(s.capacity)}</td>
      <td>${escapeHtml(s.currentPetCount)}</td>
      <td>${escapeHtml(s.volunteerCount)}</td>
      <td>${escapeHtml(formatPercent(s.occupancyRate))}</td>
      <td>${actionButtons('shelters', s.shelterId)}</td>
    </tr>`
  );


}


function filterApplicants() {
  const q = document.getElementById('applicant-search').value.toLowerCase();
  const experience = document.getElementById('applicant-experience-filter').value;
  renderApplicants(applicants.filter(a => {
    const searchable = [a.id, a.name, a.phone, a.email, a.address, a.housingType].join(' ').toLowerCase();
    const matchesExperience = !experience
      || (experience === 'yes' && a.hasPetExperience)
      || (experience === 'no' && !a.hasPetExperience);
    return (!q || searchable.includes(q)) && matchesExperience;
  }));
}

function renderApplicants(data) {
  document.getElementById('applicant-tbody').innerHTML = renderTableRows(
    data,
    9,
    a => `<tr>
      <td style="color:var(--color-text-secondary)">${escapeHtml(a.id)}</td>
      <td style="font-weight:500">${escapeHtml(a.name)}</td>
      <td>${escapeHtml(a.phone)}</td>
      <td>${escapeHtml(a.email)}</td>
      <td class="note-cell">${escapeHtml(a.address)}</td>
      <td>${escapeHtml(a.housingType)}</td>
      <td>${statusBadge(a.hasPetExperience ? 'Yes' : 'No')}</td>
      <td style="color:var(--color-text-secondary)">${escapeHtml(a.createdAt)}</td>
      <td>${actionButtons('applicants', a.applicantId)}</td>
    </tr>`
  );


}


function renderAdoptions() {
  document.getElementById('adoption-record-tbody').innerHTML = renderTableRows(
    adoptionRecords,
    8,
    r => `<tr>
      <td style="color:var(--color-text-secondary)">${escapeHtml(r.id)}</td>
      <td>${escapeHtml(r.applicationCode)}</td>
      <td style="font-weight:500">${escapeHtml(r.applicant)}<div class="muted-text">${escapeHtml(entityCode('A', r.applicantId))}</div></td>
      <td>${escapeHtml(r.pet)} <span class="muted-text">${escapeHtml(entityCode('P', r.petId))} ${escapeHtml(r.petSpecies)}</span></td>
      <td style="color:var(--color-text-secondary)">${escapeHtml(r.adoptionDate)}</td>
      <td>${escapeHtml(formatMoney(r.finalAdoptionFee))}</td>
      <td class="note-cell">${escapeHtml(r.handoverNote)}</td>
      <td>${escapeHtml(r.followupCount)}${r.lastFollowupDate ? `<div class="muted-text">last ${escapeHtml(r.lastFollowupDate)}</div>` : ''}</td>
    </tr>`
  );

  document.getElementById('followup-tbody').innerHTML = renderTableRows(
    followUps,
    9,
    f => `<tr>
      <td style="color:var(--color-text-secondary)">${escapeHtml(f.id)}</td>
      <td>${escapeHtml(f.adoptionCode)}</td>
      <td style="color:var(--color-text-secondary)">${escapeHtml(f.followupDate)}</td>
      <td>${escapeHtml(f.followupType)}</td>
      <td class="note-cell">${escapeHtml(f.petCondition)}</td>
      <td class="note-cell">${escapeHtml(f.adopterFeedback)}</td>
      <td>${statusBadge(f.resultStatus)}</td>
      <td class="note-cell">${escapeHtml(f.staffNote)}</td>
      <td>${actionButtons('follow-ups', f.followupId)}</td>
    </tr>`
  );


}


function populateSpeciesFilter() {
  const sel = document.getElementById('pet-species-filter');
  const current = sel.value;
  const species = [...new Set(pets.map(p => p.species).filter(Boolean))].sort();
  sel.innerHTML = '<option value="">All species</option>' + species.map(s => `<option>${escapeHtml(s)}</option>`).join('');
  sel.value = species.includes(current) ? current : '';
}

function renderPets(data) {
  const tb = document.getElementById('pet-tbody');
  if (!data.length) { tb.innerHTML = `<tr><td colspan="8" style="text-align:center;padding:3rem 1rem;">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" style="opacity:0.4; margin-bottom:12px; color:var(--color-primary)">
          <circle cx="12" cy="12" r="10"></circle><path d="M16 16s-1.5-2-4-2-4 2-4 2"></path><line x1="9" y1="9" x2="9.01" y2="9"></line><line x1="15" y1="9" x2="15.01" y2="9"></line>
        </svg>
        <div style="font-size:15px;font-weight:600;color:var(--color-text-secondary);margin-bottom:4px">No pets</div>
        <div style="font-size:13px;color:var(--color-text-tertiary)">We couldn\'t find any pets matching your criteria.</div>
      </td></tr>`; return; }
  tb.innerHTML = data.map(p => `<tr>
    <td style="color:var(--color-text-secondary)">${escapeHtml(p.id)}</td>
    <td style="font-weight:500">${escapeHtml(p.name)}</td>
    <td>${escapeHtml(p.species)}</td><td>${escapeHtml(p.breed)}</td><td>${escapeHtml(p.sex)}</td>
    <td>${statusBadge(p.status)}</td>
    <td style="color:var(--color-text-secondary)">${escapeHtml(p.intake)}</td>
    <td>${actionButtons('pets', p.petId, true)}</td>
  </tr>`).join('');
}

function filterPets() {
  const q = document.getElementById('pet-search').value.toLowerCase();
  const st = document.getElementById('pet-status-filter').value;
  const sp = document.getElementById('pet-species-filter').value;
  renderPets(pets.filter(p => {
    const searchable = [p.id, p.name, p.breed, p.species].join(' ').toLowerCase();
    return (!q || searchable.includes(q)) && (!st || p.status === st) && (!sp || p.species === sp);
  }));
}

function openPetDetail(i) {
  const p = pets[i];
  if (!p) return;
  document.getElementById('modal-pet-name').textContent = p.name;
  document.getElementById('modal-pet-fields').innerHTML = [
    ['ID',p.id],['Species',p.species],['Breed',p.breed],['Sex',p.sex],
    ['Color',p.color],['Est. birth date',p.birth],['Intake date',p.intake],
    ['Status',p.status],['Sterilized',p.sterilized],['Special needs',p.special],
    ['Shelter ID',p.shelterId ? `S-${String(p.shelterId).padStart(3,'0')}` : ''],
    ['Shelter',p.shelter]
  ].map(([l,v]) => `<div class="field-row"><span class="field-label">${escapeHtml(l)}</span><span>${escapeHtml(v)}</span></div>`).join('');
  document.getElementById('pet-detail-overlay').classList.add('open');
}

function openPetDetailById(id) {
  openPetDetail(pets.findIndex(p => Number(p.petId) === Number(id)));
}

function renderApps(data) {
  const tb = document.getElementById('app-tbody');
  if (!data.length) { tb.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:3rem 1rem;">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" style="opacity:0.4; margin-bottom:12px; color:var(--color-primary)">
          <circle cx="12" cy="12" r="10"></circle><path d="M16 16s-1.5-2-4-2-4 2-4 2"></path><line x1="9" y1="9" x2="9.01" y2="9"></line><line x1="15" y1="9" x2="15.01" y2="9"></line>
        </svg>
        <div style="font-size:15px;font-weight:600;color:var(--color-text-secondary);margin-bottom:4px">No applications</div>
        <div style="font-size:13px;color:var(--color-text-tertiary)">We couldn\'t find any applications matching your criteria.</div>
      </td></tr>`; return; }
  tb.innerHTML = data.map(a => {
    const gi = apps.indexOf(a);
    const approvalLocked = a.rawStatus === 'Under Review' && approvedApplicationsForPet(a.petId, a.applicationId).length > 0;
    const actions = a.rawStatus === 'Under Review'
      ? approvalLocked
        ? `<div style="display:flex;gap:6px;align-items:center"><button class="btn-sm" onclick="openAppDetail(${gi})">View</button><span class="muted-text">Approval locked</span></div>`
        : `<div style="display:flex;gap:6px"><button class="btn-sm" onclick="openAppDetail(${gi})">View</button><button class="btn-approve" onclick="openReview(${gi})">Review</button></div>`
      : `<button class="btn-sm" onclick="openAppDetail(${gi})">View</button>`;
    return `<tr>
      <td style="color:var(--color-text-secondary)">${escapeHtml(a.id)}</td>
      <td style="font-weight:500">${escapeHtml(a.applicant)}</td>
      <td>${escapeHtml(a.pet)}</td>
      <td style="color:var(--color-text-secondary)">${escapeHtml(a.date)}</td>
      <td>${statusBadge(a.status)}</td>
      <td>${actions}</td>
    </tr>`;
  }).join('');
}

function filterApps() {
  const q = document.getElementById('app-search').value.toLowerCase();
  const st = document.getElementById('app-status-filter').value;
  renderApps(apps.filter(a => {
    const searchable = [a.id, a.applicant, a.pet, a.reason].join(' ').toLowerCase();
    return (!q || searchable.includes(q)) && (!st || a.status === st);
  }));
}

function openAppDetail(i) {
  const a = apps[i];
  if (!a) return;
  document.getElementById('modal-app-title').textContent = `${a.id} - ${a.applicant}`;
  document.getElementById('modal-app-fields').innerHTML = [
    ['Applicant ID',entityCode('A', a.applicantId)],['Pet ID',entityCode('P', a.petId)],
    ['Applicant phone',a.applicantPhone],['Applicant email',a.applicantEmail],
    ['Applicant address',a.applicantAddress],['Pet experience',a.hasPetExperience ? 'Yes' : 'No'],
    ['Pet',a.pet],['Application date',a.date],['Status',a.status],
    ['Housing type',a.housingType],['Applicant created at',a.applicantCreatedAt],
    ['Reason',a.reason],['Reviewer',a.reviewer],
    ['Reviewed date',a.reviewedDate],['Decision note',a.decision]
  ].map(([l,v]) => `<div class="field-row"><span class="field-label">${escapeHtml(l)}</span><span style="max-width:60%;text-align:right">${escapeHtml(v)}</span></div>`).join('');
  document.getElementById('app-detail-overlay').classList.add('open');
}

function openReview(i) {
  reviewingIndex = i;
  const a = apps[i];
  if (!a) return;
  document.getElementById('review-title').textContent = `Review: ${a.id}`;
  document.getElementById('review-summary').innerHTML = `<strong>${escapeHtml(a.applicant)}</strong> applied to adopt <strong>${escapeHtml(a.pet)}</strong> on ${escapeHtml(a.date)}.<br><span style="color:var(--color-text-secondary);margin-top:4px;display:block">"${escapeHtml(a.reason)}"</span>`;
  document.getElementById('review-note').value = '';
  document.getElementById('review-fee').value = '';
  document.getElementById('review-handover').value = '';
  document.getElementById('review-overlay').classList.add('open');
}

async function submitReview(decision) {
  if (reviewingIndex < 0) return;
  const note = document.getElementById('review-note').value.trim();
  if (!note) {
    document.getElementById('review-note').style.borderColor = '#A32D2D';
    setTimeout(() => document.getElementById('review-note').style.borderColor = '', 1500);
    return;
  }
  const a = apps[reviewingIndex];
  if (decision === 'Approved') {
    const conflict = approvedApplicationsForPet(a.petId, a.applicationId)[0];
    if (conflict) {
      showToast(`Cannot approve ${a.id}: ${a.pet} already has approved application ${conflict.id}.`, 'error');
      return;
    }
  }
  const feeText = document.getElementById('review-fee').value.trim();
  const handoverNote = document.getElementById('review-handover').value.trim();
  try {
    await apiRequest(`/api/applications/${a.applicationId}/review`, {
      method: 'PATCH',
      body: {
        decision,
        note,
        reviewerName: 'Staff (you)',
        finalAdoptionFee: feeText ? Number(feeText) : null,
        handoverNote
      }
    });
    closeOverlay('review-overlay');
    reviewingIndex = -1;
    await loadData();
    showToast(`Application ${a.id} marked as ${decision}`, 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
}

function openNewAppModal() {
  const applicantSel = document.getElementById('form-applicant');
  applicantSel.innerHTML = '<option value="">Select an applicant...</option>';
  applicants.forEach(a => {
    const o = document.createElement('option');
    o.textContent = a.housingType ? `${a.name} (${a.housingType})` : a.name;
    o.value = a.applicantId;
    applicantSel.appendChild(o);
  });

  const petSel = document.getElementById('form-pet');
  petSel.innerHTML = '<option value="">Select a pet...</option>';
  pets.filter(p =>
    p.rawStatus === 'available'
    && !approvedApplicationsForPet(p.petId).length
    && !pendingApplicationsForPet(p.petId).length
  ).forEach(p => {
    const o = document.createElement('option');
    o.textContent = `${p.name} (${p.breed})`;
    o.value = p.petId;
    petSel.appendChild(o);
  });
  setHousingTypeSelectValue(document.getElementById('form-housing'));
  document.getElementById('form-applicant').value = '';
  document.getElementById('form-reason').value = '';
  document.getElementById('new-app-overlay').classList.add('open');
}

function syncHousingFromApplicant() {
  const applicantId = Number(document.getElementById('form-applicant').value);
  const applicant = applicants.find(a => a.applicantId === applicantId);
  setHousingTypeSelectValue(document.getElementById('form-housing'), applicant?.housingType || '');
}

async function submitNewApp() {
  const applicantId = Number(document.getElementById('form-applicant').value);
  const petId = Number(document.getElementById('form-pet').value);
  const reason = document.getElementById('form-reason').value.trim();
  const housing = document.getElementById('form-housing').value;
  if (!applicantId || !petId || !reason || !housing) { showToast('Please fill in all fields', 'info'); return; }
  try {
    const result = await apiRequest('/api/applications', {
      method: 'POST',
      body: {applicantId, petId, reason, housingType: housing}
    });
    closeOverlay('new-app-overlay');
    await loadData();
    showToast(`Application ${result.application.id} submitted successfully`, 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
}

function openNewFollowupModal() {
  const adoptionSel = document.getElementById('followup-adoption');
  adoptionSel.innerHTML = '<option value="">Select an adoption...</option>';
  adoptionRecords.forEach(record => {
    const o = document.createElement('option');
    o.textContent = `${record.id} - ${record.pet} / ${record.applicant}`;
    o.value = record.adoptionId;
    adoptionSel.appendChild(o);
  });
  document.getElementById('followup-date').value = todayIso();
  document.getElementById('followup-type').value = '';
  document.getElementById('followup-condition').value = '';
  document.getElementById('followup-feedback').value = '';
  document.getElementById('followup-result').value = '';
  document.getElementById('followup-note').value = '';
  document.getElementById('new-followup-overlay').classList.add('open');
}

async function submitFollowup() {
  const adoptionId = Number(document.getElementById('followup-adoption').value);
  const followupDate = document.getElementById('followup-date').value;
  const followupType = document.getElementById('followup-type').value;
  const petCondition = document.getElementById('followup-condition').value.trim();
  const adopterFeedback = document.getElementById('followup-feedback').value.trim();
  const resultStatus = document.getElementById('followup-result').value;
  const staffNote = document.getElementById('followup-note').value.trim();
  if (!adoptionId || !followupDate || !followupType || !petCondition || !resultStatus) {
    showToast('Please fill in the required follow-up fields', 'info');
    return;
  }
  try {
    const result = await apiRequest('/api/follow-ups', {
      method: 'POST',
      body: {adoptionId, followupDate, followupType, petCondition, adopterFeedback, resultStatus, staffNote}
    });
    closeOverlay('new-followup-overlay');
    await loadData();
    showToast(`Follow-up ${result.followUp.id} saved`, 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
}

function renderMedical() {
  const medTb = document.getElementById('medical-tbody');
  medTb.innerHTML = medicalRecords.length ? medicalRecords.map(r => `<tr>
    <td style="color:var(--color-text-secondary)">${escapeHtml(r.id)}</td>
    <td>${escapeHtml(r.pet)}<div class="muted-text">${escapeHtml(entityCode('P', r.petId))}</div></td>
    <td>${escapeHtml(r.date)}</td>
    <td>${escapeHtml(r.type)}</td>
    <td class="note-cell">${escapeHtml(r.diagnosis)}</td>
    <td class="note-cell">${escapeHtml(r.treatment)}</td>
    <td>${escapeHtml(r.vet)}</td>
    <td class="note-cell">${escapeHtml(r.notes)}</td>
    <td>${actionButtons('medical-records', r.recordId)}</td>
  </tr>`).join('') : `<tr><td colspan="9" style="text-align:center;padding:3rem 1rem;">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" style="opacity:0.4; margin-bottom:12px; color:var(--color-primary)">
          <circle cx="12" cy="12" r="10"></circle><path d="M16 16s-1.5-2-4-2-4 2-4 2"></path><line x1="9" y1="9" x2="9.01" y2="9"></line><line x1="15" y1="9" x2="15.01" y2="9"></line>
        </svg>
        <div style="font-size:15px;font-weight:600;color:var(--color-text-secondary);margin-bottom:4px">No medical records</div>
        <div style="font-size:13px;color:var(--color-text-tertiary)">We couldn\'t find any medical records matching your criteria.</div>
      </td></tr>`;

  const vaccTb = document.getElementById('vaccination-tbody');
  vaccTb.innerHTML = vaccinations.length ? vaccinations.map(v => `<tr>
    <td style="color:var(--color-text-secondary)">${escapeHtml(v.id)}</td>
    <td>${escapeHtml(v.pet)}<div class="muted-text">${escapeHtml(entityCode('P', v.petId))}</div></td>
    <td>${escapeHtml(v.vaccine)}</td>
    <td>${escapeHtml(v.doseNo)}</td>
    <td>${escapeHtml(v.vaccinationDate)}</td>
    <td${dueDateStyle(v.dueDate)}>${escapeHtml(v.dueDate)}</td>
    <td>${escapeHtml(v.vet)}</td>
    <td class="note-cell">${escapeHtml(v.notes)}</td>
    <td>${actionButtons('vaccinations', v.vaccinationId)}</td>
  </tr>`).join('') : `<tr><td colspan="9" style="text-align:center;padding:3rem 1rem;">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" style="opacity:0.4; margin-bottom:12px; color:var(--color-primary)">
          <circle cx="12" cy="12" r="10"></circle><path d="M16 16s-1.5-2-4-2-4 2-4 2"></path><line x1="9" y1="9" x2="9.01" y2="9"></line><line x1="15" y1="9" x2="15.01" y2="9"></line>
        </svg>
        <div style="font-size:15px;font-weight:600;color:var(--color-text-secondary);margin-bottom:4px">No vaccinations</div>
        <div style="font-size:13px;color:var(--color-text-tertiary)">We couldn\'t find any vaccinations matching your criteria.</div>
      </td></tr>`;
}

function dueDateStyle(dateText) {
  if (!dateText) return '';
  const todayMs = isoDateToUtcMs(todayIso());
  const dueMs = isoDateToUtcMs(dateText);
  if (Number.isNaN(todayMs) || Number.isNaN(dueMs)) return '';
  const diffDays = Math.floor((dueMs - todayMs) / 86400000);
  if (diffDays < 0) return ' style="color:#A32D2D"';
  if (diffDays <= 30) return ' style="color:#854F0B"';
  return '';
}

function renderVolunteers() {
  const volunteerTb = document.getElementById('volunteer-tbody');
  volunteerTb.innerHTML = volunteers.length ? volunteers.map(v => `<tr>
    <td style="color:var(--color-text-secondary)">${escapeHtml(v.id)}</td>
    <td><div style="display:flex;align-items:center;gap:8px"><div class="avatar">${escapeHtml(initials(v.name))}</div>${escapeHtml(v.name)}</div></td>
    <td>${escapeHtml(v.phone)}</td>
    <td>${escapeHtml(v.email)}</td>
    <td>${escapeHtml(v.shelter)}<div class="muted-text">${escapeHtml(entityCode('S', v.shelterId))}</div></td>
    <td>${escapeHtml(v.joined)}</td>
    <td class="note-cell">${escapeHtml(v.availability)}</td>
    <td>${statusBadge(v.status)}</td>
    <td>${escapeHtml(v.assignedPets)}</td>
    <td>${actionButtons('volunteers', v.volunteerId)}</td>
  </tr>`).join('') : `<tr><td colspan="10" style="text-align:center;padding:3rem 1rem;">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" style="opacity:0.4; margin-bottom:12px; color:var(--color-primary)">
          <circle cx="12" cy="12" r="10"></circle><path d="M16 16s-1.5-2-4-2-4 2-4 2"></path><line x1="9" y1="9" x2="9.01" y2="9"></line><line x1="15" y1="9" x2="15.01" y2="9"></line>
        </svg>
        <div style="font-size:15px;font-weight:600;color:var(--color-text-secondary);margin-bottom:4px">No volunteers</div>
        <div style="font-size:13px;color:var(--color-text-tertiary)">We couldn\'t find any volunteers matching your criteria.</div>
      </td></tr>`;

  const careTb = document.getElementById('care-tbody');
  careTb.innerHTML = careAssignments.length ? careAssignments.map(c => `<tr>
    <td style="color:var(--color-text-secondary)">${escapeHtml(c.id)}</td>
    <td>${escapeHtml(c.date)}</td>
    <td>${escapeHtml(c.volunteer)}<div class="muted-text">${escapeHtml(entityCode('VLT', c.volunteerId))}</div></td>
    <td>${escapeHtml(c.pet)}<div class="muted-text">${escapeHtml(entityCode('P', c.petId))}</div></td>
    <td>${escapeHtml(c.shift)}</td>
    <td>${escapeHtml(c.task)}</td>
    <td>${statusBadge(c.status)}</td>
    <td class="note-cell">${escapeHtml(c.notes)}</td>
    <td>${actionButtons('care-assignments', c.assignmentId)}</td>
  </tr>`).join('') : `<tr><td colspan="9" style="text-align:center;padding:3rem 1rem;">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" style="opacity:0.4; margin-bottom:12px; color:var(--color-primary)">
          <circle cx="12" cy="12" r="10"></circle><path d="M16 16s-1.5-2-4-2-4 2-4 2"></path><line x1="9" y1="9" x2="9.01" y2="9"></line><line x1="15" y1="9" x2="15.01" y2="9"></line>
        </svg>
        <div style="font-size:15px;font-weight:600;color:var(--color-text-secondary);margin-bottom:4px">No care assignments</div>
        <div style="font-size:13px;color:var(--color-text-tertiary)">We couldn\'t find any care assignments matching your criteria.</div>
      </td></tr>`;
}

function renderAnalytics() {
  const data = analytics || {};
  document.getElementById('analytics-occupancy-tbody').innerHTML = renderTableRows(
    data.occupancy,
    4,
    row => `<tr>
      <td>${escapeHtml(row.shelter)}</td>
      <td>${escapeHtml(row.currentPetCount)}</td>
      <td>${escapeHtml(row.capacity)}</td>
      <td>${escapeHtml(formatPercent(row.occupancyRate))}</td>
    </tr>`
  );

  document.getElementById('analytics-housing-tbody').innerHTML = renderTableRows(
    data.housingApproval,
    4,
    row => `<tr>
      <td>${escapeHtml(row.housingType)}</td>
      <td>${escapeHtml(row.totalApplications)}</td>
      <td>${escapeHtml(row.approvedCount)}</td>
      <td>${escapeHtml(formatPercent(row.approvalRate))}</td>
    </tr>`
  );

  document.getElementById('analytics-species-tbody').innerHTML = renderTableRows(
    data.speciesDemand,
    4,
    row => `<tr>
      <td>${escapeHtml(row.species)}</td>
      <td>${escapeHtml(row.totalApplications)}</td>
      <td>${escapeHtml(row.successfulAdoptions)}</td>
      <td>${escapeHtml(formatPercent(row.adoptionSuccessRate))}</td>
    </tr>`
  );

  document.getElementById('analytics-followup-tbody').innerHTML = renderTableRows(
    data.followupOutcomes,
    2,
    row => `<tr>
      <td>${escapeHtml(row.resultStatus)}</td>
      <td>${escapeHtml(row.totalFollowups)}</td>
    </tr>`
  );

  document.getElementById('analytics-longstay-tbody').innerHTML = renderTableRows(
    data.longStayPets,
    6,
    row => `<tr>
      <td style="color:var(--color-text-secondary)">${escapeHtml(row.id)}</td>
      <td style="font-weight:500">${escapeHtml(row.name)}</td>
      <td>${escapeHtml(row.species)}</td>
      <td>${escapeHtml(row.breed)}</td>
      <td style="color:var(--color-text-secondary)">${escapeHtml(row.intakeDate)}</td>
      <td>${escapeHtml(row.daysInShelter)}</td>
    </tr>`
  );

  document.getElementById('analytics-workload-tbody').innerHTML = renderTableRows(
    data.volunteerWorkload,
    5,
    row => `<tr>
      <td style="font-weight:500">${escapeHtml(row.name)}</td>
      <td>${escapeHtml(row.totalAssignments)}</td>
      <td>${escapeHtml(row.completedTasks)}</td>
      <td>${escapeHtml(row.scheduledTasks)}</td>
      <td>${escapeHtml(row.cancelledTasks)}</td>
    </tr>`
  );

  if (window.Chart && data) {
    if (window.occupancyChart) window.occupancyChart.destroy();
    if (window.speciesChart) window.speciesChart.destroy();

    const occCtx = document.getElementById("chart-occupancy");
    if (occCtx && data.occupancy) {
      window.occupancyChart = new Chart(occCtx, {
        type: "bar",
        data: {
          labels: data.occupancy.map(o => o.shelter),
          datasets: [
            { label: "Current Pets", data: data.occupancy.map(o => o.currentPetCount), backgroundColor: "#f76707", borderRadius: 4 },
            { label: "Capacity", data: data.occupancy.map(o => o.capacity), backgroundColor: "#e2e8f0", borderRadius: 4 }
          ]
        },
        options: { maintainAspectRatio: false, responsive: true, plugins: { legend: { position: "bottom" } }, scales: { y: { beginAtZero: true } } }
      });
    }

    const spCtx = document.getElementById("chart-species");
    if (spCtx && data.speciesDemand) {
      window.speciesChart = new Chart(spCtx, {
        type: "doughnut",
        data: {
          labels: data.speciesDemand.map(s => s.species),
          datasets: [{
            data: data.speciesDemand.map(s => s.totalApplications),
            backgroundColor: ["#f76707", "#1c7ed6", "#2b8a3e", "#fab005", "#7950f2"],
            borderWidth: 0
          }]
        },
        options: { maintainAspectRatio: false, responsive: true, plugins: { legend: { position: "right" } }, cutout: "65%" }
      });
    }
  }


}


function renderTableRows(rows, colspan, renderRow) {
  return rows?.length
    ? rows.map(renderRow).join('')
    : `<tr><td colspan="${colspan}" style="text-align:center;padding:3rem 1rem;">
        <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round" stroke-linejoin="round" style="opacity:0.4; margin-bottom:12px; color:var(--color-primary)">
          <path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path>
          <polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline>
          <line x1="12" y1="22.08" x2="12" y2="12"></line>
        </svg>
        <div style="font-size:15px;font-weight:600;color:var(--color-text-secondary);margin-bottom:4px">No records found</div>
        <div style="font-size:13px;color:var(--color-text-tertiary)">It looks like there is no data to display here at the moment.</div>
      </td></tr>`;
}

function formatPercent(value) {
  const n = Number(value);
  if (!Number.isFinite(n)) return '-';
  return `${n.toFixed(n % 1 === 0 ? 0 : 2)}%`;
}

function formatMoney(value) {
  if (value == null || value === '') return '-';
  const n = Number(value);
  if (!Number.isFinite(n)) return '-';
  return `$${n.toFixed(2)}`;
}

function renderLlmBonus() {
  const data = llmBonus || {};
  const summary = data.summary || {};
  document.getElementById('llm-refinement-count').textContent = summary.architectureRefinementCount ?? '--';
  document.getElementById('llm-check-count').textContent = summary.integrityCheckCount ?? '--';
  document.getElementById('llm-finding-count').textContent = summary.openFindingCount ?? '--';
  document.getElementById('llm-query-count').textContent = summary.safeReadOnlyQueryCount ?? '--';

  document.getElementById('llm-refinement-tbody').innerHTML = renderTableRows(
    data.architectureRefinements,
    5,
    row => `<tr>
      <td style="font-weight:500">${escapeHtml(row.area)}</td>
      <td>${escapeHtml(row.originalDesign)}</td>
      <td>${escapeHtml(row.llmRefinement)}</td>
      <td>${escapeHtml(row.implementation)}</td>
      <td>${escapeHtml(row.benefit)}</td>
    </tr>`
  );

  document.getElementById('llm-audit-tbody').innerHTML = renderTableRows(
    data.integrityAudit,
    6,
    row => `<tr>
      <td><div style="font-weight:500">${escapeHtml(row.title)}</div><div class="muted-text">${escapeHtml(row.llmRationale)}</div></td>
      <td>${escapeHtml(row.severity)}</td>
      <td><code>${escapeHtml(row.enforcementLayer)}</code></td>
      <td>${statusBadge(row.status)}</td>
      <td>${escapeHtml(row.findingCount)}</td>
      <td>${escapeHtml(row.refinement)}</td>
    </tr>`
  );

  document.getElementById('llm-constraint-tbody').innerHTML = renderTableRows(
    data.refinedConstraints,
    3,
    row => `<tr>
      <td style="font-weight:500">${escapeHtml(row.name)}</td>
      <td><code>${escapeHtml(row.sql)}</code></td>
      <td>${escapeHtml(row.reason)}</td>
    </tr>`
  );

  document.getElementById('llm-prompt-tbody').innerHTML = renderTableRows(
    data.promptPatterns,
    3,
    row => `<tr>
      <td style="font-weight:500">${escapeHtml(row.pattern)}</td>
      <td>${escapeHtml(row.prompt)}<div class="muted-text">${escapeHtml(row.routingLogic)}</div></td>
      <td><code>${escapeHtml(row.expectedQuery)}</code></td>
    </tr>`
  );

  document.getElementById('llm-catalog-tbody').innerHTML = renderTableRows(
    data.queryCatalog,
    4,
    row => `<tr>
      <td><code>${escapeHtml(row.name)}</code></td>
      <td>${escapeHtml(row.category)}</td>
      <td>${statusBadge(row.readOnly ? 'Yes' : 'No')}</td>
      <td>${escapeHtml(row.description)}</td>
    </tr>`
  );


}


async function submitLlmPrompt() {
  const input = document.getElementById('llm-prompt-input');
  const prompt = input.value.trim();
  if (!prompt) {
    showToast('Please enter a natural language prompt', 'info');
    return;
  }
  try {
    const result = await apiRequest('/api/llm-query', {
      method: 'POST',
      body: {prompt}
    });
    renderLlmQueryResult(result);
    showToast(`Matched ${result.matchedQuery.name}`, 'success');
  } catch (err) {
    showToast(err.message, 'error');
  }
}

function renderLlmQueryResult(result) {
  const summary = document.getElementById('llm-query-summary');
  summary.style.display = 'block';
  summary.innerHTML = `<strong>${escapeHtml(result.matchedQuery.title)}</strong><br><span class="muted-text">${escapeHtml(result.safetyModel)} Category: ${escapeHtml(result.matchedQuery.category)}. Read-only: ${escapeHtml(result.matchedQuery.readOnly ? 'Yes' : 'No')}. Returned ${escapeHtml(result.rowCount)} rows.</span>`;

  const sqlBlock = document.getElementById('llm-query-sql');
  sqlBlock.style.display = 'block';
  sqlBlock.textContent = result.matchedQuery.sql;

  const head = document.getElementById('llm-query-head');
  const body = document.getElementById('llm-query-body');
  const rows = result.rows || [];
  if (!rows.length) {
    head.innerHTML = '';
    body.innerHTML = '<tr><td style="text-align:center;padding:2rem;color:var(--color-text-secondary)">No rows returned</td></tr>';
    return;
  }
  const columns = Object.keys(rows[0]);
  head.innerHTML = `<tr>${columns.map(col => `<th>${escapeHtml(col)}</th>`).join('')}</tr>`;
  body.innerHTML = rows.map(row => `<tr>${columns.map(col => `<td>${escapeHtml(row[col])}</td>`).join('')}</tr>`).join('');
}

function initials(name) {
  return String(name || '')
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map(part => part[0].toUpperCase())
    .join('') || '?';
}

function renderLoadError(message) {
  document.getElementById('dash-total-pets').textContent = '--';
  document.getElementById('dash-shelter-count').textContent = 'backend unavailable';
  document.getElementById('activity-feed').innerHTML = `<div class="activity-item"><div class="activity-dot dot-amber"></div><div><div class="activity-text">${escapeHtml(message)}</div><div class="activity-time">Start the API server</div></div></div>`;
  document.getElementById('shelter-tbody').innerHTML = '<tr><td colspan="9" style="text-align:center;padding:2rem;color:var(--color-text-secondary)">Backend API is not connected</td></tr>';
  document.getElementById('pet-tbody').innerHTML = '<tr><td colspan="8" style="text-align:center;padding:2rem;color:var(--color-text-secondary)">Backend API is not connected</td></tr>';
  document.getElementById('applicant-tbody').innerHTML = '<tr><td colspan="9" style="text-align:center;padding:2rem;color:var(--color-text-secondary)">Backend API is not connected</td></tr>';
  document.getElementById('app-tbody').innerHTML = '<tr><td colspan="6" style="text-align:center;padding:2rem;color:var(--color-text-secondary)">Backend API is not connected</td></tr>';
  document.getElementById('adoption-record-tbody').innerHTML = '<tr><td colspan="8" style="text-align:center;padding:2rem;color:var(--color-text-secondary)">Backend API is not connected</td></tr>';
  document.getElementById('followup-tbody').innerHTML = '<tr><td colspan="9" style="text-align:center;padding:2rem;color:var(--color-text-secondary)">Backend API is not connected</td></tr>';
  document.getElementById('medical-tbody').innerHTML = '<tr><td colspan="9" style="text-align:center;padding:2rem;color:var(--color-text-secondary)">Backend API is not connected</td></tr>';
  document.getElementById('vaccination-tbody').innerHTML = '<tr><td colspan="9" style="text-align:center;padding:2rem;color:var(--color-text-secondary)">Backend API is not connected</td></tr>';
  document.getElementById('volunteer-tbody').innerHTML = '<tr><td colspan="10" style="text-align:center;padding:2rem;color:var(--color-text-secondary)">Backend API is not connected</td></tr>';
  document.getElementById('care-tbody').innerHTML = '<tr><td colspan="9" style="text-align:center;padding:2rem;color:var(--color-text-secondary)">Backend API is not connected</td></tr>';
  ['analytics-occupancy-tbody','analytics-housing-tbody','analytics-species-tbody','analytics-followup-tbody','analytics-longstay-tbody','analytics-workload-tbody'].forEach(id => {
    const tb = document.getElementById(id);
    if (tb) tb.innerHTML = '<tr><td colspan="6" style="text-align:center;padding:2rem;color:var(--color-text-secondary)">Backend API is not connected</td></tr>';
  });
  ['llm-refinement-tbody','llm-audit-tbody','llm-constraint-tbody','llm-prompt-tbody','llm-catalog-tbody'].forEach(id => {
    const tb = document.getElementById(id);
    if (tb) tb.innerHTML = '<tr><td colspan="5" style="text-align:center;padding:2rem;color:var(--color-text-secondary)">Backend API is not connected</td></tr>';
  });
}

document.getElementById('form-applicant').addEventListener('change', syncHousingFromApplicant);
document.getElementById('llm-prompt-input').addEventListener('keydown', event => {
  if (event.key === 'Enter') submitLlmPrompt();
});
loadData().catch(err => {
  renderLoadError(err.message);
  showToast(`Could not load backend data: ${err.message}`, 'error');
});

// Setup Analytics Table Sorting
document.querySelectorAll('#page-analytics table th').forEach(th => {
  th.style.cursor = 'pointer';
  th.title = 'Click to sort';
  th.addEventListener('click', () => {
    const table = th.closest('table');
    const tbody = table.querySelector('tbody');
    const rows = Array.from(tbody.querySelectorAll('tr'));
    if (rows.length === 0 || rows[0].querySelector('td[colspan]')) return; // ignore loading/empty
    
    const index = Array.from(th.parentNode.children).indexOf(th);
    const isAscending = th.dataset.sortDir === 'asc';
    
    rows.sort((a, b) => {
      const aText = a.children[index].textContent.trim();
      const bText = b.children[index].textContent.trim();
      
      // Attempt numeric sort if values look like numbers (percentages, currency, IDs)
      const aNum = parseFloat(aText.replace(/[^0-9.-]+/g, ''));
      const bNum = parseFloat(bText.replace(/[^0-9.-]+/g, ''));
      const isNum = !isNaN(aNum) && !isNaN(bNum) && /^[0-9$.%-]/.test(aText) && /^[0-9$.%-]/.test(bText);
      
      if (isNum) {
        return isAscending ? aNum - bNum : bNum - aNum;
      } else {
        return isAscending ? aText.localeCompare(bText) : bText.localeCompare(aText);
      }
    });
    
    table.querySelectorAll('th').forEach(h => {
      h.dataset.sortDir = '';
      h.textContent = h.textContent.replace(/ [▲▼]$/, '');
    });
    
    th.dataset.sortDir = isAscending ? 'desc' : 'asc';
    th.textContent = th.textContent + (isAscending ? ' ▼' : ' ▲');
    
    tbody.append(...rows);
  });
});
