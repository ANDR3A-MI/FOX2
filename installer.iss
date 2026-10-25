; installer.iss — installer Windows per F.O.X.
;
; Compilato dal workflow con:
;   ISCC.exe /DAppVersion=0.2.0 installer.iss
; Produce: dist_installer\FOX-Setup.exe

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

#define AppName "FOX"
#define AppPublisher "FOX"
#define AppExeName "FOX.exe"

[Setup]
AppId={{8F3A6C21-4D7E-4B19-9A62-FOX0ASSISTANT}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
OutputDir=dist_installer
OutputBaseFilename=FOX-Setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Chiede l'elevazione solo se serve: così l'utente può installare anche senza admin
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
UninstallDisplayName={#AppName}
UninstallDisplayIcon={app}\{#AppExeName}
; L'icona si usa solo se c'e' davvero: senza questo controllo Inno si ferma
; con "The system cannot find the path specified" invece di proseguire.
#if FileExists(AddBackslash(SourcePath) + "assets\fox.ico")
SetupIconFile=assets\fox.ico
#endif

[Languages]
Name: "italiano"; MessagesFile: "compiler:Languages\Italian.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked
Name: "startupicon"; Description: "Avvia FOX all'accesso a Windows"; GroupDescription: "Avvio"; Flags: unchecked

[Files]
; L'intera cartella prodotta da PyInstaller (COLLECT name="FOX")
Source: "dist\FOX\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon
Name: "{userstartup}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: startupicon

[Run]
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#AppName}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; I modelli AI scaricati dalle impostazioni non stanno in {app}, ma la cache sì
Type: filesandordirs; Name: "{app}\_internal\__pycache__"
