"""用真实本地 Git 仓库验证同步，不联网、不修改用户仓库，不自动删除测试目录。"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
spec = importlib.util.spec_from_file_location('maintenance', Path(__file__).with_name('维护中文版.py'))
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class SyncTests(unittest.TestCase):
    def setUp(self):
        self.folder = Path(tempfile.mkdtemp(prefix='Win11Debloat-sync-test-'))
        self.upstream = self.folder / 'upstream'
        self.origin = self.folder / 'origin.git'
        self.root = self.folder / 'chinese'
        self.work = self.folder / 'report'
        self.work.mkdir()
        self.upstream.mkdir()
        self.run_git(self.upstream, 'init', '-b', 'master')
        self.identity(self.upstream)
        self.put(self.upstream, 'README.md', '原始说明\n')
        self.put(self.upstream, 'Config/Languages/en-US/Chrome.json', '{"Open":"Open {0}"}')
        self.put(self.upstream, 'Config/Languages/zh-CN/Chrome.json', '{"Open":"打开 {0}"}')
        self.commit(self.upstream, '初始正式版')
        self.old = self.run_git(self.upstream, 'rev-parse', 'HEAD')
        self.run_git(self.upstream, 'tag', 'v1')
        subprocess.run(['git','init','--bare',str(self.origin)], check=True, capture_output=True)
        subprocess.run(['git','clone',str(self.upstream),str(self.root)], check=True, capture_output=True)
        self.identity(self.root)
        self.run_git(self.root, 'remote','set-url','origin',str(self.origin))
        self.run_git(self.root, 'switch','-c','zh-CN')
        self.put(self.root, m.STATE, json.dumps({'release_tag':'v1','release_commit':self.old,'last_checked_month':'2000-01'}))
        self.put(self.root, m.BASELINE, json.dumps({'reviewed_source':self.old,'catalog':{'Chrome.json/Open':'Open {0}'}}))
        self.commit(self.root, '中文维护配置')
        self.run_git(self.root, 'push','origin','HEAD:zh-CN')
        self.base = self.remote_head()
        self.original_api = m.api
        m.api = lambda endpoint, data=None, method=None: [] if data is None else {'number':1}

    def tearDown(self):
        m.api = self.original_api

    def run_git(self, root, *args):
        return m.git(root, *args).stdout.strip()

    def identity(self, root):
        self.run_git(root,'config','user.name','维护测试')
        self.run_git(root,'config','user.email','test@example.invalid')

    def put(self, root, path, content):
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding='utf-8')

    def commit(self, root, message):
        self.run_git(root,'add','.')
        self.run_git(root,'commit','-m',message)

    def remote_head(self):
        return self.run_git(self.root,'ls-remote','origin','refs/heads/zh-CN').split()[0]

    def release(self, path, content):
        self.put(self.upstream, path, content)
        self.commit(self.upstream,'正式版更新')
        self.run_git(self.upstream,'tag','v2')
        return {'id':2,'tag_name':'v2','draft':False,'prerelease':False}

    def test_正常更新后中文保留且重复执行不新增提交(self):
        release = self.release('README.md','新版说明\n')
        info = m.prepare(self.root,self.work,release,str(self.upstream))
        self.assertTrue(info['update'])
        self.assertEqual(m.check_translation(self.root,self.work), [])
        self.assertTrue(m.finish(self.root,self.work,'success'))
        self.assertNotEqual(self.remote_head(),self.base)
        self.assertEqual(m.read_json(self.root/'Config/Languages/zh-CN/Chrome.json')['Open'],'打开 {0}')
        completed = self.remote_head()
        info = m.prepare(self.root,self.work,release,str(self.upstream))
        self.assertFalse(info['update'])
        m.check_translation(self.root,self.work)
        self.assertTrue(m.finish(self.root,self.work,'success'))
        self.assertEqual(self.remote_head(),completed)

    def test_原文变化留下候选和报告但不更新可用版本(self):
        release = self.release('Config/Languages/en-US/Chrome.json','{"Open":"Remove {0}"}')
        info = m.prepare(self.root,self.work,release,str(self.upstream))
        self.assertTrue(m.check_translation(self.root,self.work))
        self.assertFalse(m.finish(self.root,self.work,'success'))
        self.assertEqual(self.remote_head(),self.base)
        self.assertTrue(self.run_git(self.root,'ls-remote','origin','refs/heads/'+info['candidate']))
        self.assertIn('原文变化',(self.work/'报告.md').read_text(encoding='utf-8-sig'))

    def test_合并冲突保留本地内容和可用分支(self):
        self.put(self.root,'README.md','中文专用说明\n')
        self.commit(self.root,'中文说明')
        self.run_git(self.root,'push','origin','HEAD:zh-CN')
        base = self.remote_head()
        release = self.release('README.md','官方新版说明\n')
        info = m.prepare(self.root,self.work,release,str(self.upstream))
        self.assertEqual(info['conflicts'],['README.md'])
        self.assertEqual((self.root/'README.md').read_text(encoding='utf-8'),'中文专用说明\n')
        m.check_translation(self.root,self.work)
        self.assertFalse(m.finish(self.root,self.work,'success'))
        self.assertEqual(self.remote_head(),base)

    def test_测试失败不能发布(self):
        release = self.release('README.md','新版说明\n')
        m.prepare(self.root,self.work,release,str(self.upstream))
        m.check_translation(self.root,self.work)
        self.assertFalse(m.finish(self.root,self.work,'failure'))
        self.assertEqual(self.remote_head(),self.base)

    def test_人工补译后复用候选并通过同步(self):
        release = self.release('Config/Languages/en-US/Chrome.json','{"Open":"Remove {0}"}')
        info = m.prepare(self.root,self.work,release,str(self.upstream))
        m.check_translation(self.root,self.work)
        self.assertFalse(m.finish(self.root,self.work,'success'))
        self.put(self.root,'Config/Languages/zh-CN/Chrome.json','{"Open":"移除 {0}"}')
        self.commit(self.root,'补译并复核')
        m.write_json(self.root/m.BASELINE, {'reviewed_source':self.run_git(self.root,'rev-parse','HEAD'),'catalog':m.catalog(self.root,'en-US')})
        self.commit(self.root,'记录复核基线')
        self.run_git(self.root,'push','origin','HEAD:'+info['candidate'])
        fresh = self.folder/'rerun'
        subprocess.run(['git','clone','--branch','zh-CN',str(self.origin),str(fresh)],check=True,capture_output=True)
        self.identity(fresh)
        repeated = m.prepare(fresh,self.work,release,str(self.upstream))
        self.assertEqual(repeated['candidate'],info['candidate'])
        self.assertEqual(m.check_translation(fresh,self.work),[])
        self.assertTrue(m.finish(fresh,self.work,'success'))
        self.assertEqual(m.read_json(fresh/'Config/Languages/zh-CN/Chrome.json')['Open'],'移除 {0}')
        self.assertEqual(self.remote_head(),self.run_git(fresh,'rev-parse','HEAD'))

    def test_正式版历史回退不能发布(self):
        release = self.release('README.md','新版说明\n')
        m.prepare(self.root,self.work,release,str(self.upstream))
        m.check_translation(self.root,self.work)
        self.assertTrue(m.finish(self.root,self.work,'success'))
        completed = self.remote_head()
        with self.assertRaisesRegex(RuntimeError,'历史回退'):
            m.prepare(self.root,self.work,{'id':1,'tag_name':'v1'},str(self.upstream))
        self.assertEqual(self.remote_head(),completed)

    def test_解析失败不能沿用上次通过报告(self):
        release = self.release('README.md','新版说明\n')
        m.prepare(self.root,self.work,release,str(self.upstream))
        self.assertEqual(m.check_translation(self.root,self.work),[])
        self.put(self.root,'Config/Languages/zh-CN/Chrome.json','坏 JSON')
        with self.assertRaises(ValueError):
            m.check_translation(self.root,self.work)
        self.assertFalse(m.finish(self.root,self.work,'success'))
        self.assertEqual(self.remote_head(),self.base)


if __name__ == '__main__':
    unittest.main(verbosity=2)
