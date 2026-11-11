; ============================================================
; 课程表 · Inno Setup 安装脚本
; 生成 Setup.exe 安装程序
; ============================================================
#define MyAppName "课程表"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "七年级10班"
#define MyAppExeName "ClassSchedule.exe"
#define MyBackendName "ClassSchedule_Backend.exe"
#define MyOverlayName "ClassSchedule_Overlay.exe"
#define MyAppRegName "ClassSchedule"

[Setup]
; 基本信息
AppId={{B8E3A4F2-9C1D-4E55-A6B7-7F2D1F8A3C4E}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL=https://example.com/
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
AllowNoIcons=yes
OutputDir=installer
OutputBaseFilename=ClassSchedule_Setup
SetupIconFile=
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
UninstallDisplayIcon={app}\{#MyAppExeName}

; 许可 / 自述（可选，没有就注释掉）
; LicenseFile=LICENSE.txt
; InfoBeforeInstall=README.txt

; [Languages]
; 使用默认 English（Inno Setup 内置）
; 如果以后下载了中文语言包，改为：
;   Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Files]
; 三个主 EXE（dist 目录里打出来的）
Source: "dist\{#MyAppExeName}";         DestDir: "{app}"; Flags: ignoreversion
Source: "dist\{#MyBackendName}";        DestDir: "{app}"; Flags: ignoreversion
Source: "dist\{#MyOverlayName}";        DestDir: "{app}"; Flags: ignoreversion

[Icons]
; 开始菜单 → 主程序
Name: "{group}\{#MyAppName}（主界面）"; Filename: "{app}\{#MyAppExeName}"
; 开始菜单 → 卸载
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"
; 桌面快捷方式（可选，询问用户）
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Tasks]
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "附加图标:"; Flags: unchecked
Name: "startbackend"; Description: "启动后台服务（建议勾选）"; GroupDescription: "安装后立即:"; Flags: checkedonce

[Run]
; 安装完成后可选：启动后台服务（用户勾选 startbackend）
Filename: "{app}\{#MyBackendName}"; Description: "启动后台服务"; Flags: nowait postinstall skipifsilent unchecked; OnlyBelowVersion: 0; Check: IsTaskSelected('startbackend')
; 启动主界面
Filename: "{app}\{#MyAppExeName}"; Description: "打开课程表主界面"; Flags: nowait postinstall skipifsilent unchecked

[Registry]
; 注册开机自启（HKCU，不需要管理员权限）
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppRegName}"; ValueData: """{app}\{#MyBackendName}"""; Flags: uninsdeletevalue

[UninstallDelete]
; 卸载时删除 EXE 目录（但保留用户数据）
Type: filesandordirs; Name: "{app}"

[Code]
// 卸载前先杀掉后台进程，否则 exe 被锁删不掉
function InitializeUninstall: Boolean;
var
  ResultCode: Integer;
begin
  Result := True;
  // 停掉可能在跑的三个 EXE
  Exec('taskkill.exe', '/F /IM ClassSchedule.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec('taskkill.exe', '/F /IM ClassSchedule_Backend.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec('taskkill.exe', '/F /IM ClassSchedule_Overlay.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(500);
end;

// 安装后提示用户数据位置
procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then begin
    // 用户数据目录不存在则创建，让 EXE 第一次运行时能写进去
    ForceDirectories(ExpandConstant('{userappdata}\{#MyAppName}'));
  end;
end;
