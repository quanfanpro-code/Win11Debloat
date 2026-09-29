"""正式版筛选与汉化检查的行为测试，仅使用标准库。"""
import importlib.util
from pathlib import Path
import unittest

SCRIPT = Path(__file__).with_name('维护中文版.py')


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.assertTrue(SCRIPT.exists(), '尚未实现中文分支维护程序')
        spec = importlib.util.spec_from_file_location('maintenance', SCRIPT)
        self.m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.m)

    def test_已复核的译文通过(self):
        self.assertEqual(self.m.compare({'A':'Open {0}'}, {'A':'打开 {0}'}, {'A':'Open {0}'}), [])

    def test_原文变化即使键未变也提示复核(self):
        issues = self.m.compare({'A':'Remove all'}, {'A':'移除'}, {'A':'Remove'})
        self.assertTrue(any('原文变化' in x for x in issues))

    def test_新增英文必须复核(self):
        self.assertTrue(any('新增原文' in x for x in self.m.compare({'B':'New'}, {'B':'新'}, {})))

    def test_缺译和空译不能通过(self):
        for zh in ({}, {'A':'  '}):
            with self.subTest(zh=zh):
                self.assertTrue(any('缺少有效译文' in x for x in self.m.compare({'A':'Open'}, zh, {'A':'Open'})))

    def test_格式参数不能丢失(self):
        self.assertTrue(any('占位符' in x for x in self.m.compare({'A':'Open {0}'}, {'A':'打开'}, {'A':'Open {0}'})))

    def test_已删除的原文和多余译文可见(self):
        issues = self.m.compare({}, {'A':'旧'}, {'A':'Old'})
        self.assertTrue(any('原文删除' in x for x in issues))
        self.assertTrue(any('多余译文' in x for x in issues))

    def test_拒绝大小写重复键(self):
        with self.assertRaises(ValueError):
            self.m.parse_json('{"Name":"a","name":"b"}')

    def test_正式版排除草稿及测试版(self):
        for release in ({'tag_name':'v1','draft':True}, {'tag_name':'v1','prerelease':True}, {'tag_name':'v2-RC1'}, {'tag_name':'v2-beta'}):
            with self.subTest(release=release):
                with self.assertRaises(ValueError):
                    self.m.stable_tag(release)
        self.assertEqual(self.m.stable_tag({'tag_name':'2026.08.24'}), '2026.08.24')

    def test_版本名不可作为命令选项(self):
        with self.assertRaises(ValueError):
            self.m.stable_tag({'tag_name':'--upload-pack=bad'})

    def test_运行脚本变动需人工复核文档不阻塞(self):
        self.assertEqual(self.m.runtime_changes(['README.md','docs/a.md']), [])
        self.assertEqual(len(self.m.runtime_changes(['Scripts/GUI/new.ps1','Schemas/a.xaml','Config/Apps.json'])), 3)

    def test_只有完整通过才能发布(self):
        self.assertTrue(self.m.can_publish([], 'success', False))
        self.assertFalse(self.m.can_publish(['缺译'], 'success', False))
        self.assertFalse(self.m.can_publish([], 'failure', False))
        self.assertFalse(self.m.can_publish([], 'success', True))


if __name__ == '__main__':
    unittest.main(verbosity=2)
