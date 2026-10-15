using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Windows.Forms;
using Microsoft.Win32;

[assembly: System.Reflection.AssemblyTitle("SENTRA")]
[assembly: System.Reflection.AssemblyDescription("SENTRA Desktop launcher")]
[assembly: System.Reflection.AssemblyCompany("SENTRA")]

internal static class SentraLauncher
{
    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    private static extern int SetCurrentProcessExplicitAppUserModelID(string id);

    // Development builds may explicitly bind to one checkout. Release builds
    // leave these empty and resolve the installed app through its registration.
    private const string DevelopmentExecutable = /*DEV_EXECUTABLE*/ "";
    private const string DevelopmentArguments = /*DEV_ARGUMENTS*/ "";
    private const string DevelopmentDirectory = /*DEV_DIRECTORY*/ "";

    [STAThread]
    private static int Main()
    {
        SetCurrentProcessExplicitAppUserModelID("SENTRA.Desktop");
        try
        {
            string executable, arguments = "", directory;
            if (DevelopmentExecutable.Length != 0)
            {
                executable = DevelopmentExecutable;
                arguments = DevelopmentArguments;
                directory = DevelopmentDirectory;
            }
            else
            {
                using (var key = Registry.CurrentUser.OpenSubKey(@"Software\Microsoft\Windows\CurrentVersion\Uninstall\SENTRA Desktop"))
                    directory = key == null ? "" : Convert.ToString(key.GetValue("InstallLocation", ""));
                if (String.IsNullOrWhiteSpace(directory) || !Path.IsPathRooted(directory))
                    throw new InvalidOperationException("Abra o SENTRA Setup para concluir a instalação.");
                executable = Path.Combine(directory, "sentra-canvas.exe");
                if (!File.Exists(Path.Combine(directory, ".sentra-install.json")))
                    throw new InvalidOperationException("A instalação precisa ser reparada pelo SENTRA Setup.");
            }
            if (!File.Exists(executable) || !Directory.Exists(directory))
                throw new FileNotFoundException("O aplicativo não foi encontrado. Abra o SENTRA Setup para reparar.");
            Process.Start(new ProcessStartInfo(executable, arguments) {
                WorkingDirectory = directory, UseShellExecute = false, CreateNoWindow = true
            });
            return 0;
        }
        catch (Exception)
        {
            MessageBox.Show("Não foi possível abrir o SENTRA. Execute o SENTRA Setup para concluir ou reparar a instalação.",
                            "SENTRA", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return 2;
        }
    }
}
