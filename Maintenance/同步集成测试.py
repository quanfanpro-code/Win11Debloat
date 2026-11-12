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
        self.put(self.upstream, '.github/workflows/tests.yml', 'name: Original tests\n')
        self.commit(self.upstream, '初始正式版')
        self.old = self.run_git(self.upstream, 'rev-parse', 'HEAD')
        self.run_git(self.upstream, 'tag', 'v1')
        subprocess.run(['git','init','--bare',str(self.origin)], check=True, capture_output=True)
        subprocess.run(['git','clone',str(self.upstream),str(self.root)], check=True, capture_output=True)
        self.identity(self.root)
        self.run_git(self.root, 'remote','set-url','origin',str(self.origin))
        self.run_git(self.root, 'switch','-c','zh-CN')
        self.put(self.root, '.github/workflows/sync-stable.yml', 'name: Local sync\n')
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

    def release(self, path, content, tag='v2', release_id=2):
        self.put(self.upstream, path, content)
        self.commit(self.upstream,'正式版更新')
        self.run_git(self.upstream,'tag',tag)
        return {'id':release_id,'tag_name':tag,'draft':False,'prerelease':False}

    def fresh_checkout(self, name='rerun'):
        fresh = self.folder / name
        subprocess.run(['git', 'clone', '--branch', 'zh-CN', str(self.origin), str(fresh)],
                       check=True, capture_output=True)
        self.identity(fresh)
        return fresh

    def reject_workflow_pushes(self):
        # 用接收钩子检查远端尚未拥有的每一个提交，包括新增分支和被撤回的改动。
        hook = self.origin / 'hooks/pre-receive'
        hook.with_suffix('.py').write_text("""import subprocess
import sys

for line in sys.stdin:
    old, new, ref = line.split()
    if set(new) == {'0'}:
        continue
    commits = subprocess.check_output(['git', 'rev-list', new, '--not', '--all']).split()
    for commit in commits:
        paths = subprocess.check_output(['git', 'diff-tree', '-m', '--root', '--no-commit-id',
                                         '--name-only', '-r', commit.decode(), '--', '.github/workflows'])
        if paths:
            sys.exit(f'test remote: workflow write denied ({ref})')
""", encoding='utf-8')
        hook.write_bytes(b'#!/bin/sh\nexec python "$0.py"\n')
        hook.chmod(0o755)

    def test_正常更新后中文保留且重复执行不新增提交(self):
        self.reject_workflow_pushes()
        release = self.release('README.md','新版说明\n')
        info = m.prepare(self.root,self.work,release,str(self.upstream))
        self.assertTrue(info['update'])
        self.assertEqual(m.check_translation(self.root,self.work), [])
        self.assertTrue(m.finish(self.root,self.work,'success'))
        self.assertNotEqual(self.remote_head(),self.base)
        self.assertEqual(self.run_git(self.root, 'ls-remote', 'origin', 'refs/heads/upstream/stable'), '')
        self.assertEqual(m.git(self.root, 'merge-base', '--is-ancestor', info['sha'], 'HEAD', check=False).returncode, 1)
        self.assertEqual(self.run_git(self.root, 'diff', '--name-only', self.base, 'HEAD', '--', m.WORKFLOWS), '')
        self.assertEqual(m.read_json(self.root/m.STATE)['release_commit'], info['sha'])
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

        fresh = self.fresh_checkout('resolve')
        self.run_git(fresh, 'fetch', '--no-tags', str(self.upstream), 'refs/tags/v2')
        self.run_git(fresh, 'switch', '-c', info['candidate'], base)
        source = self.run_git(fresh, 'commit-tree', f"{info['sha']}^{{tree}}", '-p', info['merge_base'],
                              '-m', m.release_message(info['tag'], info['sha']))
        self.assertNotEqual(m.git(fresh, 'cherry-pick', '--empty=keep', source, check=False).returncode, 0)
        self.put(fresh, 'README.md', '已复核的中文新版说明\n')
        self.run_git(fresh, 'add', '--', 'README.md')
        self.run_git(fresh, '-c', 'core.editor=:', 'cherry-pick', '--continue')
        self.run_git(fresh, 'push', 'origin', 'HEAD:' + info['candidate'])
        rerun = self.fresh_checkout()
        self.assertEqual(m.prepare(rerun, self.work, release, str(self.upstream))['conflicts'], [])
        self.assertEqual(m.check_translation(rerun, self.work), [])
        self.assertTrue(m.finish(rerun, self.work, 'success'))
        self.assertEqual((rerun/'README.md').read_text(encoding='utf-8'), '已复核的中文新版说明\n')

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
        fresh = self.fresh_checkout()
        repeated = m.prepare(fresh,self.work,release,str(self.upstream))
        self.assertEqual(repeated['candidate'],info['candidate'])
        self.assertEqual(m.check_translation(fresh,self.work),[])
        self.assertTrue(m.finish(fresh,self.work,'success'))
        self.assertEqual(m.read_json(fresh/'Config/Languages/zh-CN/Chrome.json')['Open'],'移除 {0}')
        self.assertEqual(self.remote_head(),self.run_git(fresh,'rev-parse','HEAD'))

    def test_新增和修改工作流先报告人工审核再同步(self):
        self.put(self.upstream, '.github/workflows/obsolete.yml', 'name: Added after v1\n')
        self.commit(self.upstream, '上游未发布的工作流变更')
        self.run_git(self.upstream, 'rm', '.github/workflows/obsolete.yml')
        self.put(self.upstream, '.github/workflows/tests.yml', 'name: Official tests v2\n')
        release = self.release('.github/workflows/release.yml', 'name: Official release\n')
        self.reject_workflow_pushes()

        info = m.prepare(self.root, self.work, release, str(self.upstream))
        self.assertEqual(info['conflicts'], [])
        denied = m.git(self.root, 'push', 'origin', info['sha'] + ':refs/heads/upstream/stable', check=False)
        self.assertNotEqual(denied.returncode, 0)
        self.assertIn('test remote: workflow write denied', denied.stderr)
        self.assertEqual(m.check_translation(self.root, self.work), [])
        self.assertFalse(m.finish(self.root, self.work, 'success'))
        self.assertEqual(self.remote_head(), self.base)
        for ref in ('upstream/stable', info['candidate']):
            self.assertEqual(self.run_git(self.root, 'ls-remote', 'origin', 'refs/heads/' + ref), '')
        report = (self.work/'报告.md').read_text(encoding='utf-8-sig')
        for path in ('release.yml', 'tests.yml'):
            self.assertIn(f'工作流需维护者审查并单独更新：.github/workflows/{path}', report)

        # 模拟维护者已单独审核并提交上述工作流，随后恢复原有限权限。
        (self.origin / 'hooks/pre-receive').unlink()
        fresh = self.fresh_checkout()
        self.run_git(fresh, 'fetch', '--no-tags', str(self.upstream), 'refs/tags/v2')
        self.run_git(fresh, 'restore', '--source=FETCH_HEAD', '--staged', '--worktree', '--',
                     '.github/workflows/release.yml', '.github/workflows/tests.yml')
        self.run_git(fresh, 'commit', '-m', '单独更新已审工作流')
        self.run_git(fresh, 'push', 'origin', 'HEAD:zh-CN')
        reviewed_base = self.remote_head()
        self.reject_workflow_pushes()
        prepared = m.prepare(fresh, self.work, release, str(self.upstream))
        self.assertEqual(prepared['conflicts'], [])
        self.assertEqual(m.check_translation(fresh, self.work), [])
        self.assertTrue(m.finish(fresh, self.work, 'success'))
        self.assertEqual(self.run_git(fresh, 'diff', '--name-only', reviewed_base, 'HEAD', '--', m.WORKFLOWS), '')
        self.assertEqual(m.read_json(fresh/m.STATE)['release_commit'], info['sha'])

    def test_上游删除工作流也阻止自动发布(self):
        self.run_git(self.upstream, 'rm', '.github/workflows/tests.yml')
        release = self.release('README.md', '新版说明\n')
        self.reject_workflow_pushes()
        info = m.prepare(self.root, self.work, release, str(self.upstream))
        self.assertEqual(info['conflicts'], [])
        self.assertEqual(m.check_translation(self.root, self.work), [])
        self.assertFalse(m.finish(self.root, self.work, 'success'))
        self.assertEqual(self.remote_head(), self.base)
        self.assertIn('.github/workflows/tests.yml', (self.work/'报告.md').read_text(encoding='utf-8-sig'))

    def test_候选工作流冲突和中文内容冲突均上报(self):
        self.put(self.root, '.github/workflows/tests.yml', 'name: Local tests\n')
        self.put(self.root, 'README.md', '中文说明\n')
        self.commit(self.root, '自定义工作流和中文说明')
        self.run_git(self.root, 'push', 'origin', 'HEAD:zh-CN')
        base = self.remote_head()
        self.put(self.upstream, '.github/workflows/tests.yml', 'name: Official tests v2\n')
        release = self.release('README.md', '新版说明\n')
        self.reject_workflow_pushes()
        info = m.prepare(self.root, self.work, release, str(self.upstream))
        self.assertCountEqual(info['conflicts'], ['README.md', '.github/workflows/tests.yml'])
        self.assertEqual(self.run_git(self.root, 'status', '--porcelain'), '')
        self.assertFalse(m.finish(self.root, self.work, 'skipped'))
        self.assertEqual(self.remote_head(), base)
        self.assertEqual(self.run_git(self.root, 'ls-remote', 'origin', 'refs/heads/' + info['candidate']), '')

    def test_候选曾修改工作流即使撤回也不推进中文分支(self):
        release = self.release('README.md', '新版说明\n')
        info = m.prepare(self.root, self.work, release, str(self.upstream))
        self.put(self.root, '.github/workflows/tests.yml', 'name: Temporary tests\n')
        self.commit(self.root, '临时修改工作流')
        self.run_git(self.root, 'revert', '--no-edit', 'HEAD')
        self.run_git(self.root, 'push', 'origin', 'HEAD:' + info['candidate'])
        self.reject_workflow_pushes()
        fresh = self.fresh_checkout()
        m.prepare(fresh, self.work, release, str(self.upstream))
        self.assertEqual(m.check_translation(fresh, self.work), [])
        self.assertFalse(m.finish(fresh, self.work, 'success'))
        self.assertEqual(self.remote_head(), self.base)
        self.assertIn('工作流需维护者审查并单独更新：.github/workflows/tests.yml',
                      (self.work/'报告.md').read_text(encoding='utf-8-sig'))

    def test_下一正式版以上次正式版为基准保留中文版改动(self):
        self.reject_workflow_pushes()
        previous = m.prepare(self.root, self.work, self.release('README.md', '第二版说明\n'), str(self.upstream))
        self.assertEqual(m.check_translation(self.root, self.work), [])
        self.assertTrue(m.finish(self.root, self.work, 'success'))
        self.put(self.root, 'README.md', '第二版中文说明\n')
        self.commit(self.root, '本地化第二版说明')
        self.run_git(self.root, 'push', 'origin', 'HEAD:zh-CN')
        fresh = self.fresh_checkout()
        release = self.release('NEWS.md', '第三版更新\n', tag='v3', release_id=3)
        info = m.prepare(fresh, self.work, release, str(self.upstream))
        self.assertEqual(info['merge_base'], previous['sha'])
        self.assertEqual(info['conflicts'], [])
        self.assertEqual(m.check_translation(fresh, self.work), [])
        self.assertTrue(m.finish(fresh, self.work, 'success'))
        self.assertEqual((fresh/'README.md').read_text(encoding='utf-8'), '第二版中文说明\n')
        self.assertEqual(m.read_json(fresh/m.STATE)['release_tag'], 'v3')

    def test_采用比旧正式版更新的真实共同祖先(self):
        self.put(self.upstream, 'README.md', '开发版说明\n')
        self.commit(self.upstream, '正式版之间的开发提交')
        self.run_git(self.root, 'fetch', '--no-tags', str(self.upstream), 'HEAD')
        common = self.run_git(self.root, 'rev-parse', 'FETCH_HEAD')
        self.run_git(self.root, 'merge', '--no-edit', 'FETCH_HEAD')
        self.put(self.root, 'README.md', '开发版中文说明\n')
        self.commit(self.root, '本地化开发版说明')
        self.run_git(self.root, 'push', 'origin', 'HEAD:zh-CN')
        release = self.release('NEWS.md', '第二版更新\n')
        info = m.prepare(self.root, self.work, release, str(self.upstream))
        self.assertEqual(info['merge_base'], common)
        self.assertEqual(info['conflicts'], [])
        self.assertEqual((self.root/'README.md').read_text(encoding='utf-8'), '开发版中文说明\n')

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
