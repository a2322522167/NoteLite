# 智能记事本 — 打包与分发指南

## 一、源码运行（开发者）
```cmd
pip install customtkinter pystray pillow plyer requests
python notepad_app.py
```

## 二、打包为 Windows 安装包

### 1. 安装打包依赖
```cmd
pip install pyinstaller
```

### 2. 仅生成独立可执行目录（无安装包）
```cmd
python build.py
```
输出：`dist\NotepadApp\NotepadApp.exe`（双击即可运行，**无需 Python 环境**）

### 3. 生成完整 Windows 安装包

需要先安装 Inno Setup 6（免费）：
- 官网：<https://jrsoftware.org/isdl.php>
- 默认装到 `C:\Program Files (x86)\Inno Setup 6\`

然后执行：
```cmd
python build.py --installer
```

输出：
- `dist\NotepadApp\` — PyInstaller 独立目录
- `installer\notepad_setup.iss` — 自动生成的 Inno Setup 脚本
- `installer\Output\NotepadAppSetup-1.0.0.exe` — **最终安装包**（用户双击即可安装）

### 4. 仅重新生成安装包（不重新打包 exe）
```cmd
python build.py --installer --no-build
```

---

## 三、安装包的智能引导

**用户运行 `NotepadAppSetup-1.0.0.exe` 时，安装向导会**：

### 1. 安装到 `Program Files\NotepadApp`
- 创建开始菜单与桌面快捷方式（可勾选）
- 可选「开机自动启动」（写入 HKCU `Run` 项）

### 2. **检测 Python 环境**
- 通过 `where python` / `where py` 检查
- 未检测到 → 弹窗说明："本程序为绿色发行版，正常使用无需 Python；如需扩展开发再安装。是否打开下载页？"
- 选「是」自动跳转 <https://www.python.org/downloads/windows/>

### 3. **检测 DEEPSEEK_API_KEY 环境变量**
- 读取 `HKCU\Environment\DEEPSEEK_API_KEY`
- 未配置 → 询问是否现在配置：
  - 选「是」→ 先弹窗提示打开 <https://platform.deepseek.com/api_keys>
  - 用户复制 Key 后回到向导，输入框粘贴
  - 调用 `setx DEEPSEEK_API_KEY "..."` 写入用户级环境变量（重启永久生效）
- 选「否」→ 跳过；用户也可在系统环境变量中手动添加

### 4. 完成 → 可立即启动应用

---

## 四、应用首次启动的二次引导

即使用户在安装时跳过了 DeepSeek Key 设置，**首次启动应用时**还会再弹窗一次：
- 显示美化对话框，含「打开 DeepSeek 官网 / 保存并启用 / 不再提示 / 稍后」四个按钮
- 「保存并启用」会调用 `setx` 写入环境变量并立即注入当前进程，无需重启
- 「不再提示」会在程序目录创建 `.deepseek_skip` 标记文件，下次不再询问

---

## 五、文件清单

| 文件 | 说明 |
|------|------|
| `notepad_app.py` | 主程序（含首次启动 DeepSeek 向导） |
| `build.py` | 打包脚本（PyInstaller + Inno Setup） |
| `events_data.json` | 事件数据（运行时生成） |
| `trash_data.json` | 回收站数据（运行时生成） |
| `attachments/` | 附件目录（运行时生成） |
| `installer/notepad_setup.iss` | Inno Setup 脚本（build.py 自动生成） |
| `installer/Output/*.exe` | 最终安装包（编译后生成） |

---

## 六、卸载

通过 Windows「设置 → 应用」或控制面板，找到 **NotepadApp** 卸载，即可清理所有文件与开机启动项。
（环境变量 `DEEPSEEK_API_KEY` 不会被删除，避免影响其他工具；如需清理请手动 `setx DEEPSEEK_API_KEY ""`）