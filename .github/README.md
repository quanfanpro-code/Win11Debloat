# Win11Debloat 简体中文版

基于 [Raphire/Win11Debloat](https://github.com/Raphire/Win11Debloat) 的社区简体中文版，由 quanfanpro-code 维护。沿用原项目 MIT 许可证，保留原作者版权声明。

[下载简体中文版 ZIP](https://github.com/quanfanpro-code/Win11Debloat/archive/refs/heads/zh-CN.zip) · [查看自动同步记录](https://github.com/quanfanpro-code/Win11Debloat/actions/workflows/sync-stable.yml) · [查看汉化待办](https://github.com/quanfanpro-code/Win11Debloat/issues)

## 使用

下载 ZIP，完整解压后，双击文件夹中的 `启动简体中文版.cmd`。需要管理员权限时按中文提示确认。请先阅读各选项说明，再选择要卸载的应用或调整的设置。

当前版本包含完整中文界面、141 个应用的中文名称和说明、启动提示、操作日志及命令行提示，共 1,439 条语言资源。英文模式和缺失翻译的英文回退仍可使用。

## 版本来源

初始中文版来自已经实际验收的代码，提交起点为 `202a994`，包含官方在 2026.08.24 正式版之后新增的多语言框架。它不等同于纯粹的官方 2026.08.24 正式版。

今后只跟随官方正式发布版，排除草稿、RC、Beta 和其他预发布版。原官方贡献 PR #770 独立保留，本分支的维护功能不会混入该 PR。

## 自动更新如何工作

1. GitHub Actions 每天北京时间约 08:23 检查一次，也可在“正式版同步与汉化检查”页面点击 Run workflow 手动检查；GitHub 排队时可能延迟。
2. 官方正式版原始代码同步到 `upstream/stable`，与中文版合并的结果放入 `sync/stable-…` 候选分支。
3. 检查新增、删除和变化的英文原文、缺失或空白译文、占位符和重复 JSON 键。运行脚本、界面或功能目录发生变化时，会保守提示人工复核，避免漏掉尚未提取到语言文件的新文字。
4. 汉化检查和 Windows PowerShell 测试全部通过，才自动更新可用的 `zh-CN` 分支。发生冲突或需要补译时，生成中文 Issue 和检查报告，保持当前可用版本。
5. 每月写入一次检查日期以维持仓库活动。该任务在 GitHub 上运行，不需要本机开机，也不需要付费 AI 接口。

检查器负责发现变更，不能自动判断译文的语义是否准确；发现问题后仍需要维护者补译和复核。仓库更新不会自动修改你电脑上已经解压的文件，需要重新下载。

## 维护汉化

收到待办后，在对应候选分支完成翻译与源码文字复核，先提交已复核的修改，再运行：

```powershell
python Maintenance/维护中文版.py baseline
python Maintenance/维护中文版.py check
python Maintenance/维护测试.py
python Maintenance/同步集成测试.py
.\Scripts\Run-Tests.ps1
```

只有实际复核后才能更新基线；这不是用来跳过告警的按钮。将更新后的基线提交并推送到候选分支，再手动运行同步任务。任务会复用候选分支，检查通过后更新中文版。

维护脚本使用 Python 3.14 标准库。普通用户运行 Win11Debloat 不需要安装 Python。测试只在模拟环境或测试隔离目标执行，不使用真实卸载来验证语言包。

## 上游说明与许可证

软件功能、系统要求和选项说明请参阅 [上游项目文档](https://github.com/Raphire/Win11Debloat/wiki)。上游在线安装命令下载的是官方版本；需要本中文版请使用本页 ZIP 下载入口。

[MIT 许可证](../LICENSE) · 原作者：Raphire · 中文翻译与中文分支维护：quanfanpro-code。