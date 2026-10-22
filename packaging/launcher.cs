// Spug 便携版启动器（C# / .NET Framework，winexe 无控制台）
// 职责：定位私有 runtime，注入 SPUG_APP_ROOT / SPUG_DATA_DIR / SPUG_FRONTEND_DIR，
//       以 pythonw.exe 启动 app\startup.py（桌面模式：托盘 + 自动打开浏览器）。
using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

internal static class Program
{
    [STAThread]
    private static void Main(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd(Path.DirectorySeparatorChar);
        string runtime = Path.Combine(root, "runtime");
        string pythonw = Path.Combine(runtime, "pythonw.exe");
        string script = Path.Combine(root, "app", "startup.py");
        if (!File.Exists(pythonw))
        {
            MessageBox.Show("未找到 runtime\\pythonw.exe，程序包不完整。", "Spug", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }
        if (!File.Exists(script))
        {
            MessageBox.Show("未找到 app\\startup.py，程序包不完整。", "Spug", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }

        var psi = new ProcessStartInfo
        {
            FileName = pythonw,
            Arguments = "\"" + script + "\"" + (args.Length > 0 ? " " + string.Join(" ", args) : ""),
            WorkingDirectory = root,
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        psi.EnvironmentVariables["SPUG_APP_ROOT"] = root;
        psi.EnvironmentVariables["SPUG_DATA_DIR"] = Path.Combine(root, "data");
        psi.EnvironmentVariables["SPUG_FRONTEND_DIR"] = Path.Combine(root, "web");

        try
        {
            using (var process = Process.Start(psi))
            {
                process.WaitForExit();
                if (process.ExitCode != 0)
                {
                    MessageBox.Show("Spug 已退出（代码 " + process.ExitCode + "）。\n\n详情请查看 data\\spug.log", "Spug",
                        MessageBoxButtons.OK, MessageBoxIcon.Warning);
                }
            }
        }
        catch (Exception e)
        {
            MessageBox.Show("Spug 启动失败：" + e.Message, "Spug", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
