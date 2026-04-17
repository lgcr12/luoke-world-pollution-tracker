# 洛克污染统计器 Pro

一个面向《洛克王国：世界》的桌面辅助工具，用于实时识别污染目标、按精灵分池统计、导出记录，并提供悬浮可视化界面。

当前版本重点解决的是：
- 污染目标实时识别
- 模板截图与模板库管理
- 精灵污染计数池统计
- 悬浮窗 UI 展示与操作

## 功能说明

### 1. 实时污染识别
- 通过屏幕抓帧识别游戏右上角的污染头像区域
- 基于模板匹配判断当前是否出现污染目标
- 支持最小触发间隔与重置冷却，避免重复计数

### 2. 精灵模板库
- 支持从 UI 中直接框选污染头像并保存为模板
- 模板按精灵名称保存到 `assets/species_templates`
- 启动实时识别时自动加载模板库

### 3. 精灵计数池
- 按精灵名称分别统计：
  - 出现次数
  - 污染累计次数
- 在界面右侧计数库中实时展示

### 4. 悬浮窗界面
- 无边框、置顶、可拖动
- 支持开始、停止、模板截图、打开模板目录、重置、报表导出
- 内置日志输出区和计数库滚动列表

### 5. 报表与状态持久化
- 识别记录写入 `report.csv`
- 统计状态写入 `state.json`
- 关闭程序后仍可保留累计数据

## 技术框架

项目采用“识别引擎 + 桌面界面”双层结构：

### 识别层
- `tracker.py`
- 负责模板匹配、屏幕抓取、OCR、计数逻辑、状态保存、报表导出

### 界面层
- `gui.py`
- 负责悬浮窗 UI、操作按钮、模板截图、日志展示、计数库展示

### 资源层
- `assets/`
- 保存模板说明、污染模板、精灵模板等资源文件

### 数据层
- `config.json`：程序配置
- `state.json`：运行状态与统计结果
- `report.csv`：导出报表
- `species_names.json`：精灵名称词库

## 技术栈

- Python 3.10+
- Tkinter
- OpenCV
- NumPy
- MSS
- PyGetWindow
- RapidOCR ONNX Runtime

对应依赖见 [requirements.txt](E:\code\luoke_pollution_tracker\requirements.txt)。

## 项目结构

```text
luoke_pollution_tracker/
├─ assets/
│  ├─ README.txt
│  └─ species_templates/
├─ config.json
├─ gui.py
├─ report.csv
├─ requirements.txt
├─ save_template_from_clipboard.py
├─ species_names.json
├─ state.json
├─ tracker.py
└─ README.md
```

## 下载说明

### 方式 1：直接下载源码压缩包
1. 打开 GitHub 仓库首页
2. 点击 `Code`
3. 点击 `Download ZIP`
4. 解压到本地目录后运行

### 方式 2：使用 Git 克隆
```powershell
git clone <你的仓库地址>
cd luoke_pollution_tracker
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

### 3. 启动图形界面
```powershell
python gui.py
```

### 4. 首次使用流程
1. 打开程序
2. 点击 `模板截图`
3. 框选游戏中的污染头像区域
4. 输入精灵名称
5. 保存到模板库
6. 点击 `开始` 进入实时识别

### 5. 常用功能

#### 开始实时识别
- 点击 `开始`
- 程序会持续抓取游戏区域并进行模板匹配

#### 停止识别
- 点击 `停止`

#### 模板截图
- 点击 `模板截图`
- 手动框选污染头像区域
- 输入精灵名称后自动保存到模板目录

#### 打开模板目录
- 点击 `目录`
- 直接打开 `assets/species_templates`

#### 重置统计
- 点击 `重置`
- 清空本地统计状态

#### 打开报表
- 点击 `报表`
- 打开 `report.csv`

## 命令行模式

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

### 查看当前状态
```powershell
python tracker.py status
```

### 重置统计
```powershell
python tracker.py reset
```

## 配置说明

主要配置文件是 [config.json](E:\code\luoke_pollution_tracker\config.json)。

### `icon_mode`
- `template_match_threshold`：模板匹配阈值
- `purple_ratio_threshold`：紫色占比阈值
- `icon_pollution_value`：每次命中增加的污染值

### `screen_mode`
- `capture_interval_sec`：抓帧间隔
- `window_title_contains`：游戏窗口标题关键字
- `min_trigger_gap_sec`：两次触发最小时间间隔
- `rearm_absent_sec`：目标消失多久后允许重新计数
- `search_region`：屏幕搜索区域

### `species_template_mode`
- `template_dir`：精灵模板目录

## 运行环境

推荐环境：
- Windows 10 / Windows 11
- Python 3.10 及以上
- 游戏窗口使用窗口化或无边框窗口化

## 注意事项

- 模板截图尽量只截污染头像本体，不要带太多背景
- 如果误识别较多，应提高模板匹配阈值
- 如果漏识别较多，应降低模板匹配阈值
- `state.json` 和 `report.csv` 属于运行数据，通常不建议作为源码的一部分长期提交

## 后续可扩展方向

- 更精细的 ROI 调试预览
- 自动模板管理
- 更完整的精灵词库对照
- PySide6 / Qt 版本毛玻璃界面
- 多显示器与多分辨率适配
