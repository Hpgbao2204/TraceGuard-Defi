"""Build blinded, offline reviewer portals for supplementary candidate leads."""
from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LEADS = ROOT / "eval/results/m6_supplementary_candidate_leads.json"
INCIDENTS = ROOT / "corpus/incidents.jsonl"
ENRICHED = ROOT / "eval/results/m6_supplementary_display_evidence.json"
OUT = ROOT / "corpus/annotations/review_bundles_supplementary"
FORBIDDEN = ("\"factors\"", "gt_factors", "root_cause_gt", "release_operator",
             "operator_scope", "system_verdict", "mutation_result",
             "CAUSE", "NO_EFFECT", "reviewer_votes", "adjudicated_result")


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def head() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def load_trace() -> dict[str, dict]:
    path = ROOT / "eval/results/e1_trace_cache.jsonl"
    if not path.is_file():
        return {}
    result = {}
    for line in path.read_text().splitlines():
        if line.strip():
            row = json.loads(line)
            result[str(row.get("tx_hash", "")).lower()] = row.get("trace") or {}
    return result


def call_summary(call: dict) -> dict:
    data = str(call.get("input") or "")
    return {"from": call.get("from"), "to": call.get("to"),
            "selector": data[:10] if data.startswith("0x") else None,
            "value": call.get("value"), "gas_used": call.get("gasUsed"),
            "type": call.get("type"),
            "calls": [call_summary(c) for c in call.get("calls", []) if isinstance(c, dict)]}


def safe_leads() -> list[dict]:
    leads = json.loads(LEADS.read_text())["leads"]
    incidents = {json.loads(line)["id"]: json.loads(line)
                 for line in INCIDENTS.read_text().splitlines() if line.strip()}
    traces = load_trace()
    enriched = json.loads(ENRICHED.read_text())["cases"] if ENRICHED.is_file() else []
    enriched_by_case = {row["case_id"]: row for row in enriched}
    output = []
    for lead in leads:
        incident = incidents.get(lead["case_id"], {})
        tx = lead["tx_hash"].lower()
        # Explicit allowlist: never copy the lead row wholesale.
        row = {"case_id": lead["case_id"], "tx_hash": tx,
               "chain": incident.get("chain"), "date": incident.get("date"),
               "protocol_name": incident.get("protocol"),
               "public_sources": [incident["source_url"]] if incident.get("source_url") else []}
        trace = traces.get(tx)
        if trace:
            tree = trace.get("tree") if isinstance(trace, dict) else None
            row["transaction_summary"] = {"from": trace.get("from"), "to": trace.get("to"),
                                           "value": trace.get("value"), "status": trace.get("status")}
            row["observed_call_tree"] = call_summary(tree) if isinstance(tree, dict) else {}
            row["evidence_sources"] = [{"artifact": "eval/results/e1_trace_cache.jsonl",
                                         "field": "trace.tree", "tx_hash": tx}]
        else:
            row["evidence_unavailable"] = ["local objective call trace is not materialized"]
        if row["case_id"] in enriched_by_case:
            row["objective_evidence"] = enriched_by_case[row["case_id"]]
        output.append(row)
    return output


def render(reviewer: str, cases: list[dict], leads_hash: str) -> str:
    data = {"reviewer": reviewer, "cases": cases,
            "provenance": {"source_leads_sha256": leads_hash,
                           "source_display_evidence_sha256": hashlib.sha256(ENRICHED.read_bytes()).hexdigest() if ENRICHED.is_file() else None,
                           "source_trace_cache_sha256": hashlib.sha256((ROOT / "eval/results/e1_trace_cache.jsonl").read_bytes()).hexdigest(),
                           "generation_source_commit": head(), "schema_version": 1}}
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return TEMPLATE.replace("__DATA__", encoded)


