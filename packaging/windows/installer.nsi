Unicode true
ManifestDPIAware true
RequestExecutionLevel user
Name "HiFine"
OutFile "${OUTPUT}"
InstallDir "$LOCALAPPDATA\Programs\HiFine"
SetCompressor /SOLID lzma
SetCompressorDictSize 32
Icon "..\HiFine.ico"
UninstallIcon "..\HiFine.ico"
VIProductVersion "${APP_VERSION}.0"
VIAddVersionKey /LANG=1033 "ProductName" "HiFine"
VIAddVersionKey /LANG=1033 "FileDescription" "HiFine image viewer setup"
VIAddVersionKey /LANG=1033 "FileVersion" "${APP_VERSION}"
VIAddVersionKey /LANG=1033 "LegalCopyright" "HiFine contributors"

!include MUI2.nsh
!include LogicLib.nsh
!include x64.nsh
!define /ifndef SOFTWARE_ROOT "Software"
!define /ifndef SHORTCUT_DIR "$SMPROGRAMS"
!define CLASSES "${SOFTWARE_ROOT}\Classes"
!define CAPABILITIES "${SOFTWARE_ROOT}\HiFine\Capabilities"
!define UNINSTALL "${SOFTWARE_ROOT}\Microsoft\Windows\CurrentVersion\Uninstall\HiFine"
!define CLSID "{85E522D8-EC6F-4163-9F28-96B13B918743}"
!define THUMBNAIL "{E357FCCD-A995-4576-B01F-234630154E96}"
!define WINDOWS_PHOTO_THUMBNAIL "{C7657C4A-9F68-40FA-A4DF-96BC08EB3551}"

!define MUI_WELCOMEPAGE_TEXT "$(CloseHiFine)"
!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_INSTFILES
!define MUI_FINISHPAGE_RUN "$INSTDIR\HiFine.exe"
!define MUI_FINISHPAGE_SHOWREADME
!define MUI_FINISHPAGE_SHOWREADME_FUNCTION OpenDefaultSettings
!define MUI_FINISHPAGE_SHOWREADME_TEXT "$(SetDefault)"
!define MUI_FINISHPAGE_SHOWREADME_NOTCHECKED
!insertmacro MUI_PAGE_FINISH
!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES
!insertmacro MUI_LANGUAGE "English"
!insertmacro MUI_LANGUAGE "SimpChinese"
LangString CloseHiFine ${LANG_ENGLISH} "Close any open HiFine windows before continuing with the installation."
LangString CloseHiFine ${LANG_SIMPCHINESE} "如果 HiFine 正在运行，请先关闭所有 HiFine 窗口，再继续安装。"
LangString SetDefault ${LANG_ENGLISH} "Choose file types for HiFine in Default apps"
LangString SetDefault ${LANG_SIMPCHINESE} "在默认应用设置中选择用 HiFine 打开的图片格式"
LangString NeedX64 ${LANG_ENGLISH} "This edition of HiFine requires an x64 Windows PC."
LangString NeedX64 ${LANG_SIMPCHINESE} "此版本的 HiFine 适用于 x64 Windows 电脑。"

Function .onInit
  ${IfNot} ${IsNativeAMD64}
    MessageBox MB_ICONSTOP "$(NeedX64)"
    Abort
  ${EndIf}
  SetRegView 64
FunctionEnd
Function un.onInit
  SetRegView 64
FunctionEnd
Function OpenDefaultSettings
  ExecShell "open" "ms-settings:defaultapps?registeredAppUser=HiFine"
FunctionEnd

; Windows stores the user's explicit default in UserChoice. OpenWithProgids
; and RegisteredApplications let the normal Windows chooser select HiFine.
!macro register_type EXT PROGID
  WriteRegStr HKCU "${CLASSES}\.${EXT}\OpenWithProgids" "${PROGID}" ""
  WriteRegStr HKCU "${CLASSES}\Applications\HiFine.exe\SupportedTypes" ".${EXT}" ""
  WriteRegStr HKCU "${CAPABILITIES}\FileAssociations" ".${EXT}" "${PROGID}"
