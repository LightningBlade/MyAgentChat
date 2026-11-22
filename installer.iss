[Setup]
AppId={{6F1B7E52-3C0A-4D8B-9A57-2E4C1D9B8A10}
AppName=My Agent Chat
AppVersion=1.0.0
DefaultDirName={autopf}\MyAgentChat
DefaultGroupName=My Agent Chat
OutputDir=installer_output
OutputBaseFilename=MyAgentChatSetup
Compression=lzma
SolidCompression=yes
PrivilegesRequired=lowest
CloseApplications=yes
UninstallDisplayIcon={app}\MyAgentChat.exe

[Files]
Source: "dist\MyAgentChat.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\My Agent Chat"; Filename: "{app}\MyAgentChat.exe"
Name: "{autodesktop}\My Agent Chat"; Filename: "{app}\MyAgentChat.exe"

[Run]
Filename: "{app}\MyAgentChat.exe"; Description: "Start My Agent Chat"; Flags: nowait postinstall
