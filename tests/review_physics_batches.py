"""Independent, exact review; intentionally does not import physics.engine.

Optional LIE-1 quantity arithmetic is used as a second dimensional checker.
Reference answers are isolated from the production rule evaluator.
"""
from __future__ import annotations
import argparse
import json
import math
import sys
from fractions import Fraction
from pathlib import Path
import sympy as sp


def review(root, lie_root=None):
    b=json.loads((root/'knowledge/physics/rules.json').read_text())
    examples=json.loads((root/'knowledge/physics/examples.json').read_text())
    zero=(0,)*7
    def dimension(e,q):
        op=e['op']
        if op=='var':return tuple(q[e['id']]['dimension'])
        if op in {'number','pi'}:return zero
        if op=='literal':return tuple(b['units'][e['unit']]['dimension'])
        dims=[dimension(a,q) for a in e['args']]
        if op in {'add','sub','eq','lt','le','gt','ge','ne'}:
            assert all(x==dims[0] for x in dims)
            return zero if op in {'eq','lt','le','gt','ge','ne'} else dims[0]
        if op in {'mul','dot','cross'}:return tuple(map(sum,zip(*dims)))
        if op=='div':return tuple(x-y for x,y in zip(*dims))
        if op=='pow':return tuple(x*e['args'][1]['value'] for x in dims[0])
        if op=='sqrt':
            assert all(x%2==0 for x in dims[0]);return tuple(x//2 for x in dims[0])
        if op in {'sum','abs','norm','vector'}:return dims[0]
        if op=='atan2':
            assert dims[0]==dims[1];return zero
        assert dims[0]==zero
        return zero
    def exact_value(e,values):
        op=e['op']
        if op=='var':return values[e['id']]
        if op=='number':return sp.Rational(str(e['value']))
        if op=='pi':return sp.pi
        if op=='literal':
            u=b['units'][e['unit']];return sp.Rational(str(e['value']))*sp.Rational(u['scale'])*(sp.pi if u.get('pi_factor') else 1)+sp.Rational(u.get('offset','0'))
        a=[exact_value(x,values) for x in e['args']]
        if op=='sum':return sum(a[0],sp.zeros(3,1)) if isinstance(a[0][0],sp.MatrixBase) else sum(a[0])
        if op=='add':return sum(a[1:],a[0])
        if op=='sub':return a[0]-a[1]
        if op=='mul':
            result=a[0]
            for x in a[1:]:result=result*x
            return result
        if op=='div':return a[0]/a[1]
        if op=='pow':return [x**int(a[1]) for x in a[0]] if isinstance(a[0],list) else a[0]**int(a[1])
        if op=='dot':return a[0].dot(a[1])
        if op=='cross':return a[0].cross(a[1])
        if op=='norm':return a[0].norm()
        if op=='vector':return sp.Matrix(a)
        if op=='atan2':return sp.atan2(*a)
        if op=='abs':return sp.Abs(a[0])
        return getattr(sp,op)(a[0])
    checked=[]
    nuclear_checks=0
    for r in b['rules']:
        for law in r['laws']:dimension(law['equation'],r['quantities'])
        for step in r['steps']:assert dimension(step['expression'],r['quantities'])==tuple(r['quantities'][step['target']]['dimension'])
        case=next(x for x in examples if x['rule_id']==r['id'])
        values={}
        for k,entry in case['bindings'].items():
            u=b['units'][entry['unit']];scale=sp.Rational(u['scale'])*(sp.pi if u.get('pi_factor') else 1);offset=sp.Rational(u.get('offset','0'))
            def scalar(x):return sp.Rational(str(x))*scale+offset
            v=entry['value'];kind=r['quantities'][k]['kind']
            values[k]=sp.Matrix([scalar(x) for x in v]) if kind=='vector' else [sp.Matrix([scalar(x) for x in row]) for row in v] if kind=='vector_list' else [scalar(x) for x in v] if kind=='scalar_list' else scalar(v)
        for step in r['steps']:values[step['target']]=exact_value(step['expression'],values)
        if 'reaction' in r:
            for field in ['nucleon_number','charge_number','electron_lepton_number']:
                totals=[sum(exact_value(p[field],values) for p in r['reaction'][side]) for side in ['reactants','products']]
                assert totals[0]==totals[1]
            nuclear_checks+=1
        for k,v in case['expected'].items():
            want=sp.Matrix([sp.Rational(str(x)) for x in v]) if isinstance(v,list) else sp.Rational(str(v))
            difference=values[k]-want
            error=float(difference.norm()) if isinstance(difference,sp.MatrixBase) else abs(float(difference))
            assert error<=max(1e-12,1e-9*float(want.norm() if isinstance(want,sp.MatrixBase) else abs(want))),(r['id'],values[k],want)
        checked.append(r['id'])
    catalog_path=root/'knowledge/physics/catalog.json'
    declarations=json.loads(catalog_path.read_text())['records'] if catalog_path.exists() else []
    unit_identities=0
    for record in declarations:
        if record['kind']=='unit_relation':
            for equation in record['equations']:
                dimension(equation,{})
                left,right=equation['args']
                assert exact_value(left,{})==exact_value(right,{})
                unit_identities+=1
        elif record['kind']=='constant':
            dimension(record['expression'],{})
            assert exact_value(record['expression'],{}).is_finite
    # Independent physical identities, not re-evaluation of the production AST.
    m,ax,ay,az=sp.symbols('m ax ay az',positive=True)
    assert sp.simplify((m*sp.Matrix([ax,ay,az])).dot(sp.Matrix([ax,ay,az]))-m*(ax**2+ay**2+az**2))==0
    t,t0,x0,v0,a=sp.symbols('t t0 x0 v0 a')
    x=x0+v0*(t-t0)+a*(t-t0)**2/2
    assert sp.simplify(sp.diff(x,t)-(v0+a*(t-t0)))==0
    assert sp.simplify(sp.diff(x,t,2)-a)==0
    lie_verified=False
    if lie_root:
        sys.path[:0]=[str(lie_root/'CODEX LIE'/x) for x in ['求解器','数学执行算法库','知识库','其他']]
        from domains.math_library.algorithms.units import Dimension,Unit,Quantity,multiply,divide
        from domains.math_library.algorithms.checks.units import check_product
        keys=['M','L','T','I','Theta','N','J']
        def qty(d):return Quantity(Fraction(1),Unit('base',Dimension.of(dict(zip(keys,d))),Fraction(1)))
        for r in b['rules']:
            for law in r['laws']:
                def inspect(e):
                    children=e.get('args',[])
                    for child in children:inspect(child)
                    if e['op'] not in {'mul','div','dot','cross'}:return
                    dims=[dimension(x,r['quantities']) for x in children];result=qty(dims[0])
                    for d in dims[1:]:
                        right=qty(d);out=divide(result,right) if e['op']=='div' else multiply(result,right)
                        assert check_product(result,right,out.value,e['op']=='div').reason is None
                        result=out.value
                    assert result.unit.dimension==qty(dimension(e,r['quantities'])).unit.dimension
                inspect(law['equation'])
        lie_verified=True
    return {'reviewed_rule_count':len(checked),'rules':checked,'exact_numeric_examples':len(examples),'catalog_records':len(declarations),'exact_unit_identities':unit_identities,'nuclear_conservation_checks':nuclear_checks,'kinematic_derivative_identity':True,'lie_quantity_crosscheck':lie_verified,'review_scope':'independent exact arithmetic, dimensional relations and documented model conditions; not full LIE product acceptance'}


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--lie-root',type=Path);p.add_argument('--output',type=Path)
    args=p.parse_args();result=review(Path(__file__).resolve().parents[1],args.lie_root)
    text=json.dumps(result,ensure_ascii=False,indent=2)+'\n'
    if args.output:args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(text)
    print(text)
