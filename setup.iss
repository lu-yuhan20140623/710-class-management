; ============================================================
; 课程表 · Inno Setup 安装脚本
; 生成 Setup.exe 安装程序
; ============================================================
#define MyAppName "课程表"
#define MyAppVersion "2.2.7"
#define MyAppPublisher "七年级10班"
#define MyAppExeName "ClassSchedule.exe"
#define MyBackendName "ClassSchedule_Backend.exe"
#define MyOverlayName "ClassSchedule_Overlay.exe"
#define MyBallName "ClassSchedule_Ball.exe"
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
OutputBaseFilename=ClassSchedule_Setup_{#MyAppVersion}
SetupIconFile=assets\app.ico
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
PrivilegesRequired=lowest
; 自动更新时以 /SILENT 运行，需要安装程序自行关闭正在运行的程序
CloseApplications=yes
RestartApplications=no
UninstallDisplayIcon={app}\{#MyAppExeName}

; 许可 / 自述（可选，没有就注释掉）
; LicenseFile=LICENSE.txt
; InfoBeforeInstall=README.txt

; [Languages]
; 使用默认 English（Inno Setup 内置）
; 如果以后下载了中文语言包，改为：
;   Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Files]
; 四个主 EXE（onedir 启动器，本身很小）
Source: "dist\{#MyAppExeName}";         DestDir: "{app}"; Flags: ignoreversion
Source: "dist\{#MyBackendName}";        DestDir: "{app}"; Flags: ignoreversion
Source: "dist\{#MyOverlayName}";        DestDir: "{app}"; Flags: ignoreversion
Source: "dist\{#MyBallName}";           DestDir: "{app}"; Flags: ignoreversion
; 四个 EXE 共用的 Python 运行时，只打包一份
Source: "dist\_internal\*";             DestDir: "{app}\_internal"; Flags: ignoreversion recursesubdirs createallsubdirs
; 业务代码与版本清单（补丁按 app/ 下的文件替换）
Source: "dist\app\*.py";                DestDir: "{app}\app"; Flags: ignoreversion
; 插件目录：运行期自动扫描，可与第三方插件共存
Source: "dist\plugins\*";               DestDir: "{app}\plugins"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "dist\version.json";            DestDir: "{app}"; Flags: ignoreversion
; 默认名单：仅在目标文件不存在时写入，升级/重装不会覆盖真实积分
Source: "dist\class_data.txt";          DestDir: "{app}"; Flags: onlyifdoesntexist skipifsourcedoesntexist
Source: "dist\student_data.txt";        DestDir: "{app}"; Flags: onlyifdoesntexist skipifsourcedoesntexist
Source: "dist\group_data.txt";          DestDir: "{app}"; Flags: onlyifdoesntexist skipifsourcedoesntexist

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
Filename: "{app}\{#MyBackendName}"; Description: "启动后台服务"; Flags: nowait postinstall skipifsilent unchecked; OnlyBelowVersion: 0; Check: WizardIsTaskSelected('startbackend')
; 启动主界面
Filename: "{app}\{#MyAppExeName}"; Description: "打开课程表主界面"; Flags: nowait postinstall skipifsilent unchecked

[Registry]
; 注册开机自启（HKCU，不需要管理员权限）
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#MyAppRegName}"; ValueData: """{app}\{#MyBackendName}"""; Flags: uninsdeletevalue

[UninstallDelete]
; 卸载时删除 EXE 目录（但保留用户数据）
Type: filesandordirs; Name: "{app}"

[Code]
// 安装/升级前先停掉正在运行的四个进程，否则 exe 被占用无法覆盖
function InitializeSetup: Boolean;
var
  ResultCode: Integer;
begin
  Exec('taskkill.exe', '/F /IM ClassSchedule.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec('taskkill.exe', '/F /IM ClassSchedule_Backend.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec('taskkill.exe', '/F /IM ClassSchedule_Overlay.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec('taskkill.exe', '/F /IM ClassSchedule_Ball.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Sleep(600);
  Result := True;
end;

// 卸载前先杀掉后台进程，否则 exe 被锁删不掉
function InitializeUninstall: Boolean;
var
  ResultCode: Integer;
begin
  Result := True;
  // 停掉可能在跑的四个 EXE
  Exec('taskkill.exe', '/F /IM ClassSchedule.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec('taskkill.exe', '/F /IM ClassSchedule_Backend.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec('taskkill.exe', '/F /IM ClassSchedule_Overlay.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
  Exec('taskkill.exe', '/F /IM ClassSchedule_Ball.exe', '', SW_HIDE, ewWaitUntilTerminated, ResultCode);
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
