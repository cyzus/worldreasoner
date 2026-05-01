
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
    const data  = sheet.getDataRange().getValues();

    // Return existing assignment if PID already seen
    for (let i = 1; i < data.length; i++) {
      if (data[i][1] === pid) {
        return jsonResponse({ ok: true, session: data[i][0] });
      }
    }

    // Find first unassigned row
    let rowIndex = -1, sessionId = null;
    for (let i = 1; i < data.length; i++) {
      if (!data[i][1]) { rowIndex = i; sessionId = data[i][0]; break; }
    }
    // All taken — recycle least-recently assigned
    if (rowIndex === -1) {
      let oldest = Infinity;
      for (let i = 1; i < data.length; i++) {
        const t = data[i][2] ? new Date(data[i][2]).getTime() : 0;
        if (t < oldest) { oldest = t; rowIndex = i; }
      }
      sessionId = data[rowIndex][0];
    }

    sheet.getRange(rowIndex + 1, 2).setValue(pid);
    sheet.getRange(rowIndex + 1, 3).setValue(new Date().toISOString());
    return jsonResponse({ ok: true, session: sessionId });

  } finally {
    lock.releaseLock();
  }
}


// ── Setup helper — run once manually ────────────────────
function initSessions() {
  const sheet = SpreadsheetApp
    .openById(SHEET_ID)
    .getSheetByName('sessions');

  // Preserve any already-assigned rows
  const existing = sheet.getDataRange().getValues();
  const assigned = {};
  for (let i = 1; i < existing.length; i++) {
    if (existing[i][0]) assigned[existing[i][0]] = [existing[i][1] || '', existing[i][2] || ''];
  }

  sheet.clearContents();
  sheet.appendRow(['session_id', 'prolific_pid', 'assigned_at']);

  for (let i = 1; i <= N_SESSIONS; i++) {
    const sid = 's' + String(i).padStart(2, '0');
    const row = assigned[sid] || ['', ''];
    sheet.appendRow([sid, row[0], row[1]]);
  }

  Logger.log('Initialised ' + N_SESSIONS + ' sessions.');
}

function getSessionsSheet() {
  const ss = SpreadsheetApp.openById(SHEET_ID);
  let sheet = ss.getSheetByName('sessions');
  if (!sheet) {
    sheet = ss.insertSheet('sessions');
    sheet.appendRow(['session_id', 'prolific_pid', 'assigned_at']);
  }
  return sheet;
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
