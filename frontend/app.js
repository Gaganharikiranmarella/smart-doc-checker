// frontend/app.js
const API = "http://localhost:8000";
let batchId = null, userId = null, lastReportUrl = null;

function setUsage(d, r){ document.getElementById("docs").textContent=d; document.getElementById("reports").textContent=r; }
function log(txt){ document.getElementById("out").textContent = txt; }

document.getElementById("init").onclick = async () => {
  userId = document.getElementById("user").value || "demo-user";
  const form = new FormData(); form.append("user_id", userId);
  const res = await fetch(`${API}/init`, {method:"POST", body:form});
  const data = await res.json();
  batchId = data.batch_id; setUsage(data.totals.docs_analyzed, data.totals.reports_generated);
  log("Initialized");
};

document.getElementById("upload").onclick = async () => {
  const files = document.getElementById("file").files;
  for (const f of files){
    const form = new FormData();
    form.append("file", f);
    form.append("batch_id", batchId);
    form.append("user_id", userId);
    await fetch(`${API}/upload`, {method:"POST", body: form});
  }
  // fetch latest totals via analyze to reflect billing after parsing
  log("Uploaded");
};

document.getElementById("analyze").onclick = async () => {
  const form = new FormData();
  form.append("batch_id", batchId); form.append("user_id", userId);
  const res = await fetch(`${API}/analyze`, {method:"POST", body:form});
  const data = await res.json();
  setUsage(data.docs_analyzed, data.reports_generated);
  log(JSON.stringify(data.conflicts, null, 2));
};

document.getElementById("report").onclick = async () => {
  const form = new FormData();
  form.append("batch_id", batchId); form.append("user_id", userId);
  const res = await fetch(`${API}/report`, {method:"POST", body:form});
  const data = await res.json();
  setUsage(data.docs_analyzed, data.reports_generated);
  lastReportUrl = `${API}${data.report_url}`;
  document.getElementById("download").href = lastReportUrl;
  log("Report generated");
};
