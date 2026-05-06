
// ═══════════════════════════════════════════════════════
//  WorldReasoner Annotation Study — Google Apps Script
//  
//  Setup:
//    1. Replace SHEET_ID with your Google Sheet ID
//    2. Replace FOLDER_ID with your Google Drive folder ID
//    3. Run initSessions() once to populate the sheet
//    4. Deploy as Web App (Execute as: Me, Anyone can access)
// ═══════════════════════════════════════════════════════

const SHEET_ID  = '1PFoCKRolZYXUhFT00zCEHQmp-goSmbCcycJtbVribWw';   // Google Sheet ID
const FOLDER_ID = '1p0wViCpvwyFI4XQH5tHA52HLxSxxuiLj';  // Google Drive folder ID for results
const BASE_URL  = 'https://chiyz.xyz/wr-annotation/';
const N_SESSIONS = 27;  // number of main sessions (s01–s27)
const N_OVERLAP_SESSIONS = 3;  // overlap sessions (ov01–ov03)
const OVERLAP_REPLICATES = 3;  // annotators per overlap session
const ASSIGNMENT_TTL_HOURS = 6;  // recycle assigned-but-unsubmitted slots after this many hours

const SESSION_HEADERS = [
  'slot_id',
  'session_id',
  'prolific_pid',
  'assigned_at',
  'submitted_at',
  'status',
];


// ── Session dispatcher (GET) — kept for manual testing only ─
function doGet(e) {
  const pid = (e.parameter && e.parameter.PROLIFIC_PID) || 'unknown_' + Date.now();
  return assignSession(pid);
}


// ── Submission receiver (POST) ───────────────────────────
function doPost(e) {
  try {
    const payload = JSON.parse(e.postData.contents);

    // Session assignment request
    if (payload.action === 'assign') {
      return assignSession(payload.prolific_pid || 'unknown_' + Date.now());
    }

    // Original result submission
    const pid    = payload.prolific_pid || 'unknown_' + Date.now();
    const sid    = payload.session_id   || 'nosession';
    const folder = DriveApp.getFolderById(FOLDER_ID);
    const filename = pid + '_' + sid + '.json';
    const existing = folder.getFilesByName(filename);
    if (existing.hasNext()) existing.next().setTrashed(true);
    folder.createFile(filename, JSON.stringify(payload), MimeType.PLAIN_TEXT);
    markSubmitted(pid, sid);
    return jsonResponse({ ok: true });

  } catch (err) {
    return jsonResponse({ ok: false, error: err.message });
  }
}

function assignSession(pid) {
  const lock = LockService.getScriptLock();
  try { lock.waitLock(30000); } catch (_) {
    return jsonResponse({ ok: false, error: 'Server busy' });
  }
  try {
    const sheet = getSessionsSheet();
    ensureSessionHeaders(sheet);
    const data  = sheet.getDataRange().getValues();
    const col = headerMap(data[0]);
    const now = new Date();
    const nowIso = now.toISOString();

    // Return existing assignment if PID already seen
    for (let i = 1; i < data.length; i++) {
      if (data[i][col.prolific_pid] === pid) {
        return jsonResponse({
          ok: true,
          session: data[i][col.session_id],
          status: data[i][col.status] || 'assigned',
        });
      }
    }

    // Find first available row
    let rowIndex = -1;
    for (let i = 1; i < data.length; i++) {
      const status = String(data[i][col.status] || '').toLowerCase();
      const currentPid = data[i][col.prolific_pid];
      const submittedAt = data[i][col.submitted_at];
      if (!submittedAt && (!currentPid || status === 'available' || status === 'expired')) {
        rowIndex = i;
        break;
      }
    }

    // If all fresh slots are taken, recycle the oldest stale assigned row.
    if (rowIndex === -1) {
      let oldest = Infinity;
      for (let i = 1; i < data.length; i++) {
        const status = String(data[i][col.status] || '').toLowerCase();
        const submittedAt = data[i][col.submitted_at];
        const assignedAt = data[i][col.assigned_at];
        if (submittedAt || status === 'submitted' || !assignedAt) continue;

        const t = new Date(assignedAt).getTime();
        if (!Number.isFinite(t)) continue;
        const ageHours = (now.getTime() - t) / (1000 * 60 * 60);
        if (ageHours >= ASSIGNMENT_TTL_HOURS && t < oldest) {
          oldest = t;
          rowIndex = i;
        }
      }
    }

    if (rowIndex === -1) {
      return jsonResponse({
        ok: false,
        error: 'No available annotation sessions. Please contact the researcher.',
      });
    }

    sheet.getRange(rowIndex + 1, col.prolific_pid + 1).setValue(pid);
    sheet.getRange(rowIndex + 1, col.assigned_at + 1).setValue(nowIso);
    sheet.getRange(rowIndex + 1, col.submitted_at + 1).setValue('');
    sheet.getRange(rowIndex + 1, col.status + 1).setValue('assigned');

    return jsonResponse({
      ok: true,
      session: data[rowIndex][col.session_id],
      status: 'assigned',
      slot_id: data[rowIndex][col.slot_id],
    });

  } finally {
    lock.releaseLock();
  }
}


