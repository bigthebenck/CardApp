; Inno Setup script: packs dist\CardApp (from CardApp.spec) into CardApp-Setup-<version>.exe.
; Build from the repo root with:  iscc /DAppVersion=1.0.0 installer\CardApp.iss
;
; AppId must never change: it is how a newer installer finds and upgrades this one.
; It installs per user, so neither installing nor the in-app update needs admin rights.

#ifndef AppVersion
  #error Pass the version: iscc /DAppVersion=1.2.3 installer\CardApp.iss
#endif

[Setup]
AppId={{03D81435-446C-4C45-A013-F88E720A662C}
AppName=Shuffle Solver
AppVersion={#AppVersion}
AppPublisher=bigthebenck
AppPublisherURL=https://github.com/bigthebenck/CardApp
AppUpdatesURL=https://github.com/bigthebenck/CardApp/releases
DefaultDirName={localappdata}\Programs\CardApp
DefaultGroupName=Shuffle Solver
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=CardApp-Setup-{#AppVersion}
UninstallDisplayIcon={app}\CardApp.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; Let an update close the running app so its files can be replaced.
CloseApplications=force
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\CardApp\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; Drop files an older version shipped but this one doesn't.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\Shuffle Solver"; Filename: "{app}\CardApp.exe"
Name: "{group}\Uninstall Shuffle Solver"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Shuffle Solver"; Filename: "{app}\CardApp.exe"; Tasks: desktopicon

[Run]
; Interactive install: an "open it now" checkbox. Silent install (the in-app update): reopen it.
Filename: "{app}\CardApp.exe"; Description: "{cm:LaunchProgram,Shuffle Solver}"; Flags: nowait postinstall skipifsilent
Filename: "{app}\CardApp.exe"; Flags: nowait skipifnotsilent