!macroend
!macro unregister_type EXT PROGID
  DeleteRegValue HKCU "${CLASSES}\.${EXT}\OpenWithProgids" "${PROGID}"
  DeleteRegKey /ifempty HKCU "${CLASSES}\.${EXT}\OpenWithProgids"
  DeleteRegKey /ifempty HKCU "${CLASSES}\.${EXT}"
!macroend
!macro all_types OP
  !insertmacro ${OP} jpg  HiFine.Image
  !insertmacro ${OP} jpeg HiFine.Image
  !insertmacro ${OP} jpe  HiFine.Image
  !insertmacro ${OP} jfif HiFine.Image
  !insertmacro ${OP} png  HiFine.Image
  !insertmacro ${OP} bmp  HiFine.Image
  !insertmacro ${OP} gif  HiFine.Image
  !insertmacro ${OP} webp HiFine.Image
  !insertmacro ${OP} tif  HiFine.Image
  !insertmacro ${OP} tiff HiFine.Image
  !insertmacro ${OP} ico  HiFine.Image
  !insertmacro ${OP} avif HiFine.Image
  !insertmacro ${OP} hif  HiFine.Heif
  !insertmacro ${OP} heif HiFine.Heif
  !insertmacro ${OP} heic HiFine.Heif
!macroend
!macro progid ID LABEL HANDLER
  WriteRegStr HKCU "${CLASSES}\${ID}" "" "${LABEL}"
  WriteRegStr HKCU "${CLASSES}\${ID}\DefaultIcon" "" "$\"$INSTDIR\HiFine.exe$\",0"
  WriteRegStr HKCU "${CLASSES}\${ID}\shell\open\command" "" "$\"$INSTDIR\HiFine.exe$\" $\"%1$\""
  WriteRegStr HKCU "${CLASSES}\${ID}\shellex\${THUMBNAIL}" "" "${HANDLER}"
!macroend
!macro register_thumbnail KEY
  ; A user-installed handler has priority. A machine-wide handler is exposed
  ; again automatically when our per-user value is removed.
  ClearErrors
  ReadRegStr $0 HKCU "${CLASSES}\${KEY}\shellex\${THUMBNAIL}" ""
  ${If} ${Errors}
    WriteRegStr HKCU "${CLASSES}\${KEY}\shellex\${THUMBNAIL}" "" "${CLSID}"
  ${EndIf}
!macroend
!macro unregister_thumbnail KEY
  ReadRegStr $0 HKCU "${CLASSES}\${KEY}\shellex\${THUMBNAIL}" ""
  ${If} $0 == "${CLSID}"
    DeleteRegValue HKCU "${CLASSES}\${KEY}\shellex\${THUMBNAIL}" ""
    DeleteRegKey /ifempty HKCU "${CLASSES}\${KEY}\shellex\${THUMBNAIL}"
    DeleteRegKey /ifempty HKCU "${CLASSES}\${KEY}\shellex"
    DeleteRegKey /ifempty HKCU "${CLASSES}\${KEY}"
  ${EndIf}
!macroend
!macro heif_thumbnails OP
  !insertmacro ${OP} ".hif"
  !insertmacro ${OP} ".heif"
  !insertmacro ${OP} ".heic"
  !insertmacro ${OP} "SystemFileAssociations\.hif"
  !insertmacro ${OP} "SystemFileAssociations\.heif"
  !insertmacro ${OP} "SystemFileAssociations\.heic"
!macroend

