# STrans LaTeX 结题文档工程

## 1. 输出内容

本目录使用同一套 CTeX/XeLaTeX 样式，将 Markdown 事实源同步转换为可审阅的 TeX 与 PDF：

| 构建目标 | Markdown 事实源 | PDF 成品 |
|---|---|---|
| `requirements` | `17-需求分析报告V2.0.md` | `output/pdf/latex-final/STrans-需求分析报告V2.0.pdf` |
| `design` | `18-系统设计方案V2.0.md` | `output/pdf/latex-final/STrans-系统设计方案V2.0.pdf` |
| `manual` | `15-软件使用说明书.md` | `output/pdf/latex-final/STrans-软件使用说明书.pdf` |
| `test` | `06-系统测试报告.md` | `output/pdf/latex-final/STrans-系统测试报告.pdf` |
| `summary` | `16-项目总结报告.md` | `output/pdf/latex-final/STrans-项目总结报告.pdf` |
| `final` | 上述五份文档 | `output/pdf/latex-final/STrans-结题综合报告.pdf` |

## 2. 目录结构

- `preamble.tex`：A4 版式、中文字体、颜色、标题、表格、代码、页眉页脚与封面；
- `*-report.tex` / `software-manual.tex` / `project-summary.tex`：独立文档入口；
- `final-report.tex`：综合报告入口；
- `filters/localize-images.lua`：移除 Markdown 手工章节号，并将图片重写到本地资产目录；
- `build.ps1`：同步 Markdown、复制图片、生成 TeX、调用 XeLaTeX 编译并发布 PDF；
- `generated/`：Pandoc 生成的正文 TeX；
- `assets/`：从项目输出目录复制的 UML、页面和真实识别图片；
- `build/`：XeLaTeX 中间文件与编译日志。

`output/pdf/latex-final/` 是权威发布目录。构建脚本也会尽力更新 `output/pdf/` 顶层兼容副本；若旧 PDF 正被查看器占用，构建不会因此中断。

## 3. 构建命令

在仓库根目录执行：

```powershell
# 编译全部独立报告与综合报告
& 'docs\结题材料\latex\build.ps1' -Target all

# 只编译一份
& 'docs\结题材料\latex\build.ps1' -Target requirements
& 'docs\结题材料\latex\build.ps1' -Target design
& 'docs\结题材料\latex\build.ps1' -Target manual
& 'docs\结题材料\latex\build.ps1' -Target test
& 'docs\结题材料\latex\build.ps1' -Target summary
& 'docs\结题材料\latex\build.ps1' -Target final
```

## 4. 工具基线

- Pandoc 3.8；
- XeLaTeX / TeX Live 2026；
- latexmk 4.87；
- Poppler，用于逐页渲染检查；
- ImageMagick，用于生成页面总览。

## 5. 编辑与同步原则

1. 正文优先修改 Markdown 事实源，不直接修改 `generated/*.tex`；
2. 版式、封面或字体修改 `preamble.tex` 和对应入口 TeX；
3. UML 图修改 `docs/结题材料/diagrams/*.puml` 后重新渲染 PNG，再执行构建；
4. 构建会复制 Markdown 中实际引用的图片，确保 LaTeX 包可以离线归档；
5. 编译成功后仍需使用 Poppler 渲染抽查，确认无文字裁切、表格越界或低清晰度图片。
