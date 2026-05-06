"""
打包脚本：将 notepad_app.py 打包为 Windows 安装程序
================================================

用法（在项目根目录）：
    pip install pyinstaller
    python build.py             # 仅生成独立 exe（dist/NotepadApp/）
    python build.py --installer # 同时生成 .iss 脚本并尝试调用 Inno Setup 编译为安装包

可选参数：
    --installer   生成 Inno Setup 脚本并尝试编译
    --no-build    跳过 PyInstaller，仅重新生成 .iss

依赖：
    PyInstaller            （Python 打包；pip install pyinstaller）
    Inno Setup 6（可选）   （编译为 .exe 安装包；https://jrsoftware.org/isinfo.php）

输出：
    dist/NotepadApp/                 — 独立可执行目录
    installer/notepad_setup.iss      — Inno Setup 脚本
    installer/Output/NotepadAppSetup-x.y.z.exe — 最终安装包
"""
import os
import sys
import shutil
import subprocess
import argparse
from pathlib import Path

APP_NAME = "NoteLite"
APP_VERSION = "1.0.0"
APP_PUBLISHER = "NoteLite"
APP_ID = "{{B5C7E45F-3B4D-4E0E-9C0F-3F0F2A1A4B11}}"  # Inno Setup AppId

ROOT = Path(__file__).resolve().parent
DIST = ROOT / "dist"
BUILD = ROOT / "build"
INSTALLER_DIR = ROOT / "installer"
ISS_FILE = INSTALLER_DIR / "notepad_setup.iss"
ENTRY = ROOT / "build/notepad_app.py"


def run(cmd, **kw):
    print(">>", " ".join(str(c) for c in cmd))
    return subprocess.check_call(cmd, **kw)


def ensure_pyinstaller():
    try:
        import PyInstaller  # noqa: F401
    except ImportError:
        print("[!] 未检测到 PyInstaller，正在尝试安装...")
        run([sys.executable, "-m", "pip", "install", "pyinstaller"])


def build_exe():
    ensure_pyinstaller()
    if DIST.exists():
        shutil.rmtree(DIST)
    if BUILD.exists():
        shutil.rmtree(BUILD)

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", APP_NAME,
        "--noconsole",                      # 不显示终端
        "--noconfirm",
        "--clean",
        "--collect-all", "customtkinter",
        "--collect-all", "pystray",
        "--collect-all", "PIL",
        "--hidden-import", "PIL._tkinter_finder",
        # 一目录模式，启动更快、便于附加资源
        "--onedir",
        str(ENTRY),
    ]
    # 若存在自定义图标
    icon_ico = ROOT / "app_icon.ico"
    if icon_ico.exists():
        cmd[3:3] = ["--icon", str(icon_ico)]

    run(cmd)
    print(f"[√] PyInstaller 完成 -> {DIST / APP_NAME}")