Section "HiFine"
  SetShellVarContext current
  SetOutPath "$INSTDIR"
  File /r "${BUNDLE}\*.*"
  WriteUninstaller "$INSTDIR\Uninstall.exe"
  CreateShortcut "${SHORTCUT_DIR}\HiFine.lnk" "$INSTDIR\HiFine.exe"
  WriteRegStr HKCU "${UNINSTALL}" "DisplayName" "HiFine"
  WriteRegStr HKCU "${UNINSTALL}" "DisplayVersion" "${APP_VERSION}"
  WriteRegStr HKCU "${UNINSTALL}" "DisplayIcon" "$INSTDIR\HiFine.exe"
  WriteRegStr HKCU "${UNINSTALL}" "InstallLocation" "$INSTDIR"
  WriteRegStr HKCU "${UNINSTALL}" "UninstallString" "$\"$INSTDIR\Uninstall.exe$\""
  WriteRegDWORD HKCU "${UNINSTALL}" "NoModify" 1
  WriteRegDWORD HKCU "${UNINSTALL}" "NoRepair" 1
  WriteRegStr HKCU "${CLASSES}\Applications\HiFine.exe" "FriendlyAppName" "HiFine"
  WriteRegStr HKCU "${CLASSES}\Applications\HiFine.exe\shell\open\command" "" "$\"$INSTDIR\HiFine.exe$\" $\"%1$\""
  WriteRegStr HKCU "${CAPABILITIES}" "ApplicationName" "HiFine"
  WriteRegStr HKCU "${CAPABILITIES}" "ApplicationDescription" "HiFine desktop image viewer"
  WriteRegStr HKCU "${CAPABILITIES}" "ApplicationIcon" "$\"$INSTDIR\HiFine.exe$\",0"
  WriteRegStr HKCU "${SOFTWARE_ROOT}\RegisteredApplications" "HiFine" "${CAPABILITIES}"
  WriteRegStr HKCU "${CLASSES}\CLSID\${CLSID}" "" "HiFine HEIF Thumbnail Provider"
  WriteRegStr HKCU "${CLASSES}\CLSID\${CLSID}\InprocServer32" "" "$INSTDIR\HiFineThumbnail.dll"
  WriteRegStr HKCU "${CLASSES}\CLSID\${CLSID}\InprocServer32" "ThreadingModel" "Apartment"
  !insertmacro progid HiFine.Image "HiFine image" "${WINDOWS_PHOTO_THUMBNAIL}"
  !insertmacro progid HiFine.Heif "HiFine HEIF image" "${CLSID}"
  !insertmacro all_types register_type
  !insertmacro heif_thumbnails register_thumbnail
  ; An unclaimed .hif can open immediately, including on a clean Windows PC.
  ReadRegStr $0 HKCU "${CLASSES}\.hif" ""
  ${If} $0 == ""
    ReadRegStr $0 HKLM "${CLASSES}\.hif" ""
  ${EndIf}
  ReadRegStr $1 HKCU "${SOFTWARE_ROOT}\Microsoft\Windows\CurrentVersion\Explorer\FileExts\.hif\UserChoice" "ProgId"
  ${If} $0 == ""
  ${AndIf} $1 == ""
    WriteRegStr HKCU "${CLASSES}\.hif" "" "HiFine.Heif"
  ${EndIf}
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
SectionEnd

Section "Uninstall"
  SetShellVarContext current
  !insertmacro all_types unregister_type
  !insertmacro heif_thumbnails unregister_thumbnail
  ReadRegStr $0 HKCU "${CLASSES}\.hif" ""
  ${If} $0 == "HiFine.Heif"
    DeleteRegValue HKCU "${CLASSES}\.hif" ""
    DeleteRegKey /ifempty HKCU "${CLASSES}\.hif"
  ${EndIf}
  DeleteRegKey HKCU "${CLASSES}\HiFine.Image"
  DeleteRegKey HKCU "${CLASSES}\HiFine.Heif"
  DeleteRegKey HKCU "${CLASSES}\Applications\HiFine.exe"
  DeleteRegKey HKCU "${CLASSES}\CLSID\${CLSID}"
  DeleteRegValue HKCU "${SOFTWARE_ROOT}\RegisteredApplications" "HiFine"
  DeleteRegKey HKCU "${CAPABILITIES}"
  DeleteRegKey /ifempty HKCU "${SOFTWARE_ROOT}\HiFine"
  DeleteRegKey HKCU "${UNINSTALL}"
  Delete "${SHORTCUT_DIR}\HiFine.lnk"
  !include "${MANIFEST}"
  Delete /REBOOTOK "$INSTDIR\Uninstall.exe"
  RMDir /REBOOTOK "$INSTDIR"
  System::Call 'shell32::SHChangeNotify(i 0x08000000, i 0, p 0, p 0)'
SectionEnd
