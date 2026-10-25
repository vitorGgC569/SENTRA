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
CreateAppDir=yes
Uninstallable=no
CloseApplications=no
RestartApplications=no
SetupMutex=Local\SENTRA.Setup.v1
WizardStyle=modern
Compression=lzma2/fast
SolidCompression=yes
OutputDir={#OutputRoot}
OutputBaseFilename=SENTRA-Setup
VersionInfoOriginalFileName=SENTRA-Inno-Setup.exe
VersionInfoVersion={#ProductVersion}
VersionInfoTextVersion={#ProductVersion}
SetupLogging=yes

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Files]
Source: "{#BundleRoot}\*"; DestDir: "{tmp}\sentra-bootstrap"; Flags: recursesubdirs createallsubdirs ignoreversion deleteafterinstall

[Run]
Filename: "{app}\sentra-launcher.exe"; Description: "Open SENTRA"; Flags: postinstall nowait skipifsilent; Check: MayLaunch

[Code]
var
  WorkerSucceeded: Boolean;
  WorkerFailureCode: Integer;
  RecoveryPage: TInputOptionWizardPage;
  WorkerFailureText: String;
  WorkerNoticeText: String;

procedure InitializeWizard;
begin
  if ActiveLanguage = 'brazilianportuguese' then begin
    RecoveryPage := CreateInputOptionPage(wpSelectDir, 'Instalação e recuperação',
      'Escolha como instalar o SENTRA',
      'A instalação normal preserva os componentes existentes. Na instalação limpa, os componentes antigos são guardados em backup antes da substituição. Projetos, conversas e contas são preservados. Configurações inválidas podem ser recuperadas no modo Seguro. Feche o SENTRA antes de substituir uma instalação em uso.', False, False);
    RecoveryPage.Add('Instalação limpa: substituir componentes anteriores, guardando uma cópia');
    RecoveryPage.Add('Recuperar configurações locais danificadas no modo Seguro');
  end else begin
    RecoveryPage := CreateInputOptionPage(wpSelectDir, 'Installation and recovery',
      'Choose how to install SENTRA',
      'Normal installation preserves existing components. Clean installation backs up old components before replacing them. Projects, conversations and accounts are preserved. Invalid settings can be recovered in Safe mode. Close SENTRA before replacing an active installation.', False, False);
    RecoveryPage.Add('Clean installation: replace previous components, retaining a backup');
    RecoveryPage.Add('Recover damaged local settings in Safe mode');
  end;
end;

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
  Result := WorkerSucceeded and not ParamExists('NO-LAUNCH');
end;

function GetCustomSetupExitCode: Integer;
begin
  if WorkerSucceeded then Result := 0
  else if WorkerFailureCode > 0 then Result := WorkerFailureCode
  else Result := 2;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  if (CurPageID = wpFinished) and WorkerSucceeded and (WorkerNoticeText <> '') then
    WizardForm.FinishedLabel.Caption := WizardForm.FinishedLabel.Caption + #13#10 + #13#10 + WorkerNoticeText;
  if (CurPageID = wpFinished) and not WorkerSucceeded then begin
    if ActiveLanguage = 'brazilianportuguese' then begin
      WizardForm.FinishedHeadingLabel.Caption := 'O SENTRA precisa de atenção';
      WizardForm.FinishedLabel.Caption := WorkerFailureText;
    end else begin
      WizardForm.FinishedHeadingLabel.Caption := 'SENTRA needs attention';
      WizardForm.FinishedLabel.Caption := WorkerFailureText;
    end;
    WizardForm.RunList.Visible := False;
  end;
end;

procedure AddParameter(var Arguments: String; Name: String; Switch: String);
var Value: String;
begin
  Value := ExpandConstant('{param:' + Name + '|}');
  if Value <> '' then Arguments := Arguments + ' ' + Switch + ' ' + Quoted(Value);
end;

procedure CurStepChanged(CurStep: TSetupStep);
var Code, I: Integer; Arguments, Worker, FailureFile: String; Lines: TArrayOfString;
begin
  if CurStep <> ssPostInstall then Exit;
  WorkerFailureCode := 2;
  Worker := ExpandConstant('{tmp}\sentra-bootstrap\sentra-installer.exe');
  Arguments := '--silent --local-only --no-launch --no-git --install-dir ' + Quoted(ExpandConstant('{app}'));
  FailureFile := ExpandConstant('{tmp}\sentra-setup-failure.txt');
  Arguments := Arguments + ' --setup-message-file ' + Quoted(FailureFile);
  if ActiveLanguage = 'brazilianportuguese' then begin
    Arguments := Arguments + ' --setup-language pt-BR';
    WorkerFailureText := 'A configuração não foi concluída. Consulte installer-last-run.json na pasta de dados do SENTRA.';
  end else begin
    Arguments := Arguments + ' --setup-language en';
    WorkerFailureText := 'Configuration did not finish. Review installer-last-run.json in the SENTRA state folder.';
  end;
  if RecoveryPage.Values[0] or ParamExists('SENTRA-CLEAN-INSTALL') then Arguments := Arguments + ' --clean-install';
  if RecoveryPage.Values[1] or ParamExists('SENTRA-RECOVER-SETTINGS') then Arguments := Arguments + ' --repair-damaged-settings';
  AddParameter(Arguments, 'SENTRA-STATE-DIR', '--state-dir');
  AddParameter(Arguments, 'SENTRA-HANDOFF', '--offline-handoff');
  AddParameter(Arguments, 'SENTRA-MCP-PORT', '--mcp-port');
  AddParameter(Arguments, 'SENTRA-RELAY-PORT', '--relay-port');
  AddParameter(Arguments, 'SENTRA-TUNNEL-ARCHIVE', '--tunnel-archive');
  if ParamExists('SENTRA-NO-REGISTRATION') then Arguments := Arguments + ' --no-system-registration';
  if ParamExists('SENTRA-STOP-AFTER-DOCTOR') then Arguments := Arguments + ' --stop-after-doctor';
  if ActiveLanguage = 'brazilianportuguese' then
    WizardForm.StatusLabel.Caption := 'Configurando o SENTRA. Contas e dados dos projetos são preservados.'
  else
    WizardForm.StatusLabel.Caption := 'Configuring SENTRA. Existing accounts and project data are preserved.';
  if not Exec(Worker, Arguments, ExpandConstant('{tmp}\sentra-bootstrap'), SW_HIDE, ewWaitUntilTerminated, Code) then
    RaiseException('SENTRA installation worker could not start.');
  if Code <> 0 then begin
    WorkerFailureCode := Code;
    if LoadStringsFromFile(FailureFile, Lines) and (GetArrayLength(Lines) > 0) then begin
      WorkerFailureText := '';
      for I := 0 to GetArrayLength(Lines) - 1 do
        if Length(WorkerFailureText) < 4096 then WorkerFailureText := WorkerFailureText + Lines[I] + #13#10;
    end;
    if not WizardSilent then SuppressibleMsgBox(WorkerFailureText, mbError, MB_OK, IDOK);
    Exit;
  end;
  WorkerSucceeded := True;
  WorkerFailureCode := 0;
  if LoadStringsFromFile(FailureFile, Lines) then
    for I := 0 to GetArrayLength(Lines) - 1 do
      if Length(WorkerNoticeText) < 4096 then WorkerNoticeText := WorkerNoticeText + Lines[I] + #13#10;
end;
