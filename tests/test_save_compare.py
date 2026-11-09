"""Read-only approximate path comparisons; no implicit wrapper selection."""
import os
import unittest

from core.save_compare import compare_paths


class SaveCompareTests(unittest.TestCase):
    def test_paths_types_ancestors_and_unicode(self):
        candidates = [
            {'path': 'Slot.SAV', 'kind': 'file'},
            {'path': 'Saves', 'kind': 'directory'},
            {'path': 'wrong.sav', 'kind': 'file'},
            {'path': os.path.join('blocked', 'part.sav'), 'kind': 'file'},
            {'path': 'missing.sav', 'kind': 'file'},
            {'path': 'cafe\u0301.sav', 'kind': 'file'},
        ]
        entries = [
            {'path': 'slot.sav', 'kind': 'file'},
            {'path': 'saves/inside.dat', 'kind': 'file'},
            {'path': 'wrong.sav/child', 'kind': 'file'},
            {'path': 'blocked', 'kind': 'file'},
            {'path': 'caf\u00e9.sav', 'kind': 'file'},
        ]
        preview = {'game_folder': 'game', 'incomplete': True, 'scanned': 10,
                   'skipped': 1, 'candidates': candidates}
        result = compare_paths(preview, entries)
        self.assertEqual([c['relation'] for c in result['candidates']],
                         ['file_same_path', 'directory_shared', 'type_conflict',
                          'ancestor_file', 'not_found', 'file_same_path'])
        self.assertTrue(result['incomplete'])
        self.assertEqual(result['skipped'], 1)
        self.assertNotIn('relation', candidates[0])

    def test_explicit_directory_and_no_automatic_unwrapping(self):
        preview = {'game_folder': 'x', 'incomplete': False, 'scanned': 2, 'skipped': 0,
                   'candidates': [{'path': 'save.sav', 'kind': 'file'},
                                  {'path': 'saves', 'kind': 'directory'}]}
        entries = [{'path': 'wrapper/save.sav', 'kind': 'file'},
                   {'path': 'saves/', 'kind': 'directory'}]
        self.assertEqual([x['relation'] for x in compare_paths(preview, entries)['candidates']],
                         ['not_found', 'directory_shared'])

    @unittest.skipIf(os.name == 'nt', 'backslash is a directory separator on Windows')
    def test_literal_backslash_is_not_interpreted_as_separator(self):
        preview = {'game_folder': 'x', 'incomplete': False, 'scanned': 1, 'skipped': 0,
                   'candidates': [{'path': 'dir\\file.sav', 'kind': 'file'}]}
        self.assertEqual(compare_paths(preview, [{'path': 'dir/file.sav', 'kind': 'file'}])
                         ['candidates'][0]['relation'], 'unsupported_name')
