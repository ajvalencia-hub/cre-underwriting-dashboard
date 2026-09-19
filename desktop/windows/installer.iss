; CRE Underwriting - Windows installer (Inno Setup 6.3 or later).
;
; Built by desktop\build_windows.ps1, which passes:
;   /DAppVersion=<desktop\cre_desktop\version.py VERSION>
;   /DAppSourceDir=<desktop\dist\CRE Underwriting>
;   /DOutputDir=<desktop\dist>
; Compile by hand (after building the app folder) from the repo root:
;   "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" /DAppVersion=1.0.0 desktop\windows\installer.iss
;
; - Per-user install by default (no admin prompt) to
;   %LOCALAPPDATA%\Programs\CRE Underwriting; the first page lets an admin
;   choose "install for all users" instead.
; - Start-menu shortcut, optional desktop shortcut (ticked by default), and a
;   "Launch CRE Underwriting" box on the last page.
; - Checks for the Microsoft Edge WebView2 Runtime the window needs and offers
;   to download and install it (small bootstrapper from Microsoft).
; - Uninstalling removes the program only: deals, templates, documents and
;   backups in %LOCALAPPDATA%\CRE Underwriting are kept.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef AppSourceDir
  #define AppSourceDir "..\dist\CRE Underwriting"
#endif
#ifndef OutputDir
  #define OutputDir "..\dist"
#endif

#define AppName "CRE Underwriting"
#define AppExeName "CRE Underwriting.exe"
#define AppPublisher "CRE Underwriting"
#define AppUrl "https://github.com/ajvalencia-hub/cre-underwriting-dashboard"

