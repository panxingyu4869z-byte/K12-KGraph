"""Reproducible, conservative physics import. Raw formula text never executes."""
from __future__ import annotations

import argparse
import hashlib
import json
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path

from .engine import ROOT, RuleError, read_json, validate_bundle
from .catalog import validate_catalog

BOOKS = ["8a", "8b", "9", "bx1", "bx2", "bx3", "xzxbx1", "xzxbx2", "xzxbx3"]
LABELS = {"Book", "Chapter", "Section", "Concept", "Skill", "Experiment", "Exercise"}
KNOWLEDGE = {"Concept", "Skill", "Experiment", "Exercise"}
ENDS = {
    "is_a": ({"Concept"}, {"Concept"}),
    "prerequisites_for": ({"Concept", "Skill", "Experiment"}, {"Concept", "Skill", "Experiment"}),
    "relates_to": ({"Concept"}, {"Concept"}),
    "verifies": ({"Experiment"}, {"Concept"}),
    "tests_concept": ({"Exercise"}, {"Concept"}),
    "tests_skill": ({"Exercise"}, {"Skill"}),
    "appears_in": (KNOWLEDGE, {"Section", "Chapter"}),
    "is_part_of": ({"Section", "Chapter"}, {"Chapter", "Book"}),
    "leads_to": ({"Chapter"}, {"Chapter"}),
}
# Two explicitly reviewed nodes encode the same v=v0+a*dt rule. The earlier
# section is retained; names alone never authorize a merge.
ALIASES = {"physics_bx1_rjb_cpt33": "physics_bx1_rjb_cpt31"}


