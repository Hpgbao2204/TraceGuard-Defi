"""Build self-contained, blinded offline M5 review bundles."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PACKETS = ROOT / "corpus/annotations/review_packets"
DISPLAY_EVIDENCE = ROOT / "corpus/annotations/review_bundles/display_evidence.json"
TRACE_CACHE = ROOT / "eval/results/e1_trace_cache.jsonl"
OUT = ROOT / "corpus/annotations/review_bundles"
FORBIDDEN = {
    "gt_factors", "root_cause_gt", "attack_type", "blind_candidate_factors",
    "supported_from_cache", "trace_evidence", "system_verdict", "ground_truth",
    "adjudicated_result", "reviewer_votes",
}
E4_DISPLAY = ("packet_schema_version", "reviewer", "case_id", "tx_hash", "block",
              "fixed_set_sha256", "packet_type", "packet_sha256")
HARD_DISPLAY = ("packet_schema_version", "reviewer", "incident_case_id",
                "incident_tx_hash", "incident_block", "candidate_tx_hash",
                "candidate_block", "preregistered_window_blocks", "within_window",
                "fixed_set_sha256", "packet_type", "packet_sha256")


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def git_head() -> str | None:
    try:
        return subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def packet_digest(rows: list[dict]) -> str:
    values = [{k: v for k, v in row.items() if k != "packet_sha256"} for row in rows]
    return hashlib.sha256(json.dumps(values, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()).hexdigest()


def safe_rows(rows: list[dict], fields: tuple[str, ...]) -> list[dict]:
    result = []
    for row in rows:
        if FORBIDDEN & set(row):
            raise ValueError("forbidden field in packet: " + ",".join(sorted(FORBIDDEN & set(row))))
        result.append({key: row.get(key) for key in fields})
    return result


def _trace_index() -> dict[str, dict]:
    if not TRACE_CACHE.is_file():
        return {}
    result = {}
    for row in load_jsonl(TRACE_CACHE):
        tx = str(row.get("tx_hash", "")).lower()
        trace = row.get("trace") or {}
        if tx and isinstance(trace, dict):
            result[tx] = trace
    return result


def _call_summary(call: dict) -> dict:
    input_data = str(call.get("input") or "")
    return {
        "from": call.get("from"),
        "to": call.get("to"),
        "selector": input_data[:10] if input_data.startswith("0x") else None,
        "value": call.get("value"),
        "gas_used": call.get("gasUsed", call.get("gas_used")),
        "type": call.get("type"),
        "calls": [_call_summary(child) for child in (call.get("calls") or [])
                   if isinstance(child, dict)],
        "log_count": len(call.get("logs") or []),
    }


def _call_addresses(call: dict) -> set[str]:
    if not isinstance(call, dict):
        return set()
    addresses = {str(call["to"]).lower()} if call.get("to") else set()
    for child in call.get("calls") or []:
        addresses.update(_call_addresses(child))
    return addresses


def _hard_display(rows: list[dict]) -> list[dict]:
    traces = _trace_index()
    result = []
    for row in rows:
        tx = str(row.get("candidate_tx_hash", "")).lower()
        trace = traces.get(tx)
        display = {key: row.get(key) for key in HARD_DISPLAY}
        if trace:
            display["transaction_summary"] = {
                "from": trace.get("from"), "to": trace.get("to"),
                "value": trace.get("value"),
                "gas_used": (trace.get("tree") or {}).get("gasUsed", trace.get("gas_used")),
                "status": trace.get("status"),
            }
            tree = trace.get("tree")
            display["observed_call_tree"] = _call_summary(tree) if isinstance(tree, dict) else {}
            display["observed_contracts"] = sorted(_call_addresses(tree))
            display["evidence_source"] = {
                "artifact": "eval/results/e1_trace_cache.jsonl",
                "field": "trace.tree",
                "tx_hash": row.get("candidate_tx_hash"),
            }
        else:
            display["evidence_unavailable"] = ["candidate call trace not materialized in local cache"]
        result.append(display)
    return result


def validate_packet(rows: list[dict], reviewer: str, expected: int, packet_key: str,
                    manifest: dict) -> str:
    if len(rows) != expected or not rows:
        raise ValueError(f"{packet_key}: expected {expected} rows, got {len(rows)}")
    if {row.get("reviewer") for row in rows} != {reviewer}:
        raise ValueError(f"{packet_key}: reviewer identity is not constant")
    expected_hash = manifest.get("packet_hashes", {}).get(packet_key)
    actual = rows[0].get("packet_sha256")
    if not expected_hash or actual != expected_hash or any(row.get("packet_sha256") != actual for row in rows):
        raise ValueError(f"{packet_key}: packet hash mismatch")
    return actual


def html_bundle(reviewer: str, e4: list[dict], hard: list[dict], manifest: dict,
                packets_dir: Path = PACKETS) -> str:
    dossier = json.loads(DISPLAY_EVIDENCE.read_text(encoding="utf-8")) if DISPLAY_EVIDENCE.is_file() else {"cases": []}
    dossier_by_case = {row.get("case_id"): row for row in dossier.get("cases", [])}
    safe_dossier = [{key: value for key, value in row.items()
                     if key not in FORBIDDEN} for row in
                    (dossier_by_case.get(row.get("case_id"), {}) for row in e4)]
    if len(safe_dossier) != len(e4) or any(not row for row in safe_dossier):
        raise ValueError("display evidence must cover every E4 packet")
    data = {
        "reviewer": reviewer,
        "e4": e4,
        "hard": hard,
        "display": {"e4": safe_dossier, "hard": _hard_display(hard)},
        "provenance": {"packet_manifest_sha256": hashlib.sha256((packets_dir / "packet_manifest.json").read_bytes()).hexdigest(), "generated_from": git_head()},
    }
    encoded = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/")
    return TEMPLATE.replace("__EMBEDDED_DATA__", encoded)


def build(out_dir: Path = OUT, packets_dir: Path = PACKETS) -> dict:
    manifest = json.loads((packets_dir / "packet_manifest.json").read_text(encoding="utf-8"))
    out_dir.mkdir(parents=True, exist_ok=True)
    bundles = {}
    for reviewer in ("reviewer_a", "reviewer_b"):
        e4 = load_jsonl(packets_dir / f"e4_{reviewer}.jsonl")
        hard = load_jsonl(packets_dir / f"hard_negatives_{reviewer}.jsonl")
        e4_hash = validate_packet(e4, reviewer, 20, f"e4_{reviewer}", manifest)
        hard_hash = validate_packet(hard, reviewer, len(hard), f"hard_negatives_{reviewer}", manifest)
        content = html_bundle(reviewer, e4, hard, manifest, packets_dir)
        content = content.replace(
            '</label></div></section><section id="review"',
            '</label><button onclick="finalize()">Finalize &amp; Export JSONL</button></div></section><section id="review"')
        content = content.replace(
            "function importDraft(ev){let f=ev.target.files[0];if(!f)return;let rd=new FileReader();rd.onload=()=>{try{let x=JSON.parse(rd.result);if(x.reviewer!==DATA.reviewer)throw Error('reviewer mismatch');state=x.answers;if(!state.reviewer)state.reviewer=DATA.reviewer;save();refresh();alert('Draft imported.')}catch(e){alert('Draft rejected: '+e.message)}};rd.readAsText(f)}",
            "function finalize(){refresh();let e=DATA.e4.filter((_,i)=>valid('e4',i)).length,h=DATA.hard.filter((_,i)=>valid('hard',i)).length;if(e!==DATA.e4.length||h!==DATA.hard.length){alert('Cannot finalize: '+(DATA.e4.length-e)+' E4 and '+(DATA.hard.length-h)+' hard-negative cases remain incomplete.');return}let rows=(m)=>DATA[m].map(r=>Object.assign({},r,state[m][m==='e4'?r.case_id:r.candidate_tx_hash]||{}));download(new Blob([rows('e4').map(JSON.stringify).join('\\n')+'\\n'],{type:'application/jsonl'}),'e4_'+DATA.reviewer+'.jsonl');download(new Blob([rows('hard').map(JSON.stringify).join('\\n')+'\\n'],{type:'application/jsonl'}),'hard_negatives_'+DATA.reviewer+'.jsonl');alert('JSONL files exported.')}\nfunction importDraft(ev){let f=ev.target.files[0];if(!f)return;let rd=new FileReader();rd.onload=()=>{try{let x=JSON.parse(rd.result);if(x.reviewer!==DATA.reviewer)throw Error('reviewer mismatch');if(x.packet_manifest_sha256!==DATA.provenance.packet_manifest)throw Error('packet manifest mismatch');if(!x.answers||typeof x.answers!==\'object\')throw Error('invalid draft');state=x.answers;if(!state.reviewer)state.reviewer=DATA.reviewer;save();refresh();alert('Draft imported.')}catch(e){alert('Draft rejected: '+e.message)}};rd.readAsText(f)}")
        compact = r'''function e4FormCompact(a){return `<div class="form"><div class="notice"><strong>Your review</strong><br>Assess eligibility, the plausible factor, and whether an intervention corresponds to it. The replay system—not you—produces CAUSE / NO_EFFECT / INCONCLUSIVE.</div><div class="field"><label>Eligibility *</label><div class="choice"><label><input type="radio" name="eligibility" value="eligible" ${a.eligibility==='eligible'?'checked':''}> eligible</label><label><input type="radio" name="eligibility" value="ineligible" ${a.eligibility==='ineligible'?'checked':''}> ineligible</label></div></div>${text('eligibility_reason','Why?',a.eligibility_reason,true)}${jsonText('root_cause','Plausible factor codes (JSON array)',a.root_cause,a.eligibility==='eligible')}${jsonText('intervention_candidates','Intervention candidates (JSON array; include supported only when justified)',a.intervention_candidates,a.eligibility==='eligible')}${jsonText('evidence','Evidence references (JSON array)',a.evidence,true)}${text('reviewer_note','Reasoning note',a.reviewer_note,true)}<details><summary>Protocol details required for eligible cases</summary>${text('security_objective_kind','Security objective kind',a.security_objective_kind,a.eligibility==='eligible')}${text('security_objective_statement','Security objective statement',a.security_objective_statement,a.eligibility==='eligible')}${text('security_objective_reference','Security objective reference',a.security_objective_reference,a.eligibility==='eligible')}${jsonText('victims','Victims (JSON array)',a.victims,a.eligibility==='eligible')}${jsonText('token_prices','Token prices (JSON object)',a.token_prices,a.eligibility==='eligible')}${number('lmin_usd','Lmin USD',a.lmin_usd,a.eligibility==='eligible')}${text('valuation_source','Valuation source',a.valuation_source,a.eligibility==='eligible')}${jsonText('enabling_primitives','Enabling primitives (JSON array)',a.enabling_primitives,a.eligibility==='eligible')}${jsonText('causal_calls','Causal calls (JSON array)',a.causal_calls,a.eligibility==='eligible')}${text('label_confidence','Label confidence',a.label_confidence,true)}</details></div>`}'''
        compact = compact.replace("${jsonText('token_prices','Token prices (JSON object)',a.token_prices,a.eligibility==='eligible')}", "${tokenPrices(a.token_prices,a.eligibility==='eligible')}")
        compact = compact.replace("${jsonText('root_cause','Plausible factor codes (JSON array)',a.root_cause,a.eligibility==='eligible')}", "${factorChoices(a.root_cause,a.eligibility==='eligible')}")
        compact = compact.replace("${jsonText('evidence','Evidence references (JSON array)',a.evidence,true)}", "${evidenceRefs(a.evidence,true)}")
        compact += r'''function tokenPrices(v,req){let entries=Object.entries(v&&typeof v==='object'&&!Array.isArray(v)?v:{});if(!entries.length)entries=[['','']];return `<div class="field"><label>Token prices${req?' *':''}</label><div class="repeat" data-token-prices>${entries.map(([token,price])=>`<div class="repeat-row"><input data-price-token placeholder="Token/address" value="${esc(token)}"><input data-price-value type="number" step="any" placeholder="USD per token" value="${esc(price)}"><button type="button" data-price-remove>Remove</button></div>`).join('')}</div><button type="button" data-price-add>Add token price</button><small>Enter each asset and its USD price; cite the source in valuation source/evidence.</small></div>`}'''
        compact += r'''function factorChoices(v,req){let opts=[['f_fl','Flash liquidity'],['f_orc','Oracle'],['f_auth','Authorization'],['f_re','Reentrancy'],['f_other','Other'],['unknown','Unknown']];let chosen=Array.isArray(v)?v:[];return `<div class="field"><label>Plausible causal factor${req?' *':''}</label><div class="choice">${opts.map(([code,label])=>`<label><input type="checkbox" data-factor="${code}" ${chosen.includes(code)?'checked':''}> ${code} — ${label}</label>`).join('')}</div></div>`}function evidenceRefs(v,req){let values=Array.isArray(v)?v:[];if(!values.length)values=[''];return `<div class="field"><label>Evidence references${req?' *':''}</label><div class="repeat" data-evidence-refs>${values.map(value=>`<div class="repeat-row"><input data-evidence-value placeholder="Artifact path, tx hash, or citation" value="${esc(typeof value==='string'?value:value&&value.reference||'')}"><button type="button" data-evidence-remove>Remove</button></div>`).join('')}</div><button type="button" data-evidence-add>Add evidence reference</button></div>`}'''
        compact += r'''document.addEventListener('change',e=>{if(e.target.matches('[data-factor]')){let a=answer();a.root_cause=[...document.querySelectorAll('[data-factor]:checked')].map(x=>x.dataset.factor);state.e4[rowKey()]=a;save();}});document.addEventListener('input',e=>{if(e.target.matches('[data-price-token],[data-price-value]')){let a=answer(),out={};document.querySelectorAll('[data-token-prices] .repeat-row').forEach(row=>{let k=row.querySelector('[data-price-token]').value.trim(),v=row.querySelector('[data-price-value]').value;if(k&&v!=='')out[k]=Number(v)});a.token_prices=out;state.e4[rowKey()]=a;save()}if(e.target.matches('[data-evidence-value]')){let a=answer();a.evidence=[...document.querySelectorAll('[data-evidence-refs] [data-evidence-value]')].map(x=>x.value.trim()).filter(Boolean);state.e4[rowKey()]=a;save()}});document.addEventListener('click',e=>{if(e.target.matches('[data-price-add]')){let box=document.querySelector('[data-token-prices]');box.insertAdjacentHTML('beforeend','<div class="repeat-row"><input data-price-token placeholder="Token/address"><input data-price-value type="number" step="any" placeholder="USD per token"><button type="button" data-price-remove>Remove</button></div>')}if(e.target.matches('[data-price-remove]')){e.target.closest('.repeat-row').remove();e.target.dispatchEvent(new Event('input',{bubbles:true}))}if(e.target.matches('[data-evidence-add]'))document.querySelector('[data-evidence-refs]').insertAdjacentHTML('beforeend','<div class="repeat-row"><input data-evidence-value placeholder="Artifact path, tx hash, or citation"><button type="button" data-evidence-remove>Remove</button></div>');if(e.target.matches('[data-evidence-remove]'))e.target.closest('.repeat-row').remove()});'''
        content = content.replace("</script></body></html>", compact + "</script></body></html>")
        path = out_dir / f"{reviewer}.html"
        path.write_text(content, encoding="utf-8", newline="\n")
        bundles[path.name] = {"sha256": hashlib.sha256(content.encode()).hexdigest(),
                              "reviewer": reviewer, "e4_packet_sha256": e4_hash,
                              "hard_packet_sha256": hard_hash}
    result = {"schema_version": 1, "source_packet_manifest_sha256": hashlib.sha256((packets_dir / "packet_manifest.json").read_bytes()).hexdigest(),
              "generation_source_commit": git_head(), "bundles": bundles}
    (out_dir / "bundle_manifest.json").write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


TEMPLATE = r'''<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>TraceGuard-DeFi — Independent Human Review</title>
<style>
:root{--ink:#17212b;--muted:#687583;--paper:#f6f7f8;--surface:#fff;--line:#dfe5e9;--accent:#245b73;--focus:#8ab8c9;--warn:#9a6518;--ok:#34735b;font:15px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}*{box-sizing:border-box}body{margin:0;background:var(--paper);color:var(--ink)}header{position:sticky;top:0;z-index:2;background:rgba(246,247,248,.96);border-bottom:1px solid var(--line);padding:14px max(20px,calc((100vw - 1120px)/2));display:flex;justify-content:space-between;align-items:center;gap:16px}.brand{font-weight:700;letter-spacing:-.02em}.brand small{display:block;color:var(--muted);font-weight:400;font-size:12px}.wrap{max-width:1120px;margin:0 auto;padding:32px 20px 72px}.hero{display:flex;justify-content:space-between;gap:24px;align-items:end;margin-bottom:28px}.eyebrow{text-transform:uppercase;letter-spacing:.12em;font-size:11px;color:var(--accent);font-weight:700}.hero h1{font-size:30px;line-height:1.15;margin:7px 0}.hero p{color:var(--muted);max-width:650px;margin:0}.pill{border:1px solid var(--line);background:var(--surface);border-radius:999px;padding:7px 12px;color:var(--muted);white-space:nowrap;font-size:13px}.notice{background:#eef5f6;border:1px solid #c9dfe4;border-radius:12px;padding:14px 16px;margin-bottom:24px}.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px}.card{background:var(--surface);border:1px solid var(--line);border-radius:14px;padding:20px;box-shadow:0 1px 2px rgba(20,35,45,.04)}.card h2{font-size:18px;margin:0 0 5px}.meta{color:var(--muted);font-size:13px}.progress{height:7px;background:#e7ecee;border-radius:8px;overflow:hidden;margin:18px 0 14px}.bar{height:100%;background:var(--accent);width:0}.actions{display:flex;gap:8px;flex-wrap:wrap}button,.button{font:inherit;cursor:pointer;border:1px solid var(--line);background:var(--surface);border-radius:9px;padding:10px 14px;color:var(--ink);min-height:40px}button:hover,.button:hover{border-color:var(--focus);background:#f5fafb}button:focus-visible,input:focus-visible,textarea:focus-visible,select:focus-visible{outline:3px solid rgba(138,184,201,.45);outline-offset:1px}.primary{background:var(--accent);border-color:var(--accent);color:#fff}.danger{color:#8c3f35}.hidden{display:none!important}.topline{display:flex;justify-content:space-between;align-items:center;gap:12px;margin-bottom:18px}.case-title{font-size:23px;margin:4px 0}.facts{display:grid;grid-template-columns:repeat(3,1fr);gap:10px;margin:16px 0}.fact{padding:11px 12px;background:#f8fafb;border-radius:9px}.fact label{display:block;color:var(--muted);font-size:11px;text-transform:uppercase;letter-spacing:.08em}.fact code{word-break:break-all;font-size:12px}.section{margin-top:18px}.section h3{font-size:12px;text-transform:uppercase;letter-spacing:.1em;color:var(--muted);margin:0 0 10px}.evidence{border-left:3px solid #c9dfe4;padding:10px 14px;background:#fbfcfc;border-radius:0 9px 9px 0}.evidence dl{display:grid;grid-template-columns:170px 1fr;gap:5px 14px;margin:0}.evidence dt{color:var(--muted);font-size:13px}.evidence dd{margin:0;word-break:break-word}.form{display:grid;gap:14px}.field{display:grid;gap:6px}.field label{font-weight:600}.field small,.help{color:var(--muted);font-size:12px}.field input,.field textarea,.field select{font:inherit;border:1px solid var(--line);border-radius:8px;padding:9px 10px;background:#fcfdfd;width:100%}.field textarea{min-height:76px;resize:vertical}.choice{display:flex;gap:14px;flex-wrap:wrap}.choice label{font-weight:400;display:flex;gap:7px;align-items:center}.repeat{display:grid;gap:8px}.repeat-row{display:grid;grid-template-columns:1fr 1fr auto;gap:8px}.error{color:#9b4338;font-size:12px}.footer-nav{display:flex;justify-content:space-between;margin-top:22px}.summary{background:#fff8e8;border:1px solid #ecd8ae;border-radius:10px;padding:12px 14px}.kbd{font-family:ui-monospace,monospace;border:1px solid var(--line);border-bottom-width:2px;border-radius:4px;padding:1px 5px;background:#fff;font-size:12px}@media(max-width:760px){.grid,.facts{grid-template-columns:1fr}.hero{display:block}.hero .pill{display:inline-block;margin-top:14px}.evidence dl{grid-template-columns:1fr}.repeat-row{grid-template-columns:1fr}.wrap{padding-top:22px}}
</style></head><body><header><div class="brand">TraceGuard-DeFi<small>Independent Human Review · offline bundle</small></div><div id="saveStatus" class="pill">Not started</div></header><main class="wrap"><section id="home"><div class="hero"><div><div class="eyebrow">Blinded review workspace</div><h1>Evidence, then judgement.</h1><p>Review the observable record independently. System verdicts, ground truth, and the other reviewer’s decisions are not included in this bundle.</p></div><div class="pill">Reviewer: <strong id="reviewerName"></strong></div></div><div class="notice"><strong>Review policy</strong><br>This interface does not show causal verdicts or ground-truth labels. Do not exchange decisions with the other reviewer until both submissions are finalized.</div><div class="grid"><div class="card"><h2>E4 detailed review</h2><div class="meta"><span id="e4Count">0</span> / <span id="e4Total"></span> complete</div><div class="progress"><div id="e4Bar" class="bar"></div></div><button class="primary" onclick="start('e4')">Start / Continue E4</button></div><div class="card"><h2>Hard-negative review</h2><div class="meta"><span id="hardCount">0</span> / <span id="hardTotal"></span> complete</div><div class="progress"><div id="hardBar" class="bar"></div></div><button class="primary" onclick="start('hard')">Start / Continue hard negatives</button></div></div><div class="actions" style="margin-top:18px"><button onclick="exportDraft()">Export Draft</button><label class="button">Import Draft<input id="draftInput" type="file" accept="application/json" hidden onchange="importDraft(event)"></label></div></section><section id="review" class="hidden"><div class="topline"><div><div id="modeLabel" class="eyebrow"></div><h2 id="caseTitle" class="case-title"></h2></div><div id="caseIndex" class="pill"></div></div><div id="caseBody"></div><div class="footer-nav"><button onclick="previous()">← Previous</button><div class="actions"><button onclick="goHome()">Home</button><button class="primary" onclick="next()">Next →</button></div></div></section></main>
<script type="application/json" id="embedded-data">__EMBEDDED_DATA__</script><script>
const DATA=JSON.parse(document.getElementById('embedded-data').textContent), KEY='tg-review-'+DATA.reviewer;let state=load(),mode='e4',index=0;
const e4Fields=['eligibility','eligibility_reason','security_objective_kind','security_objective_statement','security_objective_reference','victims','token_prices','lmin_usd','valuation_source','root_cause','enabling_primitives','causal_calls','intervention_candidates','label_confidence','evidence','reviewer_note'];
const hardFields=['same_protocol','legitimate_mechanism','label','rationale','evidence','reviewer_note'];
function load(){try{let x=JSON.parse(localStorage.getItem(KEY)||'null');return x&&x.reviewer===DATA.reviewer?x:{reviewer:DATA.reviewer,e4:{},hard:{}}}catch(e){return {reviewer:DATA.reviewer,e4:{},hard:{}}}}
function save(){localStorage.setItem(KEY,JSON.stringify(state));document.getElementById('saveStatus').textContent='Saved '+new Date().toLocaleTimeString()}
function row(){return DATA[mode][index]}
function answer(){return state[mode][rowKey()]||{}}
function rowKey(){return mode==='e4'?row().case_id:row().candidate_tx_hash}
function display(){return DATA.display[mode][index]}
function start(m){mode=m;index=firstIncomplete(m);document.getElementById('home').classList.add('hidden');document.getElementById('review').classList.remove('hidden');render()}
function firstIncomplete(m){let a=DATA[m];let i=a.findIndex((_,n)=>!valid(m,n));return i<0?0:i}
function goHome(){document.getElementById('review').classList.add('hidden');document.getElementById('home').classList.remove('hidden');refresh()}
function esc(x){return String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]))}
function jsonField(v){return JSON.stringify(v??[],null,2)}
function render(){let r=row(),a=answer();document.getElementById('modeLabel').textContent=mode==='e4'?'E4 detailed review':'Hard-negative rapid review';document.getElementById('caseTitle').textContent=mode==='e4'?r.case_id:'Hard negative '+(index+1);document.getElementById('caseIndex').textContent=(index+1)+' / '+DATA[mode].length;let d=display();let facts=Object.entries(d).filter(([k])=>!['packet_schema_version','reviewer','fixed_set_sha256','packet_type','packet_sha256'].includes(k)).map(([k,v])=>`<div class="fact"><label>${esc(k.replaceAll('_',' '))}</label><code>${esc(typeof v==='object'?JSON.stringify(v):v)}</code></div>`).join('');let evidence=`<div class="evidence"><dl>${Object.entries(d).map(([k,v])=>`<dt>${esc(k.replaceAll('_',' '))}</dt><dd>${esc(typeof v==='object'?JSON.stringify(v):v)}</dd>`).join('')}</dl><p class="help">Source: frozen packet identity and objective queue metadata. No interpretation is supplied.</p></div>`;document.getElementById('caseBody').innerHTML=`<div class="card"><div class="facts">${facts}</div><details class="section"><summary>Packet references and objective facts</summary>${evidence}</details><div class="section"><h3>Your assessment</h3>${mode==='e4'?e4FormCompact(a):hardForm(a)}<div id="errors" class="error"></div></div></div>`;bind();}
function e4Form(a){return `<div class="form"><div class="field"><label>Eligibility</label><div class="choice"><label><input type="radio" name="eligibility" value="eligible" ${a.eligibility==='eligible'?'checked':''}> eligible</label><label><input type="radio" name="eligibility" value="ineligible" ${a.eligibility==='ineligible'?'checked':''}> ineligible</label></div></div>${text('eligibility_reason','Eligibility reason',a.eligibility_reason,true)}${text('security_objective_kind','Security objective kind',a.security_objective_kind,a.eligibility==='eligible')}${text('security_objective_statement','Security objective statement',a.security_objective_statement,a.eligibility==='eligible')}${text('security_objective_reference','Security objective reference',a.security_objective_reference,a.eligibility==='eligible')}${jsonText('victims','Victims (one JSON array)',a.victims,a.eligibility==='eligible')}${jsonText('token_prices','Token prices (JSON object)',a.token_prices,a.eligibility==='eligible')}${number('lmin_usd','Lmin USD',a.lmin_usd,a.eligibility==='eligible')}${text('valuation_source','Valuation source',a.valuation_source,a.eligibility==='eligible')}${jsonText('root_cause','Root cause codes (JSON array)',a.root_cause,a.eligibility==='eligible')}${jsonText('enabling_primitives','Enabling primitives (JSON array)',a.enabling_primitives,a.eligibility==='eligible')}${jsonText('causal_calls','Causal calls (JSON array)',a.causal_calls,a.eligibility==='eligible')}${jsonText('intervention_candidates','Intervention candidates (JSON array; include applicability supported only when you judge it)',a.intervention_candidates,a.eligibility==='eligible')}${text('label_confidence','Label confidence',a.label_confidence,true)}${jsonText('evidence','Evidence references (JSON array)',a.evidence,true)}${text('reviewer_note','Reviewer note',a.reviewer_note,true)}`}
function hardForm(a){return `<div class="form"><div class="field"><label>Same protocol</label><div class="choice"><label><input type="radio" name="same_protocol" value="true" ${a.same_protocol===true?'checked':''}> true</label><label><input type="radio" name="same_protocol" value="false" ${a.same_protocol===false?'checked':''}> false</label></div></div><div class="field"><label>Within window</label><input value="${esc(row().within_window?'YES':'NO')}" disabled></div>${select('legitimate_mechanism','Legitimate mechanism',['arbitrage','liquidation','migration','governance_execution','router_aggregation','flash_liquidity','other','unknown'],a.legitimate_mechanism,true)}${select('label','Classification',['verified_benign','exclude_uncertain','security_incident'],a.label,true)}${text('rationale','Rationale',a.rationale,true)}${jsonText('evidence','Evidence references (JSON array)',a.evidence,true)}${text('reviewer_note','Reviewer note',a.reviewer_note,true)}<p class="help">Shortcuts: <span class="kbd">1</span> benign · <span class="kbd">2</span> uncertain · <span class="kbd">3</span> incident · <span class="kbd">N</span> next · <span class="kbd">P</span> previous · <span class="kbd">E</span> evidence</p>`}
function text(k,l,v,req){return `<div class="field"><label>${esc(l)}${req?' *':''}</label><textarea data-k="${k}">${esc(v)}</textarea></div>`}function number(k,l,v,req){return `<div class="field"><label>${esc(l)}${req?' *':''}</label><input type="number" step="any" data-k="${k}" value="${v===null||v===undefined?'':esc(v)}"></div>`}function jsonText(k,l,v,req){return `<div class="field"><label>${esc(l)}${req?' *':''}</label><textarea data-json="${k}">${esc(jsonField(v))}</textarea><small>Use structured JSON; the portal exports the existing protocol representation unchanged.</small></div>`}function select(k,l,opts,v,req){return `<div class="field"><label>${esc(l)}${req?' *':''}</label><select data-k="${k}"><option value="">— select —</option>${opts.map(x=>`<option ${x===v?'selected':''} value="${x}">${x}</option>`).join('')}</select></div>`}
function bind(){document.querySelectorAll('[data-k]').forEach(x=>x.oninput=()=>{let a=answer();a[x.dataset.k]=x.type==='number'?(x.value===''?null:Number(x.value)):x.value;state[mode][rowKey()]=a;save();});document.querySelectorAll('[data-json]').forEach(x=>x.oninput=()=>{try{let a=answer();a[x.dataset.json]=JSON.parse(x.value);state[mode][rowKey()]=a;save();document.getElementById('errors').textContent=''}catch(e){document.getElementById('errors').textContent='JSON needs to be valid before leaving this case.'}});document.querySelectorAll('input[type=radio]').forEach(x=>x.onchange=()=>{let a=answer();a[x.name]=x.value==='true'?true:x.value==='false'?false:x.value;state[mode][rowKey()]=a;save();render()})}
function valid(m,i){let r=DATA[m][i],a=state[m][m==='e4'?r.case_id:r.candidate_tx_hash]||{};if(m==='e4'){if(!['eligible','ineligible'].includes(a.eligibility)||!a.eligibility_reason||!a.reviewer_note||!Array.isArray(a.evidence)||!a.evidence.length)return false;if(a.eligibility==='eligible'){let req=['security_objective_kind','security_objective_statement','security_objective_reference','victims','token_prices','valuation_source','root_cause','causal_calls','intervention_candidates'];if(req.some(k=>!a[k])||a.lmin_usd===null||a.lmin_usd===undefined||!Array.isArray(a.intervention_candidates)||!a.intervention_candidates.some(x=>x&&x.applicability==='supported'))return false}return true}return [true,false].includes(a.same_protocol)&&a.legitimate_mechanism&&['verified_benign','exclude_uncertain','security_incident'].includes(a.label)&&a.rationale&&Array.isArray(a.evidence)&&a.evidence.length&&a.reviewer_note}
function next(){if(!valid(mode,index)){document.getElementById('errors').textContent='Complete the required fields before continuing.';return}index=Math.min(DATA[mode].length-1,index+1);render()}function previous(){index=Math.max(0,index-1);render()}function refresh(){for(const m of ['e4','hard']){let n=DATA[m].filter((_,i)=>valid(m,i)).length;document.getElementById(m+'Count').textContent=n;document.getElementById(m+'Total').textContent=DATA[m].length;document.getElementById(m+'Bar').style.width=(n/DATA[m].length*100)+'%'}}
function exportDraft(){let blob=new Blob([JSON.stringify({schema_version:1,reviewer:DATA.reviewer,packet_manifest_sha256:DATA.provenance.packet_manifest_sha256,answers:state},null,2)],{type:'application/json'});download(blob,'traceguard-'+DATA.reviewer+'-draft.json')}
function importDraft(ev){let f=ev.target.files[0];if(!f)return;let rd=new FileReader();rd.onload=()=>{try{let x=JSON.parse(rd.result);if(x.reviewer!==DATA.reviewer)throw Error('reviewer mismatch');state=x.answers;if(!state.reviewer)state.reviewer=DATA.reviewer;save();refresh();alert('Draft imported.')}catch(e){alert('Draft rejected: '+e.message)}};rd.readAsText(f)}
function download(blob,name){let a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download=name;a.click();setTimeout(()=>URL.revokeObjectURL(a.href),500)}
document.addEventListener('keydown',e=>{if(document.getElementById('review').classList.contains('hidden'))return;if(mode==='hard'&&!e.target.matches('input,textarea,select')){if(['1','2','3'].includes(e.key)){let v={1:'verified_benign',2:'exclude_uncertain',3:'security_incident'}[e.key];let a=answer();a.label=v;state.hard[rowKey()]=a;save();render()}if(e.key.toLowerCase()==='n')next();if(e.key.toLowerCase()==='p')previous();if(e.key.toLowerCase()==='e'){let d=document.querySelector('details');d.open=!d.open}}});refresh();document.getElementById('reviewerName').textContent=DATA.reviewer;
</script></body></html>'''


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-dir", type=Path, default=OUT)
    parser.add_argument("--packets-dir", type=Path, default=PACKETS)
    args = parser.parse_args()
    print(json.dumps(build(args.out_dir, args.packets_dir), indent=2))