def write_iss():
    INSTALLER_DIR.mkdir(parents=True, exist_ok=True)
    src_dir = (DIST / APP_NAME).resolve()
    if not src_dir.exists():
        raise FileNotFoundError(f"未找到打包结果 {src_dir}，请先运行 PyInstaller")

    iss = f'''\
; ====================================================================
; NotepadApp Inno Setup 安装脚本（由 build.py 自动生成）
; ====================================================================
#define MyAppName "{APP_NAME}"
#define MyAppVersion "{APP_VERSION}"
#define MyAppPublisher "{APP_PUBLISHER}"
#define MyAppExeName "{APP_NAME}.exe"

[Setup]
AppId={APP_ID}
AppName={{#MyAppName}}
AppVersion={{#MyAppVersion}}
AppPublisher={{#MyAppPublisher}}
DefaultDirName={{autopf}}\\{{#MyAppName}}
DefaultGroupName={{#MyAppName}}
DisableProgramGroupPage=yes
OutputDir=Output
OutputBaseFilename={APP_NAME}Setup-{APP_VERSION}
Compression=lzma
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=admin
UninstallDisplayIcon={{app}}\\{{#MyAppExeName}}

[Languages]
Name: "english";    MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{{cm:CreateDesktopIcon}}"; GroupDescription: "{{cm:AdditionalIcons}}"; Flags: unchecked
Name: "startup";     Description: "Start {{#MyAppName}} automatically at Windows logon"; GroupDescription: "Additional tasks:"; Flags: unchecked

[Files]
; 打包整个 PyInstaller 输出目录
Source: "{src_dir}\\*"; DestDir: "{{app}}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{{group}}\\{{#MyAppName}}";          Filename: "{{app}}\\{{#MyAppExeName}}"
Name: "{{group}}\\Uninstall {{#MyAppName}}"; Filename: "{{uninstallexe}}"
Name: "{{commondesktop}}\\{{#MyAppName}}";  Filename: "{{app}}\\{{#MyAppExeName}}"; Tasks: desktopicon

[Registry]
; 开机自启动（写入 HKCU 用户级 Run 项）
Root: HKCU; Subkey: "Software\\Microsoft\\Windows\\CurrentVersion\\Run"; \\
    ValueType: string; ValueName: "{{#MyAppName}}"; ValueData: """{{app}}\\{{#MyAppExeName}}"""; \\
    Flags: uninsdeletevalue; Tasks: startup

[Run]
Filename: "{{app}}\\{{#MyAppExeName}}"; Description: "{{cm:LaunchProgram,{{#MyAppName}}}}"; \\
    Flags: nowait postinstall skipifsilent

; ====================================================================
; Custom post-install logic:
;   - Detect DEEPSEEK_API_KEY; if missing, collect and persist it
; ====================================================================
[Code]
const
  DEEPSEEK_HELP_URL   = 'https://platform.deepseek.com/api_keys';

function GetDeepseekKey(): String;
var
  V: String;
begin
  Result := '';
  // 1) 当前进程环境（继承自启动时的 user+system 合并环境）
  V := GetEnv('DEEPSEEK_API_KEY');
  if V <> '' then
  begin
    Result := V;
    Exit;
  end;
  // 2) HKCU 用户级（注意：安装器以 admin 运行时这里是管理员账户的 hive，可能拿不到登录用户的值）
  if RegQueryStringValue(HKCU, 'Environment', 'DEEPSEEK_API_KEY', V) and (V <> '') then
  begin
    Result := V;
    Exit;
  end;
  // 3) HKLM 系统级
  if RegQueryStringValue(HKLM,
       'System\CurrentControlSet\Control\Session Manager\Environment',
       'DEEPSEEK_API_KEY', V) and (V <> '') then
  begin
    Result := V;
    Exit;
  end;
end;

procedure SetDeepseekKey(const Key: String);
var
  ResultCode: Integer;
begin
  // setx 会写入用户环境变量并广播 WM_SETTINGCHANGE
  Exec('cmd.exe', '/C setx DEEPSEEK_API_KEY "' + Key + '"',
        '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
end;

// 自定义输入框（Inno Setup 没有内置 InputQuery）
function PromptForKey(var Value: String): Boolean;
var
  Form: TSetupForm;
  PromptLabel: TNewStaticText;
  Edit: TNewEdit;
  OKBtn, CancelBtn: TNewButton;
begin
  Result := False;
  Form := TSetupForm.Create(nil);
  try
    Form.Caption := 'DEEPSEEK_API_KEY';
    Form.ClientWidth := ScaleX(440);
    Form.ClientHeight := ScaleY(150);
    Form.BorderStyle := bsDialog;
    Form.Position := poScreenCenter;

    PromptLabel := TNewStaticText.Create(Form);
    PromptLabel.Parent := Form;
    PromptLabel.Caption := 'Paste your DeepSeek API Key below (leave empty to skip):';
    PromptLabel.Left := ScaleX(12);
    PromptLabel.Top := ScaleY(12);
    PromptLabel.Width := ScaleX(420);

    Edit := TNewEdit.Create(Form);
    Edit.Parent := Form;
    Edit.Left := ScaleX(12);
    Edit.Top := ScaleY(50);
    Edit.Width := ScaleX(420);
    Edit.Text := Value;

    OKBtn := TNewButton.Create(Form);
    OKBtn.Parent := Form;
    OKBtn.Caption := 'OK';
    OKBtn.Left := ScaleX(260);
    OKBtn.Top := ScaleY(105);
    OKBtn.Width := ScaleX(80);
    OKBtn.Height := ScaleY(28);
    OKBtn.ModalResult := mrOk;
    OKBtn.Default := True;

    CancelBtn := TNewButton.Create(Form);
    CancelBtn.Parent := Form;
    CancelBtn.Caption := 'Skip';
    CancelBtn.Left := ScaleX(350);
    CancelBtn.Top := ScaleY(105);
    CancelBtn.Width := ScaleX(80);
    CancelBtn.Height := ScaleY(28);
    CancelBtn.ModalResult := mrCancel;
    CancelBtn.Cancel := True;

    if Form.ShowModal = mrOk then
    begin
      Value := Edit.Text;
      Result := True;
    end;
  finally
    Form.Free;
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  Key: String;
  Resp: Integer;
begin
  if CurStep = ssPostInstall then
  begin
    // ---- DeepSeek API Key detection ----
    Key := GetDeepseekKey();
    if Key = '' then
    begin
      Resp := MsgBox(
        'Environment variable DEEPSEEK_API_KEY was not found.' + #13#10 +
        'It is used by the "Weekly Summary" feature to call DeepSeek for AI analysis (optional).' + #13#10 + #13#10 +
        'Would you like to configure your DeepSeek API Key now?' + #13#10 +
        '(Choosing No lets you set it later via system environment variables.)',
        mbConfirmation, MB_YESNO);
      if Resp = IDYES then
      begin
        if MsgBox('The DeepSeek API key page will be opened in your browser.' + #13#10 +
                   'Please create or copy your key, then return to this wizard.',
                   mbInformation, MB_OKCANCEL) = IDOK then
          ShellExec('open', DEEPSEEK_HELP_URL, '', '', SW_SHOW, ewNoWait, Resp);

        Key := '';
        if PromptForKey(Key) then
        begin
          Key := Trim(Key);
          if Key <> '' then
          begin
            SetDeepseekKey(Key);
            MsgBox('DEEPSEEK_API_KEY has been saved to your user environment variables.' + #13#10 +
                    'It will take effect the next time you launch {{#MyAppName}}.',
                    mbInformation, MB_OK);
          end;
        end;
      end;
    end;
  end;
end;
'''
    ISS_FILE.write_text(iss, encoding="utf-8")
    print(f"[√] 已生成 Inno Setup 脚本 -> {ISS_FILE}")


