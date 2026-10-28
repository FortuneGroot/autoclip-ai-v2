Option Explicit

Dim files, shell, project, command, result
Set files = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
project = files.GetParentFolderName(WScript.ScriptFullName)
command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ _
    & project & "\Start iPhone Server.ps1"" -OpenApp"
result = shell.Run(command, 0, True)
If result <> 0 Then
    MsgBox "AUTOCLIP AI could not open. Run 'Launch AUTOCLIP AI for iPhone.bat' " _
        & "in the AUTOCLIP_AI folder to see the startup error.", vbExclamation, "AUTOCLIP AI"
End If