[Setup]
; Stable forever: Windows identifies the installed app (upgrades, uninstall)
; by this id. The doubled brace escapes the GUID's opening brace.
AppId={{6F3C2A1E-8B4D-4E7A-9C51-2D8E7F4B3A60}
AppName={#AppName}
AppVersion={#AppVersion}
AppVerName={#AppName} {#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppUrl}
AppSupportURL={#AppUrl}
AppUpdatesURL={#AppUrl}/releases
VersionInfoVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} Setup
DefaultDirName={autopf}\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
DisableDirPage=auto
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#OutputDir}
OutputBaseFilename=CRE-Underwriting-Setup-{#AppVersion}
SetupIconFile=..\assets\AppIcon.ico
UninstallDisplayIcon={app}\{#AppExeName}
UninstallDisplayName={#AppName}
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
; Upgrading while the app is open: close it first (Restart Manager).
CloseApplications=yes
RestartApplications=no

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Messages]
ConfirmUninstall=Remove %1 from this computer?%n%nYour deals, templates, documents and backups are NOT deleted. They stay in your user folder (AppData\Local\{#AppName}) and the app finds them again if you reinstall.

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "{#AppSourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExeName}"
Name: "{autodesktop}\{#AppName}"; Filename: "{app}\{#AppExeName}"; Tasks: desktopicon

[Run]
Filename: "{tmp}\MicrosoftEdgeWebview2Setup.exe"; Parameters: "/silent /install"; StatusMsg: "Installing the Microsoft Edge WebView2 Runtime..."; Check: ShouldInstallWebView2; Flags: waituntilterminated
Filename: "{app}\{#AppExeName}"; Description: "{cm:LaunchProgram,{#StringChange(AppName, '&', '&&')}}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Only the program folder's own runtime tree (anything Python left beside the
; installed files). The user's data lives elsewhere (see [Messages] above) and
; is never touched.
Type: filesandordirs; Name: "{app}\_internal"

[Code]
const
  WebView2ClientKey = 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  WebView2UserClientKey = 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  WebView2BootstrapperUrl = 'https://go.microsoft.com/fwlink/p/?LinkId=2124703';
  WebView2PageUrl = 'https://developer.microsoft.com/microsoft-edge/webview2/';
  LibreOfficeUrl = 'https://www.libreoffice.org/download/download-libreoffice/';

var
  DownloadPage: TDownloadWizardPage;
  WebView2Downloaded: Boolean;

function WebView2VersionOk(RootKey: Integer; SubKey: String): Boolean;
var
  Version: String;
begin
  Result := RegQueryStringValue(RootKey, SubKey, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0');
end;

{ Microsoft's documented detection: the per-machine key (32-bit registry view
  on 64-bit Windows, i.e. WOW6432Node) or the per-user key. }
function IsWebView2Installed: Boolean;
begin
  Result := WebView2VersionOk(HKLM32, WebView2ClientKey)
    or WebView2VersionOk(HKLM64, WebView2ClientKey)
    or WebView2VersionOk(HKCU, WebView2UserClientKey);
end;

function ShouldInstallWebView2: Boolean;
begin
  Result := WebView2Downloaded and not IsWebView2Installed;
end;

procedure OpenUrl(Url: String);
var
  ErrorCode: Integer;
begin
  ShellExecAsOriginalUser('open', Url, '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
end;

procedure LibreOfficeLinkClick(Sender: TObject);
begin
  OpenUrl(LibreOfficeUrl);
end;

function OnDownloadProgress(const Url, FileName: String; const Progress, ProgressMax: Int64): Boolean;
begin
  if Progress = ProgressMax then
    Log(Format('Downloaded %s', [FileName]));
  Result := True;
end;

procedure InitializeWizard;
var
  Page: TWizardPage;
  Note: TNewStaticText;
  Link: TNewStaticText;
begin
  WebView2Downloaded := False;
  DownloadPage := CreateDownloadPage(SetupMessage(msgWizardPreparing), SetupMessage(msgPreparingDesc), @OnDownloadProgress);

  { Optional tools note, shown after the shortcut choices. }
  Page := CreateCustomPage(wpSelectTasks, 'Optional: LibreOffice',
    'Used for Excel recalculation and PDF memos');
  Note := TNewStaticText.Create(Page);
  Note.Parent := Page.Surface;
  Note.AutoSize := False;
  Note.WordWrap := True;
  Note.Left := 0;
  Note.Top := 0;
  Note.Width := Page.SurfaceWidth;
  Note.Height := ScaleY(150);
  Note.Caption :=
    'CRE Underwriting works without any other software.' + #13#10 + #13#10 +
    'LibreOffice (free) is optional. Install it if you use your own Excel template: ' +
    'it lets the app recalculate your workbook and show your template''s results, run ' +
    'template-verified sensitivities, and save the IC memo as a PDF. Without it, the ' +
    'built-in engine, the Excel model export, the Word memo and the decks all work normally.' + #13#10 + #13#10 +
    'You can install LibreOffice at any time; restart CRE Underwriting afterwards. ' +
    'Settings > External tools shows whether it was found.';
  Link := TNewStaticText.Create(Page);
  Link.Parent := Page.Surface;
  Link.Left := 0;
  Link.Top := Note.Top + Note.Height + ScaleY(8);
  Link.Caption := 'Download LibreOffice (opens your browser)';
  Link.Cursor := crHand;
  Link.Font.Style := [fsUnderline];
  Link.Font.Color := clBlue;
  Link.OnClick := @LibreOfficeLinkClick;
end;

{ Before installing: if the WebView2 runtime is missing, offer to download
  Microsoft's bootstrapper; [Run] then installs it. If the download fails,
  offer the download page instead. The app also checks at every launch. }
function NextButtonClick(CurPageID: Integer): Boolean;
begin
  Result := True;
  if (CurPageID <> wpReady) or IsWebView2Installed then
    Exit;
  if WizardSilent then
    Exit;
  if MsgBox('CRE Underwriting needs the Microsoft Edge WebView2 Runtime to show its window, ' +
            'and it isn''t installed on this PC.' + #13#10 + #13#10 +
            'Download and install it now? (A small, free download from Microsoft.)',
            mbConfirmation, MB_YESNO) <> IDYES then
  begin
    MsgBox('CRE Underwriting will be installed, but it can''t open until the WebView2 Runtime ' +
           'is installed. You can get it later from:' + #13#10 + WebView2PageUrl,
           mbInformation, MB_OK);
    Exit;
  end;
  DownloadPage.Clear;
  DownloadPage.Add(WebView2BootstrapperUrl, 'MicrosoftEdgeWebview2Setup.exe', '');
  DownloadPage.Show;
  try
    try
      DownloadPage.Download;
      WebView2Downloaded := True;
    except
      if DownloadPage.AbortedByUser then
        Log('WebView2 download cancelled.')
      else
        Log('WebView2 download failed: ' + GetExceptionMessage);
      if MsgBox('The WebView2 Runtime could not be downloaded.' + #13#10 + #13#10 +
                'Open the download page in your browser? CRE Underwriting will still be installed.',
                mbError, MB_YESNO) = IDYES then
        OpenUrl(WebView2PageUrl);
    end;
  finally
    DownloadPage.Hide;
  end;
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent then
    MsgBox('CRE Underwriting has been removed.' + #13#10 + #13#10 +
           'Your deals, templates, documents and backups were kept in:' + #13#10 +
           ExpandConstant('{localappdata}\{#AppName}') + #13#10 + #13#10 +
           'Reinstall the app to use them again, or delete that folder if you no longer need them.',
           mbInformation, MB_OK);
end;
