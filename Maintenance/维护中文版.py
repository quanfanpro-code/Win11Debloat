"""正式版同步、汉化变化检查与中文待办报告。只使用 Python 标准库。"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import tempfile
import urllib.error
import urllib.request

REPOSITORY = 'quanfanpro-code/Win11Debloat'
UPSTREAM = 'https://github.com/Raphire/Win11Debloat.git'
ISSUE_TITLE = '[自动同步] 正式版同步与汉化检查'
STATE = 'Maintenance/同步状态.json'
BASELINE = 'Maintenance/汉化基线.json'


def parse_json(text):
    """拒绝 PowerShell 无法区分的大小写重复键。"""
    def unique(pairs):
        result, seen = {}, set()
        for key, value in pairs:
            if key.casefold() in seen:
                raise ValueError(f'重复的 JSON 键：{key}')
            seen.add(key.casefold())
            result[key] = value
        return result
    return json.loads(text, object_pairs_hook=unique)


def read_json(path):
    return parse_json(Path(path).read_text(encoding='utf-8-sig'))


def write_json(path, data):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')


def git(root, *args, check=True):
    """以参数数组调用 Git，不执行来自版本名称的 shell 代码。"""
    result = subprocess.run(['git', '-C', str(root), *args], capture_output=True, text=True, encoding='utf-8', errors='replace')
    if check and result.returncode:
        raise RuntimeError(f'Git 操作失败（{args[0]}）：{result.stderr.strip()}')
    return result


def flatten(value, prefix=''):
    result = {}
    if isinstance(value, dict):
        for key, child in value.items():
            escaped = key.replace('~', '~0').replace('/', '~1')
            result.update(flatten(child, prefix + '/' + escaped))
    else:
        result[prefix] = value
    return result


def catalog(root, language):
    folder = root / 'Config/Languages' / language
    files = sorted(folder.glob('*.json'))
    if not files:
        raise ValueError(f'未找到语言资源：{language}')
    result = {}
    for path in files:
        result.update(flatten(read_json(path), path.name))
    return result


def compare(english, chinese, baseline):
    """发现缺译、旧译和格式错误；不以键存在代替翻译已经复核。"""
    issues = []
    placeholders = lambda text: Counter(re.findall(r'(?<!\{)\{\d+(?:,-?\d+)?(?::[^{}]+)?\}(?!\})', text))
    for key, source in english.items():
        translated = chinese.get(key)
        if key not in baseline:
            issues.append(f'新增原文，需复核：{key}')
        elif baseline[key] != source:
            issues.append(f'原文变化，旧译文需复核：{key}')
        if not isinstance(source, str):
            issues.append(f'原文结构发生变化：{key}')
        if not isinstance(translated, str) or not translated.strip():
            issues.append(f'缺少有效译文：{key}')
        elif isinstance(source, str) and placeholders(source) != placeholders(translated):
            issues.append(f'占位符不一致：{key}')
        if isinstance(translated, str) and '\ufffd' in translated:
            issues.append(f'译文编码异常：{key}')
    issues += [f'原文删除，需清理对应译文：{key}' for key in baseline.keys() - english.keys()]
    issues += [f'多余译文：{key}' for key in chinese.keys() - english.keys()]
    return sorted(issues)


def runtime_changes(paths):
    """脚本或界面有变化时保守提示复核，覆盖未提取到语言资源的新文字。"""
    return [p for p in paths if p.startswith(('Scripts/', 'Schemas/')) or p in ('Win11Debloat.ps1', 'Run.bat', 'Config/Apps.json', 'Config/Features.json')]


def stable_tag(release):
    tag = release.get('tag_name', '')
    if release.get('draft') or release.get('prerelease') or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]*', tag):
        raise ValueError('不是可接受的正式发布版')
    if re.search(r'(?i)(?:^|[._-])(?:rc|alpha|beta|preview|pre)(?:\d|[._-]|$)', tag):
        raise ValueError('不跟随 RC 或预发布版本')
    return tag


def can_publish(issues, tests, conflict):
    return not issues and tests == 'success' and not conflict


def api(endpoint, data=None, method=None):
    token = os.environ['GH_TOKEN']
    request = urllib.request.Request('https://api.github.com/' + endpoint,
        data=None if data is None else json.dumps(data).encode(), method=method,
        headers={'Authorization': 'Bearer ' + token, 'Accept': 'application/vnd.github+json', 'X-GitHub-Api-Version': '2022-11-28', 'User-Agent': 'Win11Debloat-zh-CN-maintenance'})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def check_translation(root, work):
    write_json(work / 'check.json', {'issues': ['汉化检查未完成']})
    baseline = read_json(root / BASELINE)
    issues = compare(catalog(root, 'en-US'), catalog(root, 'zh-CN'), baseline['catalog'])
    changed = git(root, 'diff', '--name-only', baseline['reviewed_source'], 'HEAD').stdout.splitlines()
    issues += [f'运行代码或界面变化，需检查新增文字：{path}' for path in runtime_changes(changed)]
    write_json(work / 'check.json', {'issues': issues, 'entries': len(catalog(root, 'zh-CN'))})
    return issues


def prepare(root, work, release, upstream_url=UPSTREAM):
    """只拉取正式版，保存候选合并；冲突时回到原中文提交。"""
    state = read_json(root / STATE)
    tag = stable_tag(release)
    if git(root, 'status', '--porcelain', '--untracked-files=no').stdout.strip():
        raise RuntimeError('工作区存在未提交修改，停止同步')
    git(root, 'fetch', '--no-tags', upstream_url, 'refs/tags/' + tag)
    sha = git(root, 'rev-parse', 'FETCH_HEAD^{commit}').stdout.strip()
    base = git(root, 'rev-parse', 'HEAD').stdout.strip()
    if git(root, 'merge-base', '--is-ancestor', state['release_commit'], sha, check=False).returncode:
        raise RuntimeError('正式版历史回退或改写，停止自动同步')
    if tag == state['release_tag'] and sha != state['release_commit']:
        raise RuntimeError('同名正式版标签的提交发生变化，需人工确认')
    git(root, 'push', 'origin', sha + ':refs/heads/upstream/stable')
    info = {'tag': tag, 'sha': sha, 'base': base, 'update': tag != state['release_tag'], 'conflicts': [], 'candidate': None}
    write_json(work / 'sync.json', info)
    if info['update']:
        branch = f"sync/stable-{release['id']}-{base[:10]}"
        info['candidate'] = branch
        remote = git(root, 'ls-remote', '--heads', 'origin', 'refs/heads/' + branch).stdout.strip()
        if remote:
            git(root, 'fetch', 'origin', 'refs/heads/' + branch)
            for ancestor in (base, sha):
                if git(root, 'merge-base', '--is-ancestor', ancestor, 'FETCH_HEAD', check=False).returncode:
                    raise RuntimeError('已有候选分支不包含当前基线和正式版，保留分支并停止')
            git(root, 'switch', '-c', branch, 'FETCH_HEAD')
        else:
            git(root, 'switch', '-c', branch)
            merged = git(root, 'merge', '--no-ff', '--no-edit', sha, check=False)
            if merged.returncode:
                info['conflicts'] = git(root, 'diff', '--name-only', '--diff-filter=U').stdout.splitlines()
                if not info['conflicts']:
                    raise RuntimeError('合并失败：' + merged.stderr)
                git(root, 'merge', '--abort')
    write_json(work / 'sync.json', info)
    return info


def publish_issue(body, failed):
    """在自己的仓库复用一个报告，内容不变时不重复发布。"""
    existing = None
    for page in range(1, 11):
        rows = api(f'repos/{REPOSITORY}/issues?state=open&per_page=100&page={page}')
        existing = next((x for x in rows if x['title'] == ISSUE_TITLE and not x.get('pull_request')), None)
        if existing or len(rows) < 100:
            break
    if failed:
        if existing:
            if existing.get('body') != body:
                api(f"repos/{REPOSITORY}/issues/{existing['number']}", {'body': body}, 'PATCH')
        else:
            api(f'repos/{REPOSITORY}/issues', {'title': ISSUE_TITLE, 'body': body}, 'POST')
    elif existing:
        api(f"repos/{REPOSITORY}/issues/{existing['number']}", {'state':'closed', 'body':body}, 'PATCH')


def finish(root, work, tests):
    info = read_json(work / 'sync.json')
    check = read_json(work / 'check.json') if (work / 'check.json').exists() else {'issues':['汉化检查未完成']}
    issues = check['issues'] + [f'合并冲突：{p}' for p in info['conflicts']]
    if tests != 'success':
        issues.append('测试未通过或未完整执行，禁止更新可用中文分支')
    ready = can_publish(issues, tests, bool(info['conflicts']))
    if info['update'] and not info['conflicts']:
        git(root, 'push', 'origin', 'HEAD:refs/heads/' + info['candidate'])
    if ready:
        state = read_json(root / STATE)
        month = datetime.now(timezone.utc).strftime('%Y-%m')
        if info['update'] or state.get('last_checked_month') != month:
            state.update(release_tag=info['tag'], release_commit=info['sha'], last_checked_month=month)
            write_json(root / STATE, state)
            git(root, 'add', '--', STATE)
            git(root, 'commit', '-m', '记录正式版同步与汉化检查通过：' + info['tag'])
            git(root, 'push', 'origin', 'HEAD:refs/heads/zh-CN')
    lines = ['# 正式版同步与汉化检查', '', f"官方正式版：{info['tag']}", f"官方提交：{info['sha']}", '',
        '结果：检查通过，中文分支可用。' if ready else '结果：需要处理以下项目，当前可用中文分支保持不变。']
    if info['candidate']:
        lines += ['', f"候选分支：{info['candidate']}"]
    lines += ['', *['- ' + item for item in issues]]
    body = '\n'.join(lines) + '\n'
    (work / '报告.md').write_text(body, encoding='utf-8-sig')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as summary:
            summary.write(body)
    publish_issue(body, not ready)
    print(body)
    return ready


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode', choices=['check','baseline','prepare','finish'])
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--work', type=Path, default=Path(os.environ.get('RUNNER_TEMP', tempfile.gettempdir())) / 'Win11Debloat-zh-CN-check')
    parser.add_argument('--tests', default='failure')
    args = parser.parse_args()
    args.work.mkdir(parents=True, exist_ok=True)
    if args.mode == 'baseline':
        write_json(args.root / BASELINE, {'reviewed_source': git(args.root, 'rev-parse', 'HEAD').stdout.strip(), 'catalog': catalog(args.root, 'en-US')})
        print('已记录人工复核基线；仅在确认译文和源码文字均已复核后执行此操作。')
    elif args.mode == 'check':
        issues = check_translation(args.root, args.work)
        print('\n'.join(issues) if issues else '汉化检查通过')
        return 1 if issues else 0
    else:
        if os.environ.get('GITHUB_REPOSITORY') != REPOSITORY or os.environ.get('GITHUB_REF') != 'refs/heads/zh-CN':
            raise RuntimeError('远端写操作仅允许在自己的 zh-CN 分支工作流中运行')
        if args.mode == 'prepare':
            release = api('repos/Raphire/Win11Debloat/releases/latest')
            info = prepare(args.root, args.work, release)
            print(f"正式版 {info['tag']}，需要同步：{info['update']}，冲突：{bool(info['conflicts'])}")
        else:
            return 0 if finish(args.root, args.work, args.tests) else 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
