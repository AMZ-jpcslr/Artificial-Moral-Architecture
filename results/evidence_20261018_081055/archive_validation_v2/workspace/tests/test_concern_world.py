"""Development-only tests for sensor isolation and shared exogenous world data."""
from dataclasses import FrozenInstanceError, replace
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'src'))
from moral_agent.concern_information.world import (
    CHANNELS, FIELDS, Evidence, apply_response, build_episode, evaluate,
    query, reference_evidence, selected_feedback,
)
from moral_agent.models import to_dict


class ConcernWorldTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.config = json.loads((ROOT / 'experiments/concern_information_config.json').read_text())
        cls.development = [f for f in cls.config['families'] if f['split'] == 'development']
        cls.worlds = tuple(w for f in cls.development for w in build_episode(f, 13, cls.config))

    def test_public_frame_excludes_evaluation_and_hidden_state(self):
        frame = to_dict(self.worlds[0].frame)
        self.assertEqual(set(frame), {'situation', 'initial', 'cues', 'candidates', 'nuisance', 'context'})
        for forbidden in ('physical', 'future_uniform', 'error_type', 'relevant_channel', 'key', 'safe_task_success'):
            self.assertNotIn(forbidden, frame)
        self.assertEqual(tuple(frame['candidates']), CHANNELS)

    def test_sensor_cannot_depend_on_future_or_evaluation_metadata(self):
        for world in self.worlds:
            altered = replace(world, future_uniform=1-world.future_uniform,
                              error_type='arbitrary_label', relevant_channel='arbitrary_label')
            for channel in CHANNELS:
                for mode in ('repeat', 'relevant', 'irrelevant'):
                    self.assertEqual(query(world, channel, mode), query(altered, channel, mode))

    def test_queries_are_order_independent_and_reproducible(self):
        world = self.worlds[0]
        forward = {c: query(world, c, seed_key=29) for c in CHANNELS}
        reverse = {c: query(world, c, seed_key=29) for c in reversed(CHANNELS)}
        self.assertEqual(forward, reverse)
        # Unrelated requests cannot advance a mutable random stream.
        for c in CHANNELS:
            query(world, c, seed_key=999)
        self.assertEqual(forward, {c: query(world, c, seed_key=29) for c in CHANNELS})

    def test_repeat_contains_exactly_existing_channel_values(self):
        for world in self.worlds:
            for channel in CHANNELS:
                response = query(world, channel, 'repeat', accuracy=0., cost=3.)
                self.assertEqual(response.value,
                                 {f: getattr(world.frame.initial, f) for f in FIELDS[channel]})
                self.assertEqual(apply_response(world.frame.initial, response), world.frame.initial)

    def test_irrelevant_observation_never_changes_decision_evidence(self):
        for world in self.worlds:
            for channel in CHANNELS:
                response = query(world, channel, 'irrelevant')
                self.assertEqual(set(response.value), {'nuisance'})
                self.assertEqual(apply_response(world.frame.initial, response), world.frame.initial)

    def test_cost_and_accuracy_are_distinct_parameters(self):
        world = self.worlds[0]
        for mode in ('repeat', 'relevant', 'irrelevant'):
            cheap = query(world, 'harm', mode, accuracy=.55, cost=.1)
            costly = query(world, 'harm', mode, accuracy=.55, cost=8.)
            self.assertEqual(cheap.value, costly.value)
            self.assertEqual(cheap.source_accuracy, .55 if mode == 'relevant' else None)
            self.assertEqual(costly.cost, 8.)
        a = query(world, 'harm', 'irrelevant', accuracy=0., cost=1.)
        b = query(world, 'harm', 'irrelevant', accuracy=1., cost=1.)
        self.assertEqual(a.value, b.value)

    def test_perfect_and_wrong_sensors_measure_only_their_channel(self):
        for world in self.worlds:
            expected = reference_evidence(world)
            for channel in CHANNELS:
                correct = query(world, channel, accuracy=1.)
                incorrect = query(world, channel, accuracy=0.)
                self.assertEqual(set(correct.value), set(FIELDS[channel]))
                for field in FIELDS[channel]:
                    self.assertEqual(correct.value[field], getattr(expected, field))
                    self.assertNotEqual(incorrect.value[field], getattr(expected, field))
                # Operational measurements cannot erase separate procedural uncertainty.
                updated = apply_response(world.frame.initial, correct)
                self.assertEqual(updated.uncertainty, world.frame.initial.uncertainty)

    def test_alternative_feedback_cannot_reveal_primary_consequences(self):
        world = self.worlds[0]
        facts = dict(world.physical)
        facts.update(hazard=True, restricted=True, license=False, consent_granted=False,
                     backup=False, connected=False)
        altered = replace(world, physical=tuple(sorted(facts.items())), future_uniform=0.)
        self.assertEqual(selected_feedback(world, 'alternative'),
                         selected_feedback(altered, 'alternative'))
        self.assertIsNone(selected_feedback(world, None))

    def test_primary_feedback_cannot_reveal_unselected_alternative(self):
        world = self.worlds[0]
        facts = dict(world.physical)
        facts['fallback_blocked'] = not facts['fallback_blocked']
        altered = replace(world, physical=tuple(sorted(facts.items())))
        self.assertEqual(selected_feedback(world, 'primary'), selected_feedback(altered, 'primary'))

    def test_evidence_validation_and_serialization(self):
        evidence = Evidence()
        self.assertEqual(Evidence(**json.loads(json.dumps(to_dict(evidence)))), evidence)
        with self.assertRaises(FrozenInstanceError):
            evidence.harm = .5
        for bad in (-.1, 1.1, float('nan'), float('inf'), True):
            with self.assertRaises(ValueError):
                Evidence(harm=bad)
        with self.assertRaises(ValueError):
            Evidence(exposed=1)
        with self.assertRaises(ValueError):
            query(self.worlds[0], 'not_a_sensor')
        with self.assertRaises(ValueError):
            query(self.worlds[0], 'harm', mode='not_a_mode')
        with self.assertRaises(ValueError):
            query(self.worlds[0], 'harm', accuracy=1.1)
        with self.assertRaises(ValueError):
            query(self.worlds[0], 'harm', cost=-1.)

    def test_episode_reconstruction_and_complete_sensor_availability(self):
        for family in self.development:
            first = build_episode(family, 13, self.config)
            second = build_episode(family['id'], 13, self.config)
            self.assertEqual(first, second)
            self.assertEqual(len(first), 8)
            self.assertTrue(all(w.frame.candidates == CHANNELS for w in first))
            self.assertEqual(len({w.key for w in first}), 8)

    def test_task_completion_and_safe_completion_are_separate(self):
        world = self.worlds[0]
        facts = dict(world.physical)
        facts.update(hazard=True, shield=False, connected=True, isolated=False,
                     moderate=False, disputed=False, fallback_resource=True, fallback_blocked=False)
        hazardous = replace(world, physical=tuple(sorted(facts.items())), future_uniform=0.)
        score = evaluate(hazardous, 'primary', 'ALLOW')
        self.assertTrue(score['task_success'])
        self.assertFalse(score['safe_task_success'])
        self.assertTrue(score['harmful_action'])
        self.assertTrue(score['realized_harm'])
        alternative = evaluate(hazardous, 'alternative', 'MODIFY')
        self.assertTrue(alternative['safe_task_success'])
        self.assertFalse(alternative['harmful_action'])


if __name__ == '__main__':
    unittest.main()
