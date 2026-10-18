"""Closed AST interpreter with separate structural, dimensional and model checks.

Display strings are never parsed. Vectors are Cartesian triples in one declared
frame. This first version evaluates algebraic rules, not differential equations.
"""
from __future__ import annotations

import json
import math
from copy import deepcopy
from fractions import Fraction
from pathlib import Path

import sympy as sp
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
ZERO = (0,) * 7


class RuleError(ValueError):
    pass


def read_json(path):
    def reject(value):
        raise RuleError(f"non-finite JSON constant: {value}")
    return json.loads(Path(path).read_text(encoding="utf-8"), parse_constant=reject)


def number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise RuleError("a finite real number is required")
    return value


def infer(expr, quantities, depth=0, units=None):
    if depth > 64:
        raise RuleError("AST depth exceeds 64")
    op = expr["op"]
    if op == 'literal':
        number(expr['value'])
        if not units or expr['unit'] not in units: raise RuleError('unknown literal unit')
        return 'scalar',tuple(units[expr['unit']]['dimension']),'not_applicable'
    if op == 'pi': return 'scalar',ZERO,'not_applicable'
    if op == "var":
        if expr["id"] not in quantities:
            raise RuleError(f"undefined symbol: {expr['id']}")
        q = quantities[expr["id"]]
        return q["kind"], tuple(q["dimension"]), q["frame"]
    if op == "number":
        number(expr["value"])
        return "scalar", ZERO, "not_applicable"
    a = [infer(v, quantities, depth + 1, units) for v in expr["args"]]
    if op in {'sqrt','abs','norm'}:
        kind,dim,frame=a[0]
        if op=='norm':
            if kind!='vector': raise RuleError('norm requires a vector')
            return 'scalar',dim,'not_applicable'
        if kind!='scalar': raise RuleError('scalar unary operand required')
        if op=='sqrt':
            if any(x%2 for x in dim): raise RuleError('sqrt gives unsupported fractional dimensions')
            return kind,tuple(x//2 for x in dim),frame
        return a[0]
    if op in {'sin','cos','tan','asin','acos','exp','log'}:
        if a[0][0]!='scalar' or a[0][1]!=ZERO: raise RuleError('dimensionless scalar argument required')
        return 'scalar',ZERO,'not_applicable'
    if op=='vector':
        if any(x[0]!='scalar' or x[1]!=a[0][1] for x in a): raise RuleError('incompatible vector components')
        return 'vector',a[0][1],'lab'
    if op in {'lt','le','gt','ge','ne'}:
        if any(x[0]!='scalar' or x[1]!=a[0][1] for x in a): raise RuleError('comparison dimensions differ')
        return 'boolean',ZERO,'not_applicable'
    if op in {"add", "sub", "eq"}:
        if any(v != a[0] for v in a) or a[0][0] not in {"scalar", "vector"}:
            raise RuleError(f"{op}: incompatible kind, dimension or coordinate frame")
        return ("boolean", ZERO, "not_applicable") if op == "eq" else a[0]
    if op == "sum":
        if a[0][0] not in {"vector_list",'scalar_list'}:
            raise RuleError("sum requires a nonempty quantity list")
        return "vector" if a[0][0]=='vector_list' else 'scalar', a[0][1], a[0][2]
    if op in {"dot",'cross'}:
        if any(v[0] != "vector" for v in a) or a[0][2] != a[1][2]:
            raise RuleError("dot requires vectors in the same frame")
        return "scalar" if op=='dot' else 'vector', tuple(x + y for x, y in zip(a[0][1], a[1][1])), "not_applicable" if op=='dot' else a[0][2]
    if op == "pow":
        exponent = expr["args"][1]
        if a[0][0] not in {"scalar",'scalar_list'} or exponent["op"] != "number" or type(exponent["value"]) is not int:
            raise RuleError("pow requires a scalar base and literal integer exponent")
        return a[0][0], tuple(v * exponent["value"] for v in a[0][1]), a[0][2]
    if op == "div":
        if a[0][0] not in {"scalar", "vector"} or a[1][0] != "scalar":
            raise RuleError("division by a vector is undefined")
        return a[0][0], tuple(x - y for x, y in zip(a[0][1], a[1][1])), a[0][2]
    if op == "mul":
        if any(v[0] not in {"scalar", "vector"} for v in a) or sum(v[0] == "vector" for v in a) > 1:
            raise RuleError("mul allows scalars and at most one vector; use dot explicitly")
        vectors = [v for v in a if v[0] == "vector"]
        # A scalar coefficient does not change a coordinate frame.
        frame = vectors[0][2] if vectors else next((v[2] for v in a if v[2] != "not_applicable"), "not_applicable")
        return "vector" if vectors else "scalar", tuple(sum(v[1][i] for v in a) for i in range(7)), frame
    raise RuleError(f"unsupported operation: {op}")


def symbolic(expr, symbols):
    op = expr["op"]
    if op == "var":
        return symbols[expr["id"]]
    if op == "number":
        return sp.Rational(str(expr["value"]))
    if op=='pi': return sp.pi
    a = [symbolic(v, symbols) for v in expr["args"]]
    if op == "add": return sp.Add(*a)
    if op == "sub": return a[0] - a[1]
    if op == "mul": return sp.Mul(*a)
    if op == "div": return a[0] / a[1]
    if op == "pow": return a[0] ** a[1]
    if op=='sqrt': return sp.sqrt(a[0])
    raise RuleError("symbolic rewrite supports scalar/componentwise algebra only")


def validate_bundle(bundle, schema=None):
    schema = schema or read_json(ROOT / "schemas/physics_rule.schema.json")
    Draft202012Validator.check_schema(schema)
    errors = sorted(Draft202012Validator(schema).iter_errors(bundle), key=lambda e: str(e.path))
    if errors:
        raise RuleError(f"JSON Schema: {errors[0].json_path}: {errors[0].message}")
    ids = [r["id"] for r in bundle["rules"]]
    if len(ids) != len(set(ids)):
        raise RuleError("duplicate rule id")
    for unit in bundle["units"].values():
        if Fraction(unit["scale"]) <= 0:
            raise RuleError("unit scale must be positive")
        if unit.get('offset') and unit['dimension'] != [0,0,0,0,1,0,0]: raise RuleError('offset is restricted to temperature units')
    for r in bundle["rules"]:
        if r["variant_of"] is not None and r["variant_of"] not in ids:
            raise RuleError("variant refers to an undefined rule")
        q = r["quantities"]
        objects=r.get('objects',{'body':r['object_model']})
        if 'body' not in objects: raise RuleError('primary body model missing')
        for name, spec in q.items():
            if spec['object'] not in objects: raise RuleError('undefined physical object')
            unit = bundle["units"].get(spec["unit"])
            if not unit or unit["dimension"] != spec["dimension"]:
                raise RuleError(f"{r['id']}.{name}: unit/dimension mismatch")
            if spec["kind"] in {'vector','vector_list'} and spec["domain"] != "real":
                raise RuleError("ordered vector domains are unsupported")
            if spec["kind"] in {'vector','vector_list'} and spec["frame"] != "lab":
                raise RuleError("vector coordinates require a declared frame")
        laws = {x["id"]: x for x in r["laws"]}
        if len(laws) != len(r["laws"]): raise RuleError("duplicate law id")
        for law in laws.values():
            if law["equation"]["op"] != "eq": raise RuleError("a law must be an equality")
            infer(law["equation"], q, units=bundle['units'])
        for constraint in r.get('constraints',[]):
            if infer(constraint,q,units=bundle['units'])[0]!='boolean': raise RuleError('constraint must be boolean')
        produced = set()
        all_targets = {s['target'] for s in r['steps']}
        def variables(expr):
            if expr['op'] == 'var': return {expr['id']}
            return set().union(*(variables(x) for x in expr.get('args', [])))
        symbols = {name: sp.Symbol(name, positive=True) if spec["domain"] == "positive" else sp.Symbol(name, real=True) for name, spec in q.items()}
        if len({x['id'] for x in r['steps']}) != len(r['steps']): raise RuleError("duplicate step id")
        for step in r["steps"]:
            target = step["target"]
            if target not in q or target in produced: raise RuleError("undefined or multiply assigned target")
            if variables(step['expression']) & (all_targets - produced):
                raise RuleError("step depends on an uncomputed quantity")
            produced.add(target)
            inferred = infer(step["expression"], q, units=bundle['units'])
            expected = (q[target]["kind"], tuple(q[target]["dimension"]), q[target]["frame"])
            if inferred != expected: raise RuleError(f"{r['id']}.{target}: assignment type mismatch")
            if step["law_id"] not in laws: raise RuleError("undefined law reference")
            law = laws[step["law_id"]]
            if not set(law["principles"]).issubset(step["principles"]): raise RuleError("step omits its physical principle")
            lhs, rhs = law["equation"]["args"]
            if step["rewrite"] == "direct":
                if lhs != {"op":"var", "id":target} or rhs != step["expression"]:
                    raise RuleError("direct assignment does not match its law")
            else:
                if "divide_nonzero" not in step["principles"]: raise RuleError("rewrite lacks algebra principle")
                residual = symbolic(lhs, symbols) - symbolic(rhs, symbols)
                variable = symbols[target]
                if sp.Poly(residual, variable).degree() != 1 or sp.diff(residual, variable).is_nonzero is not True:
                    raise RuleError("linear rewrite coefficient is not proven nonzero")
                if sp.simplify(residual.subs(variable, symbolic(step["expression"], symbols))) != 0:
                    raise RuleError("algebraic rewrite is not equivalent to its law")
        for law in r["laws"]:
            if any(p not in bundle["principles"] for p in law["principles"]): raise RuleError("undefined principle")
        for step in r["steps"]:
            if any(p not in bundle["principles"] for p in step["principles"]): raise RuleError("undefined step principle")
        if any(x not in produced for x in r["conclusions"]): raise RuleError("conclusion is not computed")
        for initial in r["initial_conditions"]:
            quantity, time = initial["quantity"], initial["time_quantity"]
            dimension = (0,1,0,0,0,0,0) if initial["state"] == "position" else (0,1,-1,0,0,0,0)
            if quantity not in q or tuple(q[quantity]["dimension"]) != dimension or time not in q or q[time]["dimension"] != [0,0,1,0,0,0,0]:
                raise RuleError("invalid initial condition references")
    return True


def evaluate(expr, values, units=None):
    op = expr["op"]
    if op == "var":
        if expr["id"] not in values: raise RuleError(f"missing input: {expr['id']}")
        return values[expr["id"]]
    if op == "number": return expr["value"]
    if op=='pi': return math.pi
    if op=='literal':
        u=units[expr['unit']]
        return expr['value']*float(Fraction(u['scale']))*(math.pi if u.get('pi_factor') else 1)+float(Fraction(u.get('offset','0')))
    a = [evaluate(v, values, units) for v in expr["args"]]
    if op in {'sqrt','abs','sin','cos','tan','asin','acos','exp','log'}:
        try:return abs(a[0]) if op=='abs' else getattr(math,op)(a[0])
        except (ValueError,OverflowError) as e:raise RuleError(f'{op}: outside real finite domain') from e
    if op=='norm': return math.hypot(*a[0])
    if op=='vector':return a
    if op=='cross':
        x,y=a
        return [x[1]*y[2]-x[2]*y[1],x[2]*y[0]-x[0]*y[2],x[0]*y[1]-x[1]*y[0]]
    if op in {'eq','ne','lt','le','gt','ge'}:
        import operator
        return getattr(operator,op)(a[0],a[1])
    if op == "sum": return [sum(row[i] for row in a[0]) for i in range(3)] if isinstance(a[0][0],list) else sum(a[0])
    if op in {"add", "sub"}:
        if isinstance(a[0], list):
            return [sum(row[i] for row in a) if op == "add" else a[0][i] - a[1][i] for i in range(3)]
        return sum(a) if op == "add" else a[0] - a[1]
    if op == "dot": return sum(x*y for x,y in zip(a[0],a[1]))
    if op == "mul":
        vectors = [x for x in a if isinstance(x, list)]
        scale = math.prod(x for x in a if not isinstance(x, list))
        return [x*scale for x in vectors[0]] if vectors else scale
    if op == "div":
        if a[1] == 0: raise RuleError("division by zero")
        return [x/a[1] for x in a[0]] if isinstance(a[0],list) else a[0]/a[1]
    if op == "pow":
        def power(v):
            if v == 0 and a[1] < 0: raise RuleError("zero to a negative power")
            try:return v ** a[1]
            except OverflowError as e: raise RuleError('power overflow') from e
        return [power(v) for v in a[0]] if isinstance(a[0],list) else power(a[0])
    raise RuleError(f"non-executable operation: {op}")


def check_value(value, spec):
    kind = spec["kind"]
    if kind == "scalar":
        number(value)
        if spec["domain"] == "positive" and value <= 0: raise RuleError("positive quantity required")
        if spec["domain"] == "nonnegative" and value < 0: raise RuleError("nonnegative quantity required")
        if spec['domain'] in {'integer','positive_integer','nonnegative_integer'}:
            if value!=int(value): raise RuleError('integer quantity required')
            if spec['domain']=='positive_integer' and value<=0:raise RuleError('positive integer required')
            if spec['domain']=='nonnegative_integer' and value<0:raise RuleError('nonnegative integer required')
    elif kind == "vector":
        if not isinstance(value,list) or len(value) != 3: raise RuleError("vector must contain exactly three components")
        for x in value: number(x)
    elif kind=='scalar_list':
        if not isinstance(value,list) or not value:raise RuleError('nonempty scalar list required')
        for x in value:check_value(x,dict(spec,kind='scalar'))
    else:
        if not isinstance(value,list) or not value: raise RuleError("nonempty vector list required; use a zero vector for zero resultant")
        for x in value: check_value(x,dict(spec,kind="vector"))


def measurement(value, spec, units):
    if not isinstance(value,dict) or set(value) != {"value","unit"}: raise RuleError("measurement requires exactly value and unit")
    if not isinstance(value['unit'],str): raise RuleError("unit must be a registered string")
    unit = units.get(value["unit"])
    if not unit or unit["dimension"] != spec["dimension"]: raise RuleError("input unit has incompatible dimensions")
    check_value(value["value"], spec)
    preferred=units[spec['unit']]
    if preferred.get('temperature_kind')!=unit.get('temperature_kind'):raise RuleError('absolute temperature and temperature intervals cannot be interchanged')
    scale = float(Fraction(unit["scale"]))*(math.pi if unit.get('pi_factor') else 1)
    def convert(x): return [convert(v) for v in x] if isinstance(x,list) else x*scale+float(Fraction(unit.get('offset','0')))
    result = convert(value["value"])
    check_value(result,spec)
    return result


def run_rule(bundle, rule_id, bindings, context, boundary_conditions=()):
    validate_bundle(bundle)
    return _run_rule(bundle,rule_id,bindings,context,boundary_conditions)


class CompiledRules:
    def __init__(self,bundle):
        self._bundle=deepcopy(bundle)
        validate_bundle(self._bundle)
    def run(self,rule_id,bindings,context,boundary_conditions=()):
        return _run_rule(self._bundle,rule_id,bindings,context,boundary_conditions)


def _run_rule(bundle, rule_id, bindings, context, boundary_conditions=()):
    matches = [r for r in bundle["rules"] if r["id"] == rule_id]
    if not matches: raise RuleError("unknown rule")
    r = matches[0]
    if context.get("object_model") != r["object_model"]: raise RuleError("object model not established")
    if r.get('objects') and context.get('objects')!=r['objects']: raise RuleError('multiple object models not established')
    if r["reference_frame"] != "not_applicable" and context.get("reference_frame") != r["reference_frame"]:
        raise RuleError("reference frame not established")
    if any(q["frame"] == "lab" for q in r["quantities"].values()) and context.get("frame_id") != "lab":
        raise RuleError("coordinate frame is missing or inconsistent")
    facts = deepcopy(context)
    axis = context.get("axis")
    if axis is not None:
        check_value(axis,{"kind":"vector","domain":"real"})
        if not math.isclose(sum(x*x for x in axis),1,rel_tol=1e-10,abs_tol=1e-10): raise RuleError("axis must be a unit vector")
    facts["axis_declared"] = axis is not None
    for c in r["conditions"]:
        if facts.get(c["fact"]) is not c["equals"]: raise RuleError(f"condition not established: {c['fact']}")
    force = context.get("force")
    if force is not None or r["force_dependence"]["mode"] != "not_used" or any(c["fact"] == "force_constant" for c in r["conditions"]):
        if not isinstance(force,dict) or set(force) != {"behavior","depends_on"}: raise RuleError("explicit force profile required")
        if force["behavior"] not in {"constant","variable","unknown"} or not isinstance(force["depends_on"],list) or any(x not in {"position","time","velocity"} for x in force["depends_on"]): raise RuleError("invalid force profile")
        if force["behavior"] == "constant" and force["depends_on"]: raise RuleError("constant force cannot declare state dependencies")
        if facts.get("force_constant") and force["behavior"] != "constant": raise RuleError("force constancy is contradictory")
        if r['force_dependence']['mode']!='not_used' and not set(force['depends_on']).issubset(r['force_dependence']['allowed_dependencies']):raise RuleError('force dependencies not allowed by model')
    if facts.get("acceleration_constant") and facts.get("mass_constant") and isinstance(force,dict) and force.get("behavior") == "variable":
        raise RuleError("variable net force and fixed mass conflict with constant acceleration")
    targets = {s["target"] for s in r["steps"]}
    if set(bindings) - (set(r["quantities"]) - targets): raise RuleError("unknown or computed input quantity")
    values = {k:measurement(v,r["quantities"][k],bundle["units"]) for k,v in bindings.items()}
    for initial in r["initial_conditions"]:
        if initial["quantity"] not in values or initial["time_quantity"] not in values: raise RuleError("missing initial condition")
    if "t" in values and "t0" in values and values["t"] < values["t0"]: raise RuleError("terminal time precedes initial time")
    for c in r.get('constraints',[]):
        if evaluate(c,values,bundle['units']) is not True:raise RuleError('numeric applicability constraint not satisfied')
    trace = []
    for step in r["steps"]:
        result = evaluate(step["expression"],values,bundle['units'])
        check_value(result,r["quantities"][step["target"]])
        values[step["target"]] = result
        trace.append({"step":step["id"],"quantity":step["target"],"si_value":result,"principles":step["principles"]})
    for boundary in boundary_conditions:
        if not isinstance(boundary,dict) or set(boundary) != {"quantity","value","unit"} or boundary["quantity"] not in values: raise RuleError("invalid boundary constraint")
        key = boundary["quantity"]
        expected = measurement({"value":boundary["value"],"unit":boundary["unit"]},r["quantities"][key],bundle["units"])
        def close(a,b): return all(close(x,y) for x,y in zip(a,b)) if isinstance(a,list) else math.isclose(a,b,rel_tol=1e-9,abs_tol=1e-12)
        if not close(values[key],expected): raise RuleError("boundary constraint not satisfied")
    def si_unit(key):
        dim = r['quantities'][key]['dimension']
        return next((u for u,spec in bundle['units'].items() if spec['dimension'] == dim and Fraction(spec['scale']) == 1), None)
    return {"rule_id":rule_id,"results":{k:{"si_value":values[k],"si_unit":si_unit(k),"dimension":r["quantities"][k]["dimension"]} for k in r["conclusions"]},"trace":trace}


def available_rules(bundle, bindings, context):
    """Fail closed: missing values or conditions do not license a rule."""
    validate_bundle(bundle)
    result = []
    for rule in bundle["rules"]:
        try:
            # A problem may carry inputs for more than one candidate rule.
            targets = {s["target"] for s in rule["steps"]}
            applicable = {k:v for k,v in bindings.items() if k in rule["quantities"] and k not in targets}
            _run_rule(bundle,rule["id"],applicable,context)
            result.append(rule["id"])
        except RuleError:
            pass
    return result