def build(out: Path = OUT) -> dict:
    raw = LEADS.read_bytes()
    cases = safe_leads()
    if len(cases) != 6 or len({c["case_id"] for c in cases}) != 6:
        raise ValueError("supplementary leads must contain six unique cases")
    out.mkdir(parents=True, exist_ok=True)
    bundles = {}
    for reviewer in ("reviewer_a", "reviewer_b"):
        html = render(reviewer, cases, sha256(raw))
        if any(token in html for token in FORBIDDEN):
            raise ValueError("forbidden label-bearing content leaked into bundle")
        path = out / f"{reviewer}.html"
        path.write_text(html, encoding="utf-8", newline="\n")
        bundles[path.name] = {"sha256": sha256(html.encode()), "reviewer": reviewer,
                              "case_count": 6, "packet_sha256": sha256(raw)}
    manifest = {"schema_version": 1, "source_leads_sha256": sha256(raw),
                "source_display_evidence_sha256": hashlib.sha256(ENRICHED.read_bytes()).hexdigest() if ENRICHED.is_file() else None,
                "source_trace_cache_sha256": hashlib.sha256((ROOT / "eval/results/e1_trace_cache.jsonl").read_bytes()).hexdigest(),
                "generation_source_commit": head(), "bundles": bundles}
    (out / "bundle_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


TEMPLATE = r'''<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>TraceGuard-DeFi — Supplementary Review</title><style>
body{font:16px/1.5 system-ui,sans-serif;margin:0;background:#f5f7f8;color:#18242d}header{position:sticky;top:0;background:#fff;border-bottom:1px solid #dbe2e6;padding:14px 24px;display:flex;justify-content:space-between}.wrap{max-width:900px;margin:28px auto;padding:0 18px}.card{background:#fff;border:1px solid #dbe2e6;border-radius:12px;padding:22px;margin:16px 0}.muted{color:#64727d}.facts{display:grid;grid-template-columns:repeat(3,1fr);gap:10px}.fact{background:#f7fafb;padding:10px;border-radius:8px}.fact small{display:block;color:#64727d}.evidence{white-space:pre-wrap;overflow:auto;background:#f8fafb;padding:12px;border-left:3px solid #c6dce4}.field{margin:14px 0}.field label{font-weight:650;display:block;margin-bottom:6px}.choice{display:flex;gap:15px;flex-wrap:wrap}.field input,.field textarea,.field select{font:inherit;width:100%;padding:9px;border:1px solid #cbd6db;border-radius:7px;box-sizing:border-box}.field textarea{min-height:80px}.nav{display:flex;justify-content:space-between;gap:10px}.button,button{font:inherit;padding:10px 14px;border:1px solid #b9c9cf;border-radius:8px;background:#fff;cursor:pointer}.primary{background:#245b73;color:#fff;border-color:#245b73}.warn{color:#8c4b1c}.hidden{display:none!important}@media(max-width:700px){.facts{grid-template-columns:1fr}}
</style></head><body><header><strong>TraceGuard-DeFi · Supplementary Review</strong><span id="who"></span></header><main class="wrap"><section id="home"><div class="card"><h1>Independent candidate review</h1><p class="muted">Review only the observable dossier. This bundle does not contain preassigned factors, system verdicts, or another reviewer’s decisions.</p><p><strong>Progress:</strong> <span id="progress"></span></p><button class="primary" onclick="start()">Start / Continue</button><button onclick="downloadDraft()">Export Draft</button><label class="button">Import Draft<input hidden type="file" accept="application/json" onchange="importDraft(event)"></label></div></section><section id="review" class="hidden"><div class="card"><div class="nav"><button onclick="prev()">← Previous</button><strong id="counter"></strong><button onclick="next()">Next →</button></div><h2 id="title"></h2><div id="facts" class="facts"></div><details open><summary>Objective evidence</summary><div id="evidence" class="evidence"></div></details><h3>Your independent assessment</h3><div id="form"></div><div id="errors" class="warn"></div><button class="primary" onclick="saveNext()">Save &amp; Next</button></div><button onclick="home()">Home</button><button class="primary" onclick="finalize()">Finalize &amp; Export JSONL</button></section></main><script type="application/json" id="data">__DATA__</script><script>
const DATA=JSON.parse(document.getElementById('data').textContent),KEY='tg-supp-'+DATA.reviewer;let state=load(),i=0;const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));function load(){try{let x=JSON.parse(localStorage.getItem(KEY)||'null');return x&&x.reviewer===DATA.reviewer?x:{reviewer:DATA.reviewer,answers:{}}}catch(e){return {reviewer:DATA.reviewer,answers:{}}}}function save(){localStorage.setItem(KEY,JSON.stringify(state));}function key(){return DATA.cases[i].case_id}function a(){return state.answers[key()]||{}}function valid(x){let factors=Array.isArray(x.root_cause)?x.root_cause:String(x.root_cause||'').split(/[, +]+/).filter(Boolean);return ['eligible','ineligible','insufficient_evidence'].includes(x.eligibility)&&x.mechanism_summary&&factors.length&&Array.isArray(x.evidence)&&x.evidence.length&&x.reviewer_note&&x.label_confidence&&(!factors.includes('f_fl')||x.flash_loan_role)&&(!factors.includes('f_orc')||x.oracle_subtype)}function start(){document.getElementById('home').classList.add('hidden');document.getElementById('review').classList.remove('hidden');render()}function home(){document.getElementById('review').classList.add('hidden');document.getElementById('home').classList.remove('hidden');refresh()}function refresh(){document.getElementById('progress').textContent=DATA.cases.filter(c=>valid(state.answers[c.case_id]||{})).length+' / '+DATA.cases.length+' complete';document.getElementById('who').textContent='Reviewer: '+DATA.reviewer}function render(){let r=DATA.cases[i],x=a();document.getElementById('counter').textContent=(i+1)+' / '+DATA.cases.length;document.getElementById('title').textContent=r.case_id;document.getElementById('facts').innerHTML=[['Transaction',r.tx_hash],['Block',r.block||'Not materialized'],['Protocol',r.protocol_name||'Unavailable'],['Date',r.date||'Unavailable']].map(q=>'<div class="fact"><small>'+esc(q[0])+'</small>'+esc(q[1])+'</div>').join('');document.getElementById('evidence').textContent=JSON.stringify(r,null,2);document.getElementById('form').innerHTML=`<div class="field"><label>Eligibility *</label><div class="choice">${['eligible','ineligible','insufficient_evidence'].map(v=>`<label><input type="radio" name="eligibility" value="${v}" ${x.eligibility===v?'checked':''}> ${v.replace('_',' ')}</label>`).join('')}</div></div>${text('mechanism_summary','Mechanism summary *',x.mechanism_summary)}${text('root_cause','Root-cause factor codes *',x.root_cause)}${select('flash_loan_role','Flash-loan role',['causal','enabling_only','absent','uncertain'],x.flash_loan_role)}${select('oracle_subtype','Oracle subtype',['external_feed','amm_reserve','internal_accounting','none','uncertain'],x.oracle_subtype)}${text('protected_entities','Protected entities (JSON, optional)',x.protected_entities)}${text('harm_assets','Harm assets (JSON, optional)',x.harm_assets)}${text('lmin_usd','Lmin USD (optional)',x.lmin_usd)}${text('valuation_source','Valuation source (optional)',x.valuation_source)}${text('evidence','Evidence references, one per line *',Array.isArray(x.evidence)?x.evidence.join('\\n'):x.evidence)}${select('label_confidence','Confidence',['high','medium','low'],x.label_confidence)}${text('reviewer_note','Reviewer note *',x.reviewer_note)}`;document.querySelectorAll('[data-k],input[name=eligibility]').forEach(el=>el.oninput=()=>{let z=a();let k=el.name||el.dataset.k;z[k]=el.type==='radio'?el.value:el.value;state.answers[key()]=z;save();refresh()})}function text(k,l,v){return `<div class="field"><label>${l}</label><textarea data-k="${k}">${esc(v)}</textarea></div>`}function select(k,l,o,v){return `<div class="field"><label>${l}</label><select data-k="${k}"><option value="">— select —</option>${o.map(q=>`<option value="${q}" ${v===q?'selected':''}>${q}</option>`).join('')}</select></div>`}function saveNext(){if(!valid(a())){document.getElementById('errors').textContent='Complete required fields and conditional fields before continuing.';return}if(i<DATA.cases.length-1){i++;render()}else{document.getElementById('errors').textContent='All cases reviewed. Finalize when ready.'}refresh()}function prev(){i=Math.max(0,i-1);render()}function next(){if(i<DATA.cases.length-1){i++;render()}}function downloadDraft(){download(JSON.stringify({schema_version:1,reviewer:DATA.reviewer,source_leads_sha256:DATA.provenance.source_leads_sha256,answers:state.answers},null,2),'supplementary-'+DATA.reviewer+'-draft.json','application/json')}function importDraft(e){let f=e.target.files[0];if(!f)return;let r=new FileReader();r.onload=()=>{try{let x=JSON.parse(r.result);if(x.reviewer!==DATA.reviewer||x.source_leads_sha256!==DATA.provenance.source_leads_sha256)throw Error('reviewer or packet mismatch');state.answers=x.answers||{};save();refresh();alert('Draft imported')}catch(err){alert('Draft rejected: '+err.message)}};r.readAsText(f)}function finalize(){refresh();if(DATA.cases.some(c=>!valid(state.answers[c.case_id]||{}))){alert('Cannot finalize: incomplete cases remain');return}let rows=DATA.cases.map(r=>Object.assign({reviewer:DATA.reviewer,case_id:r.case_id,tx_hash:r.tx_hash,packet_sha256:DATA.provenance.source_leads_sha256},state.answers[r.case_id]));download(rows.map(JSON.stringify).join('\\n')+'\\n','m6_supplementary_'+DATA.reviewer+'.jsonl','application/jsonl')}function download(s,n,t){let a=document.createElement('a');a.href=URL.createObjectURL(new Blob([s],{type:t}));a.download=n;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),500)}refresh();</script></body></html>'''


if __name__ == "__main__":
    print(json.dumps(build(), indent=2))