INNO_SETUP_DOWNLOAD_URLS = [
    "https://files.jrsoftware.org/is/6/innosetup-6.5.5.exe",
    "https://files.jrsoftware.org/is/6/innosetup-6.4.3.exe",
    "https://files.jrsoftware.org/is/6/innosetup-6.3.3.exe",
]

def find_iscc():
    """查找 Inno Setup 编译器 ISCC.exe（包括便携版）"""
    candidates = [
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
        r"C:\Program Files (x86)\Inno Setup 5\ISCC.exe",
        str(ROOT / "tools" / "InnoSetup" / "ISCC.exe"),
    ]
    for p in candidates:
        if os.path.exists(p):
            return p
    iscc = shutil.which("ISCC.exe") or shutil.which("iscc")
    return iscc

def download_inno_setup():
    """自动下载 Inno Setup 安装程序到本地 tools/ 目录"""
    import urllib.request
    tools_dir = ROOT / "tools"
    tools_dir.mkdir(parents=True, exist_ok=True)
    target = tools_dir / "innosetup_installer.exe"
    if target.exists() and target.stat().st_size > 1024 * 1024:
        print(f"[i] 已存在 Inno Setup 安装程序: {target}")
        return target
    last_err = None
    for url in INNO_SETUP_DOWNLOAD_URLS:
        try:
            print(f"[i] 正在下载 Inno Setup: {url}")
            print("    (约 6 MB，请耐心等待...)")
            with urllib.request.urlopen(url, timeout=60) as resp, open(target, "wb") as f:
                shutil.copyfileobj(resp, f)
            if target.stat().st_size > 1024 * 1024:
                print(f"[OK] 下载完成 -> {target}")
                return target
        except Exception as e:
            last_err = e
            print(f"[!] 下载失败: {e}")
            continue
    print(f"[!] 所有下载源均失败。最后一次错误: {last_err}")
    return None

def install_inno_setup_silent(installer_exe):
    """静默安装 Inno Setup（需要管理员权限；失败时回退到普通安装向导）"""
    print("[i] 尝试静默安装 Inno Setup（可能弹出 UAC 提示，请允许）...")
    try:
        ret = subprocess.call([str(installer_exe),
                                "/VERYSILENT", "/SUPPRESSMSGBOXES",
                                "/NORESTART", "/SP-"])
        if ret == 0:
            print("[OK] 静默安装完成")
            return True
        print(f"[!] 静默安装返回码 {ret}")
    except Exception as e:
        print(f"[!] 静默安装失败: {e}")
    return False