// ── Setup helper — run once manually ────────────────────
function initSessions() {
  const ss = SpreadsheetApp.openById(SHEET_ID);
  let sheet = ss.getSheetByName('sessions');
  if (!sheet) sheet = ss.insertSheet('sessions');

  // Preserve any already-assigned rows
  const existing = sheet.getDataRange().getValues();
  const assigned = {};
  if (existing.length > 0 && existing[0].length > 0) {
    const col = legacyAwareHeaderMap(existing[0]);
    for (let i = 1; i < existing.length; i++) {
      const slotId = existing[i][col.slot_id] || existing[i][col.session_id];
      if (!slotId) continue;
      assigned[slotId] = {
        prolific_pid: existing[i][col.prolific_pid] || '',
        assigned_at: existing[i][col.assigned_at] || '',
        submitted_at: existing[i][col.submitted_at] || '',
        status: existing[i][col.status] || '',
      };
    }
  }

  sheet.clearContents();
  sheet.appendRow(SESSION_HEADERS);

  for (let i = 1; i <= N_SESSIONS; i++) {
    const sid = 's' + String(i).padStart(2, '0');
    appendSessionRow(sheet, sid, sid, assigned[sid]);
  }

  for (let i = 1; i <= N_OVERLAP_SESSIONS; i++) {
    const sid = 'ov' + String(i).padStart(2, '0');
    for (let r = 1; r <= OVERLAP_REPLICATES; r++) {
      const slotId = sid + '_r' + r;
      appendSessionRow(sheet, slotId, sid, assigned[slotId]);
    }
  }

  Logger.log(
    'Initialised ' + N_SESSIONS + ' main sessions and ' +
    (N_OVERLAP_SESSIONS * OVERLAP_REPLICATES) + ' overlap slots.'
  );
}

function initOverlapSessionsOnly() {
  const ss = SpreadsheetApp.openById(SHEET_ID);
  let sheet = ss.getSheetByName('sessions');
  if (!sheet) sheet = ss.insertSheet('sessions');
  ensureSessionHeaders(sheet);

  const existing = sheet.getDataRange().getValues();
  const col = headerMap(existing[0]);

  for (let i = existing.length - 1; i >= 1; i--) {
    const sid = String(existing[i][col.session_id] || '');
    const slotId = String(existing[i][col.slot_id] || '');
    if (sid.indexOf('ov') === 0 || slotId.indexOf('ov') === 0) {
      sheet.deleteRow(i + 1);
    }
  }

  for (let i = 1; i <= N_OVERLAP_SESSIONS; i++) {
    const sid = 'ov' + String(i).padStart(2, '0');
    for (let r = 1; r <= OVERLAP_REPLICATES; r++) {
      const slotId = sid + '_r' + r;
      appendSessionRow(sheet, slotId, sid, null);
    }
  }

  Logger.log(
    'Reinitialised overlap only: ' +
    (N_OVERLAP_SESSIONS * OVERLAP_REPLICATES) + ' slots.'
  );
}

function getSessionsSheet() {
  const ss = SpreadsheetApp.openById(SHEET_ID);
  let sheet = ss.getSheetByName('sessions');
  if (!sheet) {
    sheet = ss.insertSheet('sessions');
    sheet.appendRow(SESSION_HEADERS);
  }
  ensureSessionHeaders(sheet);
  return sheet;
}

