import copy
import json
import unittest
from collections import Counter, deque

from physics.engine import ROOT, CompiledRules, RuleError, available_rules, read_json, run_rule, validate_bundle
from physics.clean import ALIASES, clean_graph


class PhysicsContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bundle = read_json(ROOT / 'knowledge/physics/rules.json')
        cls.examples = read_json(ROOT / 'knowledge/physics/examples.json')
        cls.compiled = CompiledRules(cls.bundle)

    def run_case(self, case, bundle=None):
        engine=self.compiled if bundle is None else CompiledRules(bundle)
        return engine.run(case['rule_id'],case['bindings'],case['context'],case['boundary_conditions'])

    def test_all_rules_and_independent_numeric_answers(self):
        self.assertTrue(validate_bundle(self.bundle))
        self.assertEqual({r['id'] for r in self.bundle['rules']},{x['rule_id'] for x in self.examples})
        for case in self.examples:
            with self.subTest(rule=case['rule_id']):
                result = self.run_case(case)
                for key, expected in case['expected'].items():
                    actual = result['results'][key]['si_value']
                    if isinstance(expected,list):
                        for a,b in zip(actual,expected): self.assertAlmostEqual(a,b)
                    else: self.assertAlmostEqual(actual,expected)
                    self.assertIsNotNone(result['results'][key]['si_unit'])

    def test_display_has_no_execution_authority(self):
        b = copy.deepcopy(self.bundle)
        for r in b['rules']:
            r['display'] = {'name_zh':'无关名称','original_formula':'__import__("os").system("false")','notes_zh':'不能改变解释结果'}
        altered=CompiledRules(b)
        for case in self.examples:
            self.assertEqual(self.run_case(case),altered.run(case['rule_id'],case['bindings'],case['context'],case['boundary_conditions']))

    def test_model_domains_and_constraints(self):
        cases={x['rule_id']:x for x in self.examples}
        for rid,key,value in [('mechanical_efficiency','useful_work',200),('average_pressure','area',0),('thin_lens_power','focal_length',0),('cycle_frequency','cycles',1.5)]:
            c=copy.deepcopy(cases[rid]);c['bindings'][key]['value']=value
            with self.subTest(rule=rid),self.assertRaises(RuleError):self.run_case(c)
        c=copy.deepcopy(cases['hydrostatic_gauge_pressure']);c['context'].pop('fluid_static')
        with self.assertRaises(RuleError):self.run_case(c)

    def test_electric_and_thermal_boundaries(self):
        cases={x['rule_id']:x for x in self.examples}
        c=copy.deepcopy(cases['parallel_resistance']);c['bindings']['resistances']['value']=[1,0]
        with self.assertRaises(RuleError):self.run_case(c)
        c=copy.deepcopy(cases['sensible_heat_exchange']);c['bindings']['temperature_change']['unit']='degC'
        with self.assertRaisesRegex(RuleError,'temperature'):self.run_case(c)
        c=copy.deepcopy(cases['ideal_gas_state_change']);c['bindings']['t1']={'value':-10,'unit':'degC'}
        result=self.run_case(c)['results']['p2']['si_value']
        self.assertAlmostEqual(result,100000*600/(2*263.15))
        c['bindings']['t1']={'value':-273.15,'unit':'degC'}
        with self.assertRaises(RuleError):self.run_case(c)
        c=copy.deepcopy(cases['sinusoidal_rms_voltage']);c['context'].pop('pure_sinusoid')
        with self.assertRaises(RuleError):self.run_case(c)
        c=copy.deepcopy(cases['electric_field_definition']);c['bindings']['test_charge']['value']=0
        with self.assertRaises(RuleError):self.run_case(c)

    def test_unknown_operator_and_property_rejected_by_schema(self):
        for field in ['op','code']:
            b = copy.deepcopy(self.bundle)
            if field == 'op': b['rules'][0]['steps'][0]['expression']['op'] = 'python_eval'
            else: b['rules'][0]['code'] = 'ignored?'
            with self.assertRaisesRegex(RuleError,'JSON Schema'): validate_bundle(b)

    def test_dimension_and_algebra_checks_are_separate(self):
        b = copy.deepcopy(self.bundle)
        b['rules'][0]['quantities']['duration']['dimension'] = [1,0,0,0,0,0,0]
        with self.assertRaisesRegex(RuleError,'unit/dimension'): validate_bundle(b)
        b = copy.deepcopy(self.bundle)
        r = next(x for x in b['rules'] if x['id']=='newton2_point_mass')
        # F/m*2 is dimensionally correct and algebraically wrong.
        r['steps'][1]['expression'] = {'op':'mul','args':[r['steps'][1]['expression'],{'op':'number','value':2}]}
        with self.assertRaisesRegex(RuleError,'not equivalent'): validate_bundle(b)

    def test_vector_division_rejected(self):
        b = copy.deepcopy(self.bundle)
        r = next(x for x in b['rules'] if x['id']=='newton2_point_mass')
        r['steps'][1]['expression']['args'].reverse()
        with self.assertRaisesRegex(RuleError,'division by a vector'): validate_bundle(b)

    def test_missing_inertial_frame_and_mass_conditions_rejected(self):
        for field in ['reference_frame','mass_constant','classical_regime']:
            c = copy.deepcopy(self.examples[2]);c['context'].pop(field)
            with self.subTest(field=field),self.assertRaises(RuleError): self.run_case(c)
        for invalid in [0,-1,True,float('nan')]:
            c = copy.deepcopy(self.examples[2]);c['bindings']['mass']['value'] = invalid
            with self.subTest(mass=invalid),self.assertRaises(RuleError): self.run_case(c)

    def test_units_shapes_and_frames(self):
        for mutation in ['unit','shape','frame']:
            c = copy.deepcopy(self.examples[2])
            if mutation == 'unit': c['bindings']['mass']['unit']='s'
            elif mutation == 'shape': c['bindings']['external_forces']['value']=[[1,2]]
            else: c['context']['frame_id']='rotating'
            with self.subTest(mutation=mutation),self.assertRaises(RuleError):self.run_case(c)

    def test_initial_time_position_and_boundary_constraints(self):
        c = copy.deepcopy(self.examples[4]);c['bindings'].pop('x0')
        with self.assertRaisesRegex(RuleError,'initial condition'): self.run_case(c)
        c = copy.deepcopy(self.examples[4]);c['bindings']['t']['value']=4
        with self.assertRaisesRegex(RuleError,'precedes'):self.run_case(c)
        c = copy.deepcopy(self.examples[4]);c['boundary_conditions'][0]['value']=21
        with self.assertRaisesRegex(RuleError,'boundary constraint'):self.run_case(c)

    def test_force_variation_does_not_license_constant_acceleration(self):
        c = copy.deepcopy(self.examples[2]);c['context']['force']={'behavior':'variable','depends_on':['position','time','velocity']}
        self.assertEqual(self.run_case(c)['results']['acceleration']['si_value'],[5,0,0])
        c = copy.deepcopy(self.examples[4]);c['context'].update(mass_constant=True,force={'behavior':'variable','depends_on':['time']})
        with self.assertRaisesRegex(RuleError,'conflict'):self.run_case(c)
        c = copy.deepcopy(self.examples[4]);c['context'].pop('acceleration_constant')
        self.assertNotIn('constant_a_position',available_rules(self.bundle,c['bindings'],c['context']))

    def test_same_knowledge_single_rule_but_later_scope_kept(self):
        a = next(r for r in self.bundle['rules'] if r['id']=='work_parallel_constant_force')
        b = next(r for r in self.bundle['rules'] if r['id']=='work_dot_constant_force')
        self.assertEqual(a['concept_id'],b['concept_id'])
        self.assertEqual(b['variant_of'],a['id'])
        self.assertEqual((a['stage'],b['stage']),('middle','high'))


class CleanedGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        p = ROOT/'knowledge/physics/cleaned'
        cls.graph=read_json(p/'graph.json');cls.report=read_json(p/'report.json')
        cls.provenance=read_json(p/'provenance.json');cls.quarantine=read_json(p/'quarantine.json')
        cls.curriculum={s:read_json(p/'curriculum'/f'{s}.json') for s in ['primary','middle','high']}

    def test_every_source_edge_is_accounted_for_once(self):
        indices=[i for x in self.provenance['edges'] for i in x['source_edge_indices']]+[x['source_edge_index'] for x in self.quarantine]
        self.assertEqual(sorted(indices),list(range(self.report['input']['edges'])))
        self.assertEqual(len(indices),len(set(indices)))

    def test_no_dangling_ids_and_dag_relations_independently(self):
        ids=[n['id'] for n in self.graph['nodes']];self.assertEqual(len(ids),len(set(ids)))
        for e in self.graph['edges']:
            self.assertIn(e['source'],ids)
            for target in ([e['target']] if 'target' in e else [x['target'] for x in e['target_name_to_ids']]):self.assertIn(target,ids)
        # Kahn's algorithm is independent of the repository's DFS cycle checker.
        for kind in ['is_a','prerequisites_for']:
            adj={i:set() for i in ids};degree=Counter()
            for e in self.graph['edges']:
                if e['type']==kind and e['target'] not in adj[e['source']]:
                    adj[e['source']].add(e['target']);degree[e['target']]+=1
            ready=deque(i for i in ids if degree[i]==0);count=0
            while ready:
                n=ready.popleft();count+=1
                for t in adj[n]:
                    degree[t]-=1
                    if degree[t]==0:ready.append(t)
            self.assertEqual(count,len(ids))

    def test_curriculum_has_each_knowledge_node_once(self):
        ids=[x['id'] for items in self.curriculum.values() for x in items]
        expected=[n['id'] for n in self.graph['nodes'] if n['label'] in {'Concept','Skill','Experiment','Exercise'}]
        self.assertEqual(sorted(ids),sorted(expected));self.assertEqual(len(ids),len(set(ids)))
        self.assertEqual(self.curriculum['primary'],[])
        self.assertNotIn('physics_bx1_rjb_cpt33',ids)

    def test_cleaning_is_idempotent_and_keeps_later_work_model(self):
        result=clean_graph(self.graph,PhysicsContractTests.bundle if hasattr(PhysicsContractTests,'bundle') else read_json(ROOT/'knowledge/physics/rules.json'),aliases={})
        self.assertEqual(result['graph'],self.graph)
        self.assertEqual(result['quarantine'],[])


if __name__=='__main__': unittest.main()
