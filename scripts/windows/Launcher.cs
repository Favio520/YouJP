using System;
using System.IO;
using System.Linq;
using System.Management.Automation;
using System.Management.Automation.Runspaces;
using System.Runtime.InteropServices;
using System.Text;
using System.Threading;
using System.Windows.Forms;

internal static class Launcher
{
    [DllImport("shell32.dll", CharSet = CharSet.Unicode)]
    private static extern int SetCurrentProcessExplicitAppUserModelID(string appId);

    [STAThread]
    private static int Main(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory;
        string script = Path.Combine(root, "scripts", "windows", "YouJP.ps1");
        bool smoke = args.Contains("--smoke-test");
        bool preview = args.Contains("--preview");
        try
        {
            if (!File.Exists(script))
                throw new FileNotFoundException("Mantén YouJP.exe dentro de la carpeta de YouJP. Puedes crear un acceso directo para abrirlo desde otro lugar.", script);

            SetCurrentProcessExplicitAppUserModelID("YouJP.Desktop");
            // Ejecutar el controlador en este proceso gráfico: sin consola ni
            // otra ventana de PowerShell. La política afecta solo a esta sesión.
            InitialSessionState state = InitialSessionState.CreateDefault();
            state.ExecutionPolicy = Microsoft.PowerShell.ExecutionPolicy.Bypass;
            using (Runspace runspace = RunspaceFactory.CreateRunspace(state))
            {
                runspace.ApartmentState = ApartmentState.STA;
                runspace.ThreadOptions = PSThreadOptions.UseCurrentThread;
                runspace.Open();
                using (PowerShell engine = PowerShell.Create())
                {
                    engine.Runspace = runspace;
                    engine.AddCommand(script);
                    if (smoke) engine.AddParameter("SmokeTest");
                    if (preview) engine.AddParameter("Preview");
                    foreach (string arg in args)
                    {
                        if (arg.StartsWith("--preview-state=", StringComparison.Ordinal))
                            engine.AddParameter("PreviewState", arg.Substring("--preview-state=".Length));
                    }
                    var output = engine.Invoke();
                    if (smoke)
                    {
                        string reportDir = Path.Combine(root, ".youjp");
                        Directory.CreateDirectory(reportDir);
                        string report = string.Join(Environment.NewLine, output.Select(item => item.ToString()));
                        report += Environment.NewLine + string.Join(Environment.NewLine, engine.Streams.Error.Select(item => item.ToString()));
                        File.WriteAllText(Path.Combine(reportDir, "launcher-smoke.log"), report, Encoding.UTF8);
                        return engine.HadErrors ? 1 : 0;
                    }
                }
            }
            return 0;
        }
        catch (Exception error)
        {
            try
            {
                string reportDir = Path.Combine(root, ".youjp");
                Directory.CreateDirectory(reportDir);
                File.WriteAllText(Path.Combine(reportDir, "launcher-error.log"), error.ToString(), Encoding.UTF8);
            }
            catch { }
            if (!smoke)
                MessageBox.Show("YouJP no pudo abrirse.\n\n" + error.Message, "YouJP", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return 1;
        }
    }
}
