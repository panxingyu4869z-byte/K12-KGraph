"""Typed declarations; unit equalities checked independently with exact fractions."""
from fractions import Fraction

from jsonschema import Draft202012Validator

from .engine import ROOT, RuleError, infer, read_json


def validate_catalog(catalog, bundle):
    schema=read_json(ROOT/'schemas/physics_catalog.schema.json')
    Draft202012Validator.check_schema(schema)
    errors=list(Draft202012Validator(schema).iter_errors(catalog))
    if errors:raise RuleError(f'catalog JSON Schema: {errors[0].message}')
    units=bundle['units']
    def exact(e):
        if e['op']=='number':return Fraction(str(e['value']))
        if e['op']=='literal':
            u=units[e['unit']]
            if u.get('pi_factor'):raise RuleError('irrational conversion is not a rational unit identity')
            return Fraction(str(e['value']))*Fraction(u['scale'])+Fraction(u.get('offset','0'))
        a=[exact(x) for x in e['args']]
        if e['op']=='mul':
            result=Fraction(1)
            for x in a:result*=x
            return result
        if e['op']=='div':return a[0]/a[1]
        raise RuleError('declaration requires a literal or rational unit expression')
    ids=[]
    for record in catalog['records']:
        ids.append(record['id'])
        if record['kind']=='unit_relation':
            for equation in record['equations']:
                if equation['op']!='eq':raise RuleError('unit relation must be equality')
                infer(equation,{},units=units)
                if exact(equation['args'][0])!=exact(equation['args'][1]):raise RuleError('unit identity is false')
        elif record['kind']=='constant':
            infer(record['expression'],{},units=units)
            exact(record['expression'])
        else:
            q=record['quantity']
            if units[q['unit']]['dimension']!=q['dimension']:raise RuleError('quantity declaration unit mismatch')
    if len(ids)!=len(set(ids)):raise RuleError('duplicate declaration id')
    return True
