# Codex 反向访问宿主机工作树流程

本文记录 Codex 登录远程机器、但事实工作树位于宿主机时，如何通过反向 SSH 隧道读写宿主机仓库。

## 事实源

唯一事实源为宿主机工作树：

```text
puyin@p15s-ubuntu-2:~/code/algorithm/robot/map_tools_ws/src/map-tools-beiguo
```

远程机器只作为执行入口。读文件、改代码、跑测试、提交都应落到宿主机工作树，避免改到远程机器副本。

## 机器与端口

- 宿主机：`puyin@p15s-ubuntu-2`
- 宿主机局域网 IP：`10.58.72.148`
- 宿主机 Tailscale IP：`100.64.0.10`
- Codex 远程机器：`192.168.9.76`
- Codex 远程机器公网 SSH 入口：`-p 20023 yuanyayun@base.preco.fun`
- 反向隧道端口：`127.0.0.1:2222` on `192.168.9.76`

## 宿主机前置检查

在宿主机执行：

```bash
sudo systemctl status ssh
ss -lntp | grep ':22'
ip addr
ip route
sudo ufw status verbose
ping -c 3 192.168.9.76
```

期望：

- `ssh.service` 为 `active (running)`。
- `sshd` 监听 `0.0.0.0:22` 或 `:::22`。
- 宿主机能 ping 通 `192.168.9.76`。

如需放行 SSH：

```bash
sudo ufw allow from 192.168.9.76 to any port 22 proto tcp
```

## 建立反向隧道

在宿主机执行：

```bash
ssh -N -R 127.0.0.1:2222:127.0.0.1:22 -p 20023 yuanyayun@base.preco.fun
```

这个终端会保持占用，不要关闭。

需要自动重连时，在宿主机使用：

```bash
while true; do
  ssh -N -o ServerAliveInterval=30 -o ServerAliveCountMax=3 \
    -R 127.0.0.1:2222:127.0.0.1:22 -p 20023 yuanyayun@base.preco.fun
  sleep 2
done
```

## Codex 侧验证

在 Codex 远程机器执行：

```bash
ssh -o UserKnownHostsFile=/tmp/maptools_host_reverse_known_hosts \
  -o StrictHostKeyChecking=accept-new \
  -p 2222 puyin@127.0.0.1 hostname
```

期望输出：

```text
p15s-ubuntu-2
```

验证目标仓库：

```bash
ssh -o UserKnownHostsFile=/tmp/maptools_host_reverse_known_hosts \
  -o StrictHostKeyChecking=accept-new \
  -p 2222 puyin@127.0.0.1 \
  'cd ~/code/algorithm/robot/map_tools_ws/src/map-tools-beiguo && pwd && git status --short'
```

期望路径：

```text
/home/puyin/code/algorithm/robot/map_tools_ws/src/map-tools-beiguo
```

## 后续读写约定

后续所有针对用户可视化环境的操作，都应通过反向隧道在宿主机工作树中执行：

```bash
ssh -o UserKnownHostsFile=/tmp/maptools_host_reverse_known_hosts \
  -o StrictHostKeyChecking=accept-new \
  -p 2222 puyin@127.0.0.1 \
  'cd ~/code/algorithm/robot/map_tools_ws/src/map-tools-beiguo && <command>'
```

常用检查：

```bash
ssh -o UserKnownHostsFile=/tmp/maptools_host_reverse_known_hosts -p 2222 puyin@127.0.0.1 \
  'cd ~/code/algorithm/robot/map_tools_ws/src/map-tools-beiguo && git status --short'

ssh -o UserKnownHostsFile=/tmp/maptools_host_reverse_known_hosts -p 2222 puyin@127.0.0.1 \
  'cd ~/code/algorithm/robot/map_tools_ws/src/map-tools-beiguo && python3 -m pytest tests/test_main_window_flow.py -q'
```

## 故障排查

`Connection timed out` 通常表示反向隧道没有建立或已经断开。回到宿主机重新执行 `ssh -N -R ...`。

`Connection timed out during banner exchange` 通常表示 `127.0.0.1:2222` 仍在监听，但后端没有连到宿主机 `sshd`。关闭旧隧道终端后重新建立隧道。

`Host key verification failed` 时使用独立 known hosts 文件：

```bash
-o UserKnownHostsFile=/tmp/maptools_host_reverse_known_hosts
```

`Permission denied (publickey,password)` 时检查宿主机：

```bash
ls -ld ~/.ssh
ls -l ~/.ssh/authorized_keys
wc -l ~/.ssh/authorized_keys
head -1 ~/.ssh/authorized_keys | cut -d' ' -f1
head -1 ~/.ssh/authorized_keys | cut -d' ' -f2 | cut -c1-8
```

权限和格式应为：

```text
~/.ssh                 700
~/.ssh/authorized_keys 600
第一字段               ssh-rsa
第二字段开头           AAAAB3Nz
```
