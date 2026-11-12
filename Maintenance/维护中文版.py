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
WORKFLOWS = '.github/workflows'


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


def release_message(tag, sha):
    return f'合并官方正式版 {tag}\n\nUpstream-release: {sha}'


def prepare(root, work, release, upstream_url=UPSTREAM):
    """把正式版增量三方合并为中文版上的单父提交。"""
    state = read_json(root / STATE)
    tag = stable_tag(release)
    if git(root, 'status', '--porcelain', '--untracked-files=no').stdout.strip():
        raise RuntimeError('工作区存在未提交修改，停止同步')
    git(root, 'fetch', '--no-tags', upstream_url, 'refs/tags/' + tag)
    sha = git(root, 'rev-parse', 'FETCH_HEAD^{commit}').stdout.strip()
    base = git(root, 'rev-parse', 'HEAD').stdout.strip()
    previous = state['release_commit']
    if git(root, 'merge-base', '--is-ancestor', previous, sha, check=False).returncode:
        raise RuntimeError('正式版历史回退或改写，停止自动同步')
    if tag == state['release_tag'] and sha != previous:
        raise RuntimeError('同名正式版标签的提交发生变化，需人工确认')
    info = {'tag': tag, 'sha': sha, 'base': base, 'update': tag != state['release_tag'],
            'conflicts': [], 'candidate': None, 'upstream_workflows': []}
    if info['update']:
        common = git(root, 'merge-base', base, sha).stdout.strip()
        # 初始中文版包含部分上游开发历史；压合发布后则以已同步的正式版为基准。
        merge_base = common
        if git(root, 'merge-base', '--is-ancestor', previous, common, check=False).returncode:
            merge_base = previous
        info['merge_base'] = merge_base
        info['upstream_workflows'] = git(
            root, 'diff', '--name-only', '-z', merge_base, sha, '--', WORKFLOWS
        ).stdout.split('\0')[:-1]
        branch = f"sync/stable-{release['id']}-{base[:10]}"
        info['candidate'] = branch
        remote = git(root, 'ls-remote', '--heads', 'origin', 'refs/heads/' + branch).stdout.strip()
        if remote:
            git(root, 'fetch', 'origin', 'refs/heads/' + branch)
            imports = git(root, 'rev-list', '--first-parent', '--reverse', f'{base}..FETCH_HEAD').stdout.splitlines()
            first = imports[0] if imports else None
            if first is None or git(root, 'rev-parse', f'{first}^@').stdout.splitlines() != [base]:
                raise RuntimeError('已有候选分支不基于当前中文提交，保留分支并停止')
            if git(root, 'show', '-s', '--format=%B', first).stdout.strip() != release_message(tag, sha):
                raise RuntimeError('已有候选分支不包含当前正式版的导入提交，保留分支并停止')
            git(root, 'switch', '-c', branch, 'FETCH_HEAD')
        else:
            # 只使用上游快照作为三方合并输入，原始提交及其工作流历史不进入候选祖先。
            source = git(root, 'commit-tree', f'{sha}^{{tree}}', '-p', merge_base,
                         '-m', release_message(tag, sha)).stdout.strip()
            git(root, 'switch', '-c', branch)
            merged = git(root, 'cherry-pick', '--empty=keep', source, check=False)
            if merged.returncode:
                info['conflicts'] = git(root, 'diff', '--name-only', '-z', '--diff-filter=U').stdout.split('\0')[:-1]
                if not info['conflicts']:
                    raise RuntimeError('合并失败：' + merged.stderr)
                git(root, 'cherry-pick', '--abort')
    info['head'] = git(root, 'rev-parse', 'HEAD').stdout.strip()
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
    if git(root, 'rev-parse', 'HEAD').stdout.strip() != info['head']:
        raise RuntimeError('检查期间候选提交发生变化，停止发布')
    check = read_json(work / 'check.json') if (work / 'check.json').exists() else {'issues':['汉化检查未完成']}
    issues = check['issues'] + [f'合并冲突：{p}' for p in info['conflicts']]
    if tests != 'success':
        issues.append('测试未通过或未完整执行，禁止更新可用中文分支')
    if git(root, 'status', '--porcelain', '--untracked-files=no').stdout.strip():
        issues.append('检查期间工作区出现未提交修改，禁止更新可用中文分支')
    candidate_pushed = False
    if info['update'] and not info['conflicts']:
        outgoing = f"{info['base']}..HEAD"
        if git(root, 'rev-list', '--merges', outgoing).stdout.strip():
            raise RuntimeError('候选包含合并提交，须以当前中文提交为起点提交正式版增量')
        # 检查将推送的每个提交，含后来又撤回的工作流修改。
        paths = git(root, 'log', '--format=', '--name-only', '-z', outgoing, '--', WORKFLOWS).stdout.split('\0')
        workflows = sorted(set(filter(None, paths)))
        issues += [f'工作流需维护者审查并单独更新：{path}' for path in workflows]
        if not workflows:
            git(root, 'push', '--no-follow-tags', 'origin', 'HEAD:refs/heads/' + info['candidate'])
            candidate_pushed = True
    ready = can_publish(issues, tests, bool(info['conflicts']))
    if ready:
        state = read_json(root / STATE)
        month = datetime.now(timezone.utc).strftime('%Y-%m')
        if info['update'] or state.get('last_checked_month') != month:
            state.update(release_tag=info['tag'], release_commit=info['sha'], last_checked_month=month)
            write_json(root / STATE, state)
            git(root, 'add', '--', STATE)
            git(root, 'commit', '-m', '记录正式版同步与汉化检查通过：' + info['tag'])
            git(root, 'push', '--no-follow-tags', 'origin', 'HEAD:refs/heads/zh-CN')
    lines = ['# 正式版同步与汉化检查', '', f"官方正式版：{info['tag']}", f"官方提交：{info['sha']}", '',
        '结果：检查通过，中文分支可用。' if ready else '结果：需要处理以下项目，当前可用中文分支保持不变。']
    if info['candidate']:
        status = '已同步至远端' if candidate_pushed else '本次未推送'
        lines += ['', f"候选分支：{info['candidate']}（{status}）"]
    if info['upstream_workflows']:
        lines += ['', '上游正式版涉及的工作流文件', *['- ' + p for p in info['upstream_workflows']]]
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
            if os.environ.get('GITHUB_OUTPUT'):
                with open(os.environ['GITHUB_OUTPUT'], 'a', encoding='utf-8') as output:
                    output.write(f"checkable={str(not info['conflicts']).lower()}\n")
            print(f"正式版 {info['tag']}，需要同步：{info['update']}，冲突：{bool(info['conflicts'])}")
        else:
            return 0 if finish(args.root, args.work, args.tests) else 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
