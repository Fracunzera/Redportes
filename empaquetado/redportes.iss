; Instalador de Redportes para Windows (Inno Setup 6).
; Se compila desde GitHub Actions: ISCC /DVersion=x.y.z empaquetado\redportes.iss

#ifndef Version
  #define Version "0.0.0"
#endif

[Setup]
AppId={{8F3C2A51-6B0E-4D3A-9C5E-2E7A1B4D9F10}
AppName=Redportes
AppVersion={#Version}
AppVerName=Redportes {#Version}
AppPublisher=Fracunzera
AppPublisherURL=https://github.com/Fracunzera/Redportes
AppSupportURL=https://github.com/Fracunzera/Redportes/issues
DefaultDirName={autopf}\Redportes
DefaultGroupName=Redportes
DisableProgramGroupPage=yes
; Se instala sin pedir administrador (en la carpeta del usuario); se puede elegir para todos.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir=..\dist
OutputBaseFilename=Redportes-{#Version}-instalador
SetupIconFile=..\redportes\recursos\icono.ico
UninstallDisplayIcon={app}\Redportes.exe
LicenseFile=..\LICENSE
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\Redportes\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\Redportes"; Filename: "{app}\Redportes.exe"
Name: "{group}\Desinstalar Redportes"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Redportes"; Filename: "{app}\Redportes.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Redportes.exe"; Description: "{cm:LaunchProgram,Redportes}"; Flags: nowait postinstall skipifsilent
