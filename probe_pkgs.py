import paramiko

cli = paramiko.SSHClient()
cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
cli.connect('10.0.0.34', 22, 'root', '1', timeout=10, allow_agent=False, look_for_keys=False)
for cmd in [
    'grep -rls "192.168.10.240" /etc/yum.repos.d/ 2>/dev/null',
    'ls /etc/yum.repos.d/ | head -20',
    'grep -rl "myrepo" /etc/yum.repos.d/ 2>/dev/null',
    'grep -rl "myrepo" /etc/apt/ 2>/dev/null',
]:
    _, out, _ = cli.exec_command(cmd)
    print('###', cmd)
    print(out.read().decode('utf-8', 'ignore').strip()[:600])
    print()
cli.close()
