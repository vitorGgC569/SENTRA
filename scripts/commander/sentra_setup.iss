; SENTRA's transaction retains ownership checks, data recovery and uninstall.
; Inno supplies the single Windows wizard, compressed media and extraction.
#ifndef BundleRoot
  #error BundleRoot is required
#endif
#ifndef OutputRoot
  #error OutputRoot is required
#endif
#ifndef ProductVersion
  #error ProductVersion is required
#endif

[Setup]
AppId=SENTRA.Desktop
AppName=SENTRA
AppVersion={#ProductVersion}
AppPublisher=SENTRA
DefaultDirName={localappdata}\SENTRA\Commander
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
UsePreviousAppDir=no
DisableDirPage=no
DisableProgramGroupPage=yes
CreateAppDir=no
Uninstallable=no
CloseApplications=no
RestartApplications=no
SetupMutex=Local\SENTRA.Setup.v1
WizardStyle=modern
Compression=lzma2/normal
SolidCompression=yes
OutputDir={#OutputRoot}
OutputBaseFilename=SENTRA-Setup
VersionInfoOriginalFileName=SENTRA-Inno-Setup.exe
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Files]
Source: "{#BundleRoot}\*"; DestDir: "{tmp}\sentra-bootstrap"; Flags: recursesubdirs createallsubdirs ignoreversion deleteafterinstall

[Run]
Filename: "{app}\sentra-launcher.exe"; Description: "Open SENTRA"; Flags: postinstall nowait skipifsilent; Check: MayLaunch

[Code]
function ParamExists(Name: String): Boolean;
var I: Integer;
begin
  Result := False;
  for I := 1 to ParamCount do
    if CompareText(ParamStr(I), '/' + Name) = 0 then Result := True;
end;

function Quoted(Value: String): String;
begin
  if Pos('"', Value) > 0 then RaiseException('Invalid quotation in setup argument');
  Result := '"' + Value + '"';
end;

function MayLaunch: Boolean;
begin
  Result := not ParamExists('NO-LAUNCH');
end;

procedure AddParameter(var Arguments: String; Name: String; Switch: String);
var Value: String;
begin
  Value := ExpandConstant('{param:' + Name + '|}');
  if Value <> '' then Arguments := Arguments + ' ' + Switch + ' ' + Quoted(Value);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var Code: Integer; Arguments, Worker: String;
begin
  if CurStep <> ssPostInstall then Exit;
  Worker := ExpandConstant('{tmp}\sentra-bootstrap\sentra-installer.exe');
  Arguments := '--silent --local-only --no-launch --no-git --install-dir ' + Quoted(ExpandConstant('{app}'));
  AddParameter(Arguments, 'SENTRA-STATE-DIR', '--state-dir');
  AddParameter(Arguments, 'SENTRA-HANDOFF', '--offline-handoff');
  AddParameter(Arguments, 'SENTRA-MCP-PORT', '--mcp-port');
  AddParameter(Arguments, 'SENTRA-RELAY-PORT', '--relay-port');
  AddParameter(Arguments, 'SENTRA-TUNNEL-ARCHIVE', '--tunnel-archive');
  if ParamExists('SENTRA-NO-REGISTRATION') then Arguments := Arguments + ' --no-system-registration';
  if ParamExists('SENTRA-STOP-AFTER-DOCTOR') then Arguments := Arguments + ' --stop-after-doctor';
  WizardForm.StatusLabel.Caption := 'Configuring SENTRA. Existing accounts and project data are preserved.';
  if not Exec(Worker, Arguments, ExpandConstant('{tmp}\sentra-bootstrap'), SW_HIDE, ewWaitUntilTerminated, Code) then
    RaiseException('SENTRA installation worker could not start.');
  if Code <> 0 then
    RaiseException('SENTRA configuration needs attention (code ' + IntToStr(Code) + '). Open setup again to repair; review installer-last-run.json in the SENTRA state folder.');
end;