def dump(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")


def location_key(value):
    prefix = value.split("_rjb")[0].removeprefix("physics_")
    if prefix not in BOOKS: raise RuleError(f"unknown physics book: {value}")
    tail = value.split("_rjb", 1)[1]
    import re
    nums = [int(x) for x in re.findall(r"\d+",tail)]
    return (BOOKS.index(prefix), *nums)


def stage(value):
    return "middle" if location_key(value)[0] < 3 else "high"


def clean_graph(graph, rules, aliases=None, catalog=None):
    aliases = dict(ALIASES if aliases is None else aliases)
    nodes, edges = graph["nodes"], graph["edges"]
    by_id = {}
    for n in nodes:
        if not isinstance(n,dict) or not isinstance(n.get("id"),str) or not n["id"].startswith("physics_") or n.get("label") not in LABELS:
            raise RuleError("invalid physics node")
        if n["id"] in by_id: raise RuleError("duplicate node ID; manual resolution required")
        by_id[n["id"]] = n
    for old,new in aliases.items():
        if old not in by_id or new not in by_id or by_id[old]["label"] != by_id[new]["label"]: raise RuleError("invalid reviewed alias")
    out_nodes = [deepcopy(n) for n in nodes if n["id"] not in aliases]
    canonical = {n["id"]:n for n in out_nodes}
    out_edges, quarantine, lineage, seen = [], [], [], {}
    def target_id(value): return aliases.get(value,value)
    def edge_problem(e):
        if e.get("type") not in ENDS: return "unknown_relation"
        if e.get("source") not in canonical: return "dangling_source"
        targets = [e["target"]] if "target" in e else [x.get("target") for x in e.get("target_name_to_ids",[])]
        if not targets: return "empty_targets"
        left,right = ENDS[e["type"]]
        if canonical[e["source"]]["label"] not in left: return "source_type"
        for target in targets:
            if target not in canonical: return "dangling_target"
            if canonical[target]["label"] not in right: return "target_type"
            if target == e["source"]: return "self_loop"
        return None
    for i, original in enumerate(edges):
        e = deepcopy(original)
        e["source"] = target_id(e.get("source"))
        if "target" in e: e["target"] = target_id(e["target"])
        for item in e.get("target_name_to_ids",[]):
            item["target"] = target_id(item.get("target"))
            if item["target"] in canonical: item["target_name"] = canonical[item["target"]]["name"]
        if e["source"] in canonical and "source_name" in e: e["source_name"] = canonical[e["source"]]["name"]
        if e.get("target") in canonical and "target_name" in e: e["target_name"] = canonical[e["target"]]["name"]
        issue = edge_problem(e)
        if issue:
            quarantine.append({"source_edge_index":i,"reason":issue,"original":original})
            continue
        token = json.dumps(e,ensure_ascii=False,sort_keys=True)
        if token in seen:
            lineage[seen[token]]["source_edge_indices"].append(i)
            continue
        seen[token] = len(out_edges)
        lineage.append({"clean_edge_index":len(out_edges),"source_edge_indices":[i]})
        out_edges.append(e)
    locations = defaultdict(set)
    for e in out_edges:
        if e["type"] == "appears_in": locations[e["source"]].add(e["target"])
    curriculum = {key:[] for key in ["primary","middle","high"]}
    for n in out_nodes:
        if n["label"] not in KNOWLEDGE: continue
        locs = sorted(locations[n["id"]],key=location_key)
        if not locs: raise RuleError(f"missing curriculum location: {n['id']}")
        curriculum[stage(locs[0])].append({"id":n["id"],"first_observed_location":locs[0],"later_references":locs[1:]})
    linked = defaultdict(list)
    for r in rules["rules"]:
        if r["concept_id"] not in canonical: raise RuleError("rule has no source node")
        if r["introduced_at"] not in locations[r["concept_id"]]: raise RuleError("rule location absent from source graph")
        if r["stage"] != stage(r["introduced_at"]): raise RuleError("rule curriculum stage mismatch")
        for source_id in r.get('source_nodes',[r['concept_id']]):
            if source_id not in canonical: raise RuleError('rule has an unknown source node')
            linked[source_id].append(r['id'])
    for record in (catalog or {}).get('records',[]):
        primary=record['source_nodes'][0]
        if record['introduced_at'] not in locations[primary] or record['stage']!=stage(record['introduced_at']):
            raise RuleError('declaration has invalid curriculum location')
        for source_id in record['source_nodes']:
            if source_id not in canonical:raise RuleError('declaration has unknown source node')
            linked[source_id].append(record['id'])
    pending = [{"id":n["id"],"name":n["name"],"original_formula":n["properties"]["formula"],"status":"pending_semantic_conversion"} for n in out_nodes if "formula" in n.get("properties",{}) and n["id"] not in linked]
    review = [
        {"id":"physics_8a_rjb_cpt11","status":"scopes_explicit","reason":"middle-school path/time scalar speed and high-school displacement/time vector velocity are separate model records; original mixed wording is retained only for provenance"},
        {"id":"physics_8a_rjb_cpt3","status":"source_wording_retained","reason":"source time definition is narrowed to work/power after upstream merging; executable rules use explicit time quantities, while this original wording remains display only"},
        {"id":"physics_8b_rjb_cpt69","status":"variants_explicit","reason":"parallel-force work and general constant-force dot product have separate executable model scopes"},
        {"id":"physics_8b_rjb_cpt40","status":"constant_precision_explicit","reason":"source rounds standard atmosphere to 101300 Pa; typed declaration uses exact standard 101325 Pa and retains the rounded source text"},
        {"id":"physics_xzxbx1_rjb_cpt18","status":"model_replaced_explicitly","reason":"source finite mass-change expression is a local first-order approximation; executable ideal rocket model uses endpoint masses and the logarithmic relation under stated assumptions"},
        {"id":"physics_xzxbx3_rjb_cpt125","status":"products_completed","reason":"beta-minus products include electron antineutrino; nucleon, charge and electron-lepton numbers are checked separately"},
    ]
    report = {
        "input":{"nodes":len(nodes),"edges":len(edges),"formula_nodes":sum("formula" in n.get("properties",{}) for n in nodes)},
        "output":{"nodes":len(out_nodes),"edges":len(out_edges),"quarantined_edges":len(quarantine),"merged_nodes":len(aliases),"deduplicated_edges":sum(len(x['source_edge_indices'])-1 for x in lineage)},
        "quarantine_reasons":dict(Counter(x["reason"] for x in quarantine)),
        "curriculum_counts":{k:len(v) for k,v in curriculum.items()},
        "rules":{"ready":len(rules["rules"]),"declarations":len((catalog or {}).get('records',[])),"covered_canonical_formula_nodes":len(linked),"pending_formula_nodes":len(pending),"by_stage":dict(Counter(r['stage'] for r in rules['rules']))},
        "scope":"first_observed_location is relative to this already-merged nine-book dataset; it is not proof of the earliest historical introduction",
    }
    provenance = {"aliases":[{"source_id":old,"canonical_id":new,"basis":"identical reviewed constant-acceleration velocity relation; ch2_s2 precedes ch2_s3","original_node":by_id[old]} for old,new in aliases.items()],"edges":lineage}
    return {"graph": {"nodes":out_nodes,"edges":out_edges},"curriculum":curriculum,"quarantine":quarantine,"provenance":provenance,"pending":pending,"review":review,"report":report,"content_links":dict(sorted(linked.items()))}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input",type=Path,required=True)
    parser.add_argument("--source",type=Path,required=True)
    parser.add_argument("--output",type=Path,default=ROOT / "knowledge/physics/cleaned")
    args = parser.parse_args()
    if args.input.resolve().is_relative_to(args.output.resolve()): raise RuleError("raw input must be outside output directory")
    rules = read_json(ROOT / "knowledge/physics/rules.json")
    validate_bundle(rules)
    catalog=read_json(ROOT/'knowledge/physics/catalog.json')
    validate_catalog(catalog,rules)
    raw = args.input.read_bytes()
    result = clean_graph(read_json(args.input),rules,catalog=catalog)
    source = read_json(args.source)
    digest = hashlib.sha256(raw).hexdigest()
    if source.get('sha256') != digest:
        raise RuleError('raw data does not match the pinned source SHA-256')
    source["sha256"] = digest
    source["bytes"] = len(raw)
    result["report"]["source"] = source
    result["report"]["raw_formula_text_executable"] = False
    result["report"]["rule_index"] = {k:[r["id"] for r in rules["rules"] if r["stage"] == k] for k in ["primary","middle","high"]}
    result["report"]["declaration_index"] = {k:[r["id"] for r in catalog["records"] if r["stage"] == k] for k in ["primary","middle","high"]}
    for name,value in result.items():
        if name == 'curriculum':
            for level,records in value.items():
                dump(args.output / 'curriculum' / f'{level}.json',records)
        else:
            dump(args.output / f"{name}.json",value)
    print(json.dumps(result["report"],ensure_ascii=False,indent=2))


if __name__ == "__main__":
    main()