def compile_installer():
    iscc = find_iscc()
    if not iscc:
        print("[!] 未找到 Inno Setup 编译器 (ISCC.exe)，将自动下载并安装。")
        installer_exe = download_inno_setup()
        if not installer_exe:
            print("    请手动前往 https://jrsoftware.org/isdl.php 下载安装。")
            print(f"    然后再次运行: python build.py --installer --no-build")
            return
        # 尝试静默安装（需要管理员权限）
        if install_inno_setup_silent(installer_exe):
            iscc = find_iscc()
        if not iscc:
            # 静默失败 → 启动普通安装向导
            print("[i] 启动 Inno Setup 安装向导，请按提示完成安装...")
            print("    （安装完成后此脚本将自动继续编译安装包）")
            try:
                subprocess.call([str(installer_exe)])
            except Exception as e:
                print(f"[!] 启动安装程序失败: {e}")
            iscc = find_iscc()
        if not iscc:
            print("[!] 安装后仍未找到 ISCC.exe。")
            print(f"    请确认已成功安装 Inno Setup 6，然后重新运行：")
            print(f"      python build.py --installer --no-build")
            return
    print(f"[i] 使用 ISCC: {iscc}")
    try:
        run([iscc, str(ISS_FILE)], cwd=str(INSTALLER_DIR))
    except subprocess.CalledProcessError as e:
        print(f"[!] ISCC 编译失败 (返回码 {e.returncode})")
        return
    out_dir = INSTALLER_DIR / "Output"
    if out_dir.exists():
        files = list(out_dir.glob("*.exe"))
        if files:
            print(f"[OK] 安装包已生成:")
            for f in files:
                size_mb = f.stat().st_size / 1024 / 1024
                print(f"      {f}  ({size_mb:.1f} MB)")
        else:
            print(f"[!] {out_dir} 中未找到生成的 .exe，请检查 ISCC 输出")
    else:
        print(f"[!] 输出目录不存在: {out_dir}")


def cleanup_artifacts():
    """安装包构建成功后，仅保留 NoteLiteSetup-x.y.z.exe，清理其他中间产物。"""
    final_exe_name = f"{APP_NAME}Setup-{APP_VERSION}.exe"
    out_dir = INSTALLER_DIR / "Output"
    src_exe = out_dir / final_exe_name
    if not src_exe.exists():
        print(f"[!] 未找到最终安装包 {src_exe}，跳过清理。")
        return

    # 1) 把最终安装包搬到项目根目录
    dst_exe = ROOT / final_exe_name
    try:
        if dst_exe.exists():
            dst_exe.unlink()
        shutil.move(str(src_exe), str(dst_exe))
        print(f"[OK] 安装包已移动到: {dst_exe}")
    except Exception as e:
        print(f"[!] 移动安装包失败: {e}")
        return

    # 2) 删除中间目录与文件
    targets = [
        DIST,
        BUILD,
        INSTALLER_DIR,
        ROOT / "tools",
        ROOT / f"{APP_NAME}.spec",
    ]
    for p in targets:
        try:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            elif p.exists():
                p.unlink()
        except Exception as e:
            print(f"[!] 清理 {p} 失败: {e}")

    print(f"[OK] 已清理中间产物，仅保留: {dst_exe.name}")

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--installer", action="store_true",
                    help="同时生成 Inno Setup 脚本并尝试编译")
    ap.add_argument("--no-build", action="store_true",
                    help="跳过 PyInstaller，仅重新生成 .iss / 编译安装包")
    ap.add_argument("--keep-intermediate", action="store_true",
                    help="保留 dist/build/installer 等中间产物（默认仅保留最终 .exe）")
    args = ap.parse_args()

    if not args.no_build:
        build_exe()

    if args.installer:
        write_iss()
        compile_installer()
        if not args.keep_intermediate:
            cleanup_artifacts()

    print("\n完成。")
    if args.installer:
        final = ROOT / f"{APP_NAME}Setup-{APP_VERSION}.exe"
        if final.exists():
            print(f"  - 最终安装包: {final}")
        else:
            print(f"  - 独立程序目录: {DIST / APP_NAME}")
            print(f"  - Inno Setup 脚本: {ISS_FILE}")
            print(f"  - 安装包输出目录: {INSTALLER_DIR / 'Output'}")
    else:
        print(f"  - 独立程序目录: {DIST / APP_NAME}")


if __name__ == "__main__":
    main()
