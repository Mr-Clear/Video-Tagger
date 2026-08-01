from Ui.TagListModel import TagListModel
import unittest

class TestTagListModel(unittest.TestCase):
    def test_init(self):
        tags = {'tag1': 1, 'tag2': 2}
        tag_list_model = TagListModel(tags)
        self.assertEqual(tag_list_model.tags, tags)
        self.assertEqual(tag_list_model.tag_names, ['tag1', 'tag2'])
        self.assertEqual(tag_list_model.checked_tags, set())
        self.assertEqual(tag_list_model._current_file, None)
        self.assertEqual(tag_list_model._max_count, 2)