function appendSessionRow(sheet, slotId, sessionId, previous) {
  previous = previous || {};
  const status = previous.status ||
    (previous.submitted_at ? 'submitted' : (previous.prolific_pid ? 'assigned' : 'available'));
  sheet.appendRow([
    slotId,
    sessionId,
    previous.prolific_pid || '',
    previous.assigned_at || '',
    previous.submitted_at || '',
    status,
  ]);
}

function markSubmitted(pid, sid) {
  const lock = LockService.getScriptLock();
  try { lock.waitLock(30000); } catch (_) { return; }
  try {
    const sheet = getSessionsSheet();
    const data = sheet.getDataRange().getValues();
    const col = headerMap(data[0]);
    const nowIso = new Date().toISOString();

    let rowIndex = -1;
    for (let i = 1; i < data.length; i++) {
      if (data[i][col.prolific_pid] === pid && data[i][col.session_id] === sid) {
        rowIndex = i;
        break;
      }
    }

    if (rowIndex === -1) {
      for (let i = 1; i < data.length; i++) {
        if (data[i][col.prolific_pid] === pid) {
          rowIndex = i;
          break;
        }
      }
    }

    if (rowIndex === -1) {
      for (let i = 1; i < data.length; i++) {
        if (data[i][col.session_id] === sid && !data[i][col.submitted_at]) {
          rowIndex = i;
          break;
        }
      }
    }

    if (rowIndex !== -1) {
      sheet.getRange(rowIndex + 1, col.prolific_pid + 1).setValue(pid);
      sheet.getRange(rowIndex + 1, col.submitted_at + 1).setValue(nowIso);
      sheet.getRange(rowIndex + 1, col.status + 1).setValue('submitted');
    }
  } finally {
    lock.releaseLock();
  }
}

function ensureSessionHeaders(sheet) {
  const range = sheet.getDataRange();
  const values = range.getValues();
  if (!values.length || !values[0].length) {
    sheet.clearContents();
    sheet.appendRow(SESSION_HEADERS);
    return;
  }
  if (values[0][0] === 'slot_id') {
    return;
  }

  // Migrate the old 3-column sheet format:
  // session_id | prolific_pid | assigned_at
  if (values[0][0] === 'session_id') {
    const migrated = [];
    for (let i = 1; i < values.length; i++) {
      const sid = values[i][0];
      if (!sid) continue;
      const pid = values[i][1] || '';
      const assignedAt = values[i][2] || '';
      migrated.push([
        sid,
        sid,
        pid,
        assignedAt,
        '',
        pid ? 'assigned' : 'available',
      ]);
    }
    sheet.clearContents();
    sheet.appendRow(SESSION_HEADERS);
    migrated.forEach(function(row) { sheet.appendRow(row); });
  }
}

function headerMap(headers) {
  const map = {};
  headers.forEach(function(h, i) { map[h] = i; });
  const required = SESSION_HEADERS;
  for (let i = 0; i < required.length; i++) {
    if (map[required[i]] == null) {
      throw new Error('sessions sheet is missing column: ' + required[i]);
    }
  }
  return {
    slot_id: map.slot_id,
    session_id: map.session_id,
    prolific_pid: map.prolific_pid,
    assigned_at: map.assigned_at,
    submitted_at: map.submitted_at,
    status: map.status,
  };
}

function legacyAwareHeaderMap(headers) {
  const map = {};
  headers.forEach(function(h, i) { map[h] = i; });
  return {
    slot_id: map.slot_id != null ? map.slot_id : 0,
    session_id: map.session_id != null ? map.session_id : 0,
    prolific_pid: map.prolific_pid != null ? map.prolific_pid : 1,
    assigned_at: map.assigned_at != null ? map.assigned_at : 2,
    submitted_at: map.submitted_at != null ? map.submitted_at : -1,
    status: map.status != null ? map.status : -1,
  };
}


// ── Helpers ──────────────────────────────────────────────
function htmlPage(body) {
  return HtmlService
    .createHtmlOutput('<html><body>' + body + '</body></html>')
    .setXFrameOptionsMode(HtmlService.XFrameOptionsMode.ALLOWALL);
}

function jsonResponse(obj) {
  return ContentService
    .createTextOutput(JSON.stringify(obj))
    .setMimeType(ContentService.MimeType.JSON);
}
