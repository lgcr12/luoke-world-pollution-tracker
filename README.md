# 洛克污染统计器 Pro

一个面向《洛克王国：世界》的桌面辅助工具，用于实时识别污染目标、按精灵分池统计、保存模板截图，并提供可视化悬浮界面。

当前版本重点：
- Qt Fluent Glass 风格主界面
- 实时屏幕识别与模板匹配
- 精灵计数库与污染累计统计
- 模板截图、模板目录、报表导出
- Qt / Tk 双界面架构，默认优先启动 Qt 版

## 功能说明

### 1. 实时污染识别
- 按配置持续抓取游戏区域画面
- 在搜索区域内进行模板匹配
- 命中后按精灵名称累计计数和污染次数
- 支持触发间隔与重置冷却，避免重复计数

### 2. 模板截图与模板库
- 可直接在界面中进入模板截图模式
- 框选污染头像后保存为精灵模板
- 模板文件按精灵名保存到 `assets/species_templates`
- 实时识别会自动加载模板库

### 3. 计数库与统计
- 展示总污染、精灵种类、最新识别目标
- 按精灵维度统计：
  - 计数
  - 污染次数
- 统计状态写入 `state.json`

### 4. 报表导出
- 识别记录写入 `report.csv`
- 可直接从界面打开报表文件

### 5. 图形界面
- Qt 版：无边框、玻璃风、置顶、可拖拽
- Tk 版：作为兼容回退版本保留
- 支持最小化、关闭、置顶开关、日志输出、滚动计数库

## 技术框架

项目采用“识别引擎 + GUI 启动器 + 多界面实现”的结构：

### 识别层
- `tracker.py`
- 负责配置加载、屏幕抓取、模板匹配、状态持久化、报表导出

### 启动层
- `gui.py`
- 作为统一入口，优先尝试启动 Qt 版，失败后回退到 Tk 版

### Qt 界面层
- `gui_qt.py`
- 当前主用界面
- 基于 `PySide6` 实现 Fluent Glass 风格界面与截图交互

### Tk 回退界面层
- `gui_tk.py`
- 保留旧版界面和兼容能力，作为 Qt 不可用时的后备方案

### 资源与数据层
- `assets/`：模板说明与模板资源
- `config.json`：程序配置
- `state.json`：统计状态
- `report.csv`：识别报表
- `species_names.json`：精灵名称词库

## 技术栈

- Python 3.10+
- PySide6
- Tkinter
- OpenCV
- NumPy
- MSS
- PyGetWindow
- RapidOCR ONNX Runtime

依赖见 [requirements.txt](./requirements.txt)。

## 下载说明

### 方式 1：直接下载 ZIP
1. 打开 GitHub 仓库首页
2. 点击 `Code`
3. 点击 `Download ZIP`
4. 解压后进入项目目录

### 方式 2：Git 克隆
```powershell
git clone https://github.com/lgcr12/luoke-world-pollution-tracker.git
cd luoke-world-pollution-tracker
```

## 使用说明

### 1. 安装依赖
```powershell
cd E:\code\luoke_pollution_tracker
python -m pip install -r requirements.txt
```

### 2. 初始化文件
```powershell
python tracker.py init
```

初始化后会生成或修复以下文件：
- `config.json`
- `state.json`
- `report.csv`
- `assets/README.txt`
- `assets/species_templates/README.txt`

### 3. 启动 GUI
```powershell
python gui.py
```

说明：
- 如果已在 `luoke_qt` 环境中，优先直接启动 Qt 版
- 如果不在 `luoke_qt` 环境中，会尝试通过 `conda run -n luoke_qt` 启动 Qt 版
- Qt 启动失败时自动回退到 Tk 版

### 4. 首次使用流程
1. 打开程序
2. 点击 `模板截图`
3. 框选游戏中的污染头像区域
4. 输入精灵名
5. 保存模板
6. 点击 `开始`

### 5. 常用操作
- `开始`：启动实时识别
- `停止`：停止实时识别
- `模板截图`：进入截图模式保存模板
- `目录`：打开模板目录
- `重置`：清空本地统计
- `报表`：打开 `report.csv`
- `置顶`：切换窗口置顶状态

## 命令行用法

### 初始化
```powershell
python tracker.py init
```

### 单次扫描
```powershell
python tracker.py once
```

### 监听截图目录
```powershell
python tracker.py watch
```

### 实时屏幕识别
```powershell
python tracker.py screen-watch
```

### 查看状态
```powershell
python tracker.py status
```

### 重置统计
```powershell
python tracker.py reset
```

## 运行环境

推荐环境：
- Windows 10 / Windows 11
- Python 3.10 及以上
- 建议单独创建 `luoke_qt` 环境运行 Qt 版
- 游戏窗口建议使用窗口化或无边框窗口化

## 项目结构

```text
luoke_pollution_tracker/
├─ assets/
│  ├─ README.txt
│  └─ species_templates/
├─ config.json
├─ gui.py
├─ gui_qt.py
├─ gui_tk.py
├─ report.csv
├─ requirements.txt
├─ save_template_from_clipboard.py
├─ species_names.json
├─ state.json
├─ tracker.py
└─ README.md
```

## 注意事项

- 模板截图尽量只截污染头像本体，不要带太多背景
- 如果误识别偏多，可提高模板匹配阈值
- 如果漏识别偏多，可适当降低模板匹配阈值
- `state.json` 和 `report.csv` 属于运行数据，通常不建议长期作为源码内容频繁提交

## 后续可扩展方向

- 多模板融合识别
- ROI 调试可视化
- 模板管理器
- 会话统计与历史统计分离
- 更完整的 Qt Fluent 动效与系统托盘支持
