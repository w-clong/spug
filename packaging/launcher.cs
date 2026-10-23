// Spug 便携版启动器（C# / .NET Framework，winexe 无控制台）
// 职责：
//   1) 定位私有 runtime，注入 SPUG_APP_ROOT / SPUG_DATA_DIR / SPUG_FRONTEND_DIR；
//   2) 以 pythonw.exe 启动 app\startup.py；
//   3) 提供原生托盘图标（打开界面 / 退出）——用 Win32 NotifyIcon 实现，
//      因此便携包无需 Pillow / pystray，省下约 14MB。
using System;
using System.Diagnostics;
using System.Drawing;
using System.IO;
using System.Text.RegularExpressions;
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
        // 托盘由本启动器提供，通知 Python 端不要再用 pystray 创建一个（避免两个图标）
        psi.EnvironmentVariables["SPUG_LAUNCHER"] = "1";

        Process child;
        try
        {
            child = Process.Start(psi);
        }
        catch (Exception e)
        {
            MessageBox.Show("Spug 启动失败：" + e.Message, "Spug", MessageBoxButtons.OK, MessageBoxIcon.Error);
            return;
        }

        if (args.Length > 0)
        {
            // 带参数（如 init / stop）时按命令行语义执行，不驻留托盘
            child.WaitForExit();
            if (child.ExitCode != 0)
            {
                MessageBox.Show("Spug 已退出（代码 " + child.ExitCode + "）。\n\n详情请查看 data\\spug.log", "Spug",
                    MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
            return;
        }

        try
        {
            Application.EnableVisualStyles();
            Application.Run(new TrayApp(root, child));
        }
        catch (Exception e)
        {
            // 托盘不可用（无桌面会话 / WinForms 初始化失败）时退化为后台运行，
            // 保证服务照常启动，不因为托盘问题导致整个程序起不来
            MessageBox.Show("托盘图标初始化失败，Spug 将在后台运行。\n\n" + e.Message, "Spug",
                MessageBoxButtons.OK, MessageBoxIcon.Warning);
            try
            {
                child.WaitForExit();
            }
            catch
            {
                // ignore
            }
        }
    }

    private sealed class TrayApp : ApplicationContext
    {
        private readonly NotifyIcon _tray;
        private readonly Process _child;
        private readonly string _url;
        private bool _exiting;

        public TrayApp(string root, Process child)
        {
            _child = child;
            _url = "http://127.0.0.1:" + ReadPort(root) + "/";

            var menu = new ContextMenuStrip();
            menu.Items.Add("打开 Spug 界面", null, (s, e) => OpenBrowser());
            menu.Items.Add(new ToolStripSeparator());
            menu.Items.Add("退出", null, (s, e) => Shutdown());

            _tray = new NotifyIcon
            {
                Icon = LoadIcon(),
                Text = "Spug 运维平台",
                Visible = true,
                ContextMenuStrip = menu,
            };
            _tray.DoubleClick += (s, e) => OpenBrowser();

            child.EnableRaisingEvents = true;
            child.Exited += (s, e) =>
            {
                if (_exiting) return;
                _exiting = true;
                _tray.Visible = false;
                _tray.Dispose();
                // 服务异常退出时给个提示，避免用户以为还在运行
                if (child.ExitCode != 0)
                {
                    MessageBox.Show("Spug 已退出（代码 " + child.ExitCode + "）。\n\n详情请查看 data\\spug.log", "Spug",
                        MessageBoxButtons.OK, MessageBoxIcon.Warning);
                }
                ExitThread();
            };
            // 浏览器由 app\startup.py 的桌面模式负责打开（含首次建库与单实例检测），
            // 这里只提供托盘，避免重复打开两个标签页。
        }

        private static Icon LoadIcon()
        {
            // 优先用 exe 自身嵌入的图标（构建时 /win32icon 注入 favicon.ico）。
            // 不用 Icon.ExtractAssociatedIcon：它只能取到 32x32，且部分系统上会退化成默认图标。
            try
            {
                var ico = Icon.ExtractAssociatedIcon(Application.ExecutablePath);
                if (ico != null) return ico;
            }
            catch
            {
                // ignore
            }
            // 退一步：从 exe 的资源里按大尺寸加载，托盘/任务栏都更清晰
            try
            {
                var large = new Icon(Application.ExecutablePath, new Size(32, 32));
                if (large != null) return large;
            }
            catch
            {
                // ignore
            }
            return SystemIcons.Application;
        }

        private static int ReadPort(string root)
        {
            var env = Environment.GetEnvironmentVariable("SPUG_PORT");
            int port;
            if (!string.IsNullOrEmpty(env) && int.TryParse(env, out port) && port > 0) return port;
            try
            {
                var ini = Path.Combine(root, "spug.ini");
                if (File.Exists(ini))
                {
                    foreach (var line in File.ReadAllLines(ini))
                    {
                        var m = Regex.Match(line, @"^\s*port\s*=\s*(\d+)", RegexOptions.IgnoreCase);
                        if (m.Success && int.TryParse(m.Groups[1].Value, out port) && port > 0)
                            return port;
                    }
                }
            }
            catch
            {
                // ignore
            }
            return 9000;
        }

        private void OpenBrowser()
        {
            try
            {
                Process.Start(new ProcessStartInfo(_url) { UseShellExecute = true });
            }
            catch (Exception e)
            {
                MessageBox.Show("无法打开浏览器：" + e.Message + "\n请手动访问 " + _url, "Spug",
                    MessageBoxButtons.OK, MessageBoxIcon.Warning);
            }
        }

        private void Shutdown()
        {
            _exiting = true;
            _tray.Visible = false;
            try
            {
                if (!_child.HasExited)
                {
                    _child.Kill();
                    _child.WaitForExit(5000);
                }
            }
            catch
            {
                // ignore
            }
            _tray.Dispose();
            ExitThread();
        }
    }
}
