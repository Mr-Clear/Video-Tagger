from datetime import datetime
import unittest

from Ui.MainWindow import MainWindow
from Ui.TagListModel import TagListModel
from VideoFile import VideoFile


class TestTagListModel(unittest.TestCase):
    def test_init(self):
        tags = {'tag1': 1, 'tag2': 2}
        tag_list_model = TagListModel(tags)
        self.assertEqual(tag_list_model.tags, tags)
        self.assertEqual(tag_list_model.tag_names, ['tag1', 'tag2'])
        self.assertEqual(tag_list_model.checked_tags, set())
        self.assertEqual(tag_list_model._current_file, None)
        self.assertEqual(tag_list_model._max_count, 2)

    def test_get_available_tags_for_selected_files(self):
        files = [
            VideoFile(1, '/tmp/a.mp4', 1, datetime.now(), tags={'alpha', 'beta'}),
            VideoFile(2, '/tmp/b.mp4', 1, datetime.now(), tags={'beta', 'gamma'})
        ]

        self.assertEqual(MainWindow.get_available_tags_for_files(files), ['alpha', 'beta', 'gamma'])
