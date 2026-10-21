# Installing QuaTrel in a Proxmox container

**Guide version:** 1.1 (2026-10-21)
**For:** QuaTrel 0.1.3
**Result:** QuaTrel running as a service in a Debian 13 LXC container, reachable from any computer on your LAN (and over your VPN, if you use one), protected by a password.

Each step names the window it happens in. There are four:

- **Proxmox web UI**: your browser, signed in to Proxmox at `https://PROXMOX-IP:8006`
- **Container console**: Proxmox web UI → your QuaTrel container → **Console**
- **Proxmox host shell**: Proxmox web UI → your Proxmox node (the server itself, not the container) → **Shell**
- **Your computer's terminal**: Windows PowerShell on Windows, or Terminal on macOS or Linux

Placeholders to replace as you go:

- `PROXMOX-IP`: the address of your Proxmox host (the part before `:8006` in the browser's address bar when you use the Proxmox web UI)
- `CTID`: the container ID number you choose in Step 2 (for example `110`)
- `CT-IP`: the fixed address you give the container in Step 4

---

## Part A: Create the container

**Step 1: Get the QuaTrel zip onto your computer.** On the QuaTrel GitHub page, click the green **Code** button, then **Download ZIP**. Rename the downloaded file to `quatrel.zip` and leave it in your Downloads folder.

**Step 2: Download the Debian 13 template, if you don't have it.** In the **Proxmox web UI**, in the left tree, click your node, then the **local** storage under it, then **CT Templates**. If a `debian-13-standard` template is already listed, skip to Step 3. Otherwise click **Templates**, type `debian-13` in the search box, select **debian-13-standard** (the newest listed), click **Download**, and wait for "TASK OK".

**Step 3: Create the container.** In the **Proxmox web UI**, click **Create CT** (top right). Fill in each tab:

- **General:** CT ID = the next free number (note it; that's your `CTID`). Hostname = `quatrel`. Leave **Unprivileged container** ticked. Set a root password and store it in your password manager.
- **Template:** Storage = local; Template = the debian-13-standard template.
- **Disks:** Disk size = 4 GB, on the storage your other containers use.
- **CPU:** Cores = 1.
- **Memory:** Memory = 512 MiB; Swap = 512 MiB.
- **Network:** Bridge = vmbr0. IPv4 = **DHCP** for now (Step 4 makes it fixed). IPv6 = DHCP or SLAAC if your network uses IPv6; otherwise **Static** with the boxes left blank.
- **DNS:** leave both fields blank to use the host's settings.
- **Confirm:** tick **Start after created**, then click **Finish**. Wait for "TASK OK".

---

## Part B: Give the container a fixed address

A service needs an address that never changes. Rather than relying on a DHCP reservation (some consumer routers and mesh systems don't list containers as clients), give the container a fixed address chosen *outside* your router's DHCP pool, so the router can never hand that address to another device.

**Step 4a: Note the network size and gateway.** In the **Proxmox web UI**, click the new container, then **Console**, and log in as `root`. In the **container console**, run:

```bash
ip -4 addr show eth0
ip route
```

In the first output, note the number after the slash in the `inet` address (for example `/24` or `/22`). In the second, note the address after `default via`; that's your gateway.

**Step 4b: Find your router's DHCP pool.** In your router's app or web page, find the DHCP settings and note where the address pool starts and ends. You'll choose an address *outside* that range, usually below its start.

**Step 4c: Make sure your chosen address is free.** Pick an address in the same network but outside the pool. In the **container console**, run (with your chosen address):

```bash
ping -c 3 CT-IP
```

You want it to end with **100% packet loss**, meaning nothing answered. If anything replies, that address is in use: pick another and ping it the same way.

**Step 4d: Set the fixed address.** In the **Proxmox web UI**, with the container selected, click **Network**, select the **net0** line, and click **Edit**. Set IPv4 to **Static**, IPv4/CIDR to your address with the slash number from Step 4a (for example `192.168.1.40/24`), and Gateway (IPv4) to the gateway from Step 4a. Click **OK**.

**Step 4e: Restart the container and confirm.** In the **Proxmox web UI**, click the small arrow beside **Shutdown** and choose **Reboot**, then wait for "Reboot ... OK" in the task list. This clears the old DHCP address. Open the **Console** again, log in, and in the **container console** run:

```bash
ip -4 addr show eth0
ping -c 3 1.1.1.1
```

The first should show only your fixed address. The second should show `0% packet loss`.

If the old DHCP address is still listed, or the ping fails, recheck Step 4d's address, slash number, and gateway before going on.

**Step 4f: Set the container's time zone.** QuaTrel uses the server's date as "today," so the container must be in your time zone; otherwise evenings can be recorded as tomorrow. In the **container console**, run (replacing `America/Los_Angeles` with your zone from the list in `/usr/share/zoneinfo`):

```bash
ln -sf /usr/share/zoneinfo/America/Los_Angeles /etc/localtime
echo "America/Los_Angeles" > /etc/timezone
date
```

The `date` output should show your local time and time zone abbreviation.

---

## Part C: Prepare the container

**Step 5: Update Debian and install Python.** In the **container console**, run these one at a time:

```bash
apt update
apt -y full-upgrade
apt -y install python3 python3-venv unzip
```

If any of them ends with a line starting `E:`, stop and resolve that error before going on.

**Step 6: Create QuaTrel's service account and folders.** QuaTrel runs as its own limited account, not as root. The program goes in `/opt/quatrel` and your data in `/var/lib/quatrel`, so upgrades never touch your data. In the **container console**, run:

```bash
useradd --system --home-dir /opt/quatrel --shell /usr/sbin/nologin quatrel
mkdir -p /opt/quatrel /var/lib/quatrel
chown quatrel:quatrel /var/lib/quatrel
chmod 750 /var/lib/quatrel
```

---

## Part D: Copy QuaTrel into the container

This takes two hops: from your computer to the Proxmox host, then from the host into the container.

**Step 7: Check that your computer has scp.** In **your computer's terminal**, run:

```powershell
scp
```

It should print a usage message starting with `usage: scp`. On Windows, if PowerShell says `scp` is not recognized, add **OpenSSH Client** under Settings → System → Optional features, then close PowerShell and open a new window.

**Step 8: Copy the zip to the Proxmox host.** In **your computer's terminal**, run (on Windows PowerShell as shown; on macOS or Linux use `~/Downloads/quatrel.zip` for the first path):

```powershell
scp $HOME\Downloads\quatrel.zip root@PROXMOX-IP:/root/
```

Answer `yes` if asked whether to continue connecting, then enter the Proxmox root password. A progress line ending in `100%` means it worked.

If you see **WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED**, your computer remembers an older key for that address, which is common after reinstalling Proxmox or moving it to new hardware. Before trusting the new key, confirm it: in the **Proxmox host shell**, run `ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub` and check that its `SHA256:` value matches the one in the warning. If it matches, run `ssh-keygen -R PROXMOX-IP` in **your computer's terminal** and repeat this step. If it doesn't match, stop and investigate.

**Step 9: Push the zip into the container.** In the **Proxmox host shell**, run:

```bash
pct push CTID /root/quatrel.zip /root/quatrel.zip
```

No output means it worked.

---

## Part E: Install and start QuaTrel

**Step 10: Unpack QuaTrel and install its Python packages.** GitHub's zip contains a folder named `quatrel-main`; these commands unpack it and move its contents into place. In the **container console**, run these one at a time:

```bash
unzip -o /root/quatrel.zip -d /root/quatrel-unpacked
cp -r /root/quatrel-unpacked/quatrel-main/. /opt/quatrel/
python3 -m venv /opt/quatrel/.venv
/opt/quatrel/.venv/bin/pip install -r /opt/quatrel/requirements.txt
```

The last command should end with `Successfully installed`, listing Flask and waitress.

**Step 11: Create the settings file and set a password.** Choose a password first and store it in your password manager. Avoid quote marks and backslashes. In the **container console**, run:

```bash
cp /opt/quatrel/deploy/quatrel.env.example /etc/quatrel.env
chown root:quatrel /etc/quatrel.env
chmod 640 /etc/quatrel.env
nano /etc/quatrel.env
```

In nano, move to the last line and type your password after `QUATREL_PASSWORD=`, with no space and no quotes. Press Ctrl+O, then Enter to save, then Ctrl+X to exit. Confirm with:

```bash
grep PASSWORD /etc/quatrel.env
```

**Step 12: Install and start the service.** In the **container console**, run:

```bash
cp /opt/quatrel/deploy/quatrel.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now quatrel
systemctl status quatrel --no-pager
```

The status should show **active (running)**, with a line starting "QuaTrel 0.1.3".

If it shows **failed** instead, run `journalctl -u quatrel -n 30 --no-pager` in the **container console** and read the last lines for the cause.

**Step 13: Open QuaTrel.** In your browser, go to `http://CT-IP:5000`. Type anything as the user name and your password from Step 11. You should see QuaTrel's welcome page.

**Step 14: Start the container with the host.** In the **Proxmox web UI**, click the container, then **Options**, double-click **Start at boot**, tick the box, and click **OK**. Otherwise QuaTrel stays off after a power outage or a Proxmox reboot.

---

## Reference

**Changing the password.** In the **container console**: `nano /etc/quatrel.env`, change the `QUATREL_PASSWORD=` line, save, then `systemctl restart quatrel`.

**Upgrading QuaTrel.** Download the new zip and copy it in as in Steps 8 and 9. Then in the **container console**:

```bash
systemctl stop quatrel
rm -rf /root/quatrel-unpacked
unzip -o /root/quatrel.zip -d /root/quatrel-unpacked
cp -r /root/quatrel-unpacked/quatrel-main/. /opt/quatrel/
/opt/quatrel/.venv/bin/pip install -r /opt/quatrel/requirements.txt
systemctl start quatrel
systemctl status quatrel --no-pager
```

Your data in `/var/lib/quatrel` is untouched. If the release notes say the service file changed, also repeat the first two commands of Step 12.

**Backups.** Include the container in your Proxmox backup jobs, and make an occasional JSON backup from QuaTrel's Import / export page, kept somewhere off the server.

**Security notes.**

- QuaTrel uses plain HTTP. On a home LAN, the password crosses the network lightly encoded rather than encrypted. Over a VPN such as Tailscale or WireGuard, the whole connection is encrypted.
- Don't forward QuaTrel's port on your router. For access away from home, use a VPN.

## Revision history

| Version | Date | Notes |
|---|---|---|
| 1.0 | 2026-10-21 | First version, for QuaTrel 0.1.2 (written for one specific network). |
| 1.1 | 2026-10-21 | General version for any network: download step, fixed address outside the DHCP pool, time zone, changed host key check, GitHub zip layout, Start at boot. |
