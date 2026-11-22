"""UPF de la slice miot dans une VM QEMU/KVM (M05, T07.2) : préparation et création par libvirt.

    .venv/bin/python platform/vm/upf-vm/build.py --vcpus 1 [--memory 1024]     (make up-vm)

La VM remplace le conteneur upf-miot : même adresse N4 / N3 (lue dans platform/core/generated/addresses.json),
même configuration UPF (platform/core/generated/open5gs/upf-miot.yaml), même sous-réseau UE. Elle est raccordée
directement au pont Docker du réseau b6g-core par libvirt (interface de type bridge).

Étapes :
  1. pool libvirt « b6g » dans /var/lib/libvirt/images/b6g (géré par libvirtd, sans sudo pour le groupe libvirt) ;
  2. image de base Ubuntu 22.04 (~/b6g-data/vm, vérifiée par SHA256SUMS) téléversée dans le pool ;
  3. disque de la VM (qcow2 adossé à l'image de base) et disque cloud-init (ISO 9660 construit par xorriso) ;
  4. virt-install --import ; cloud-init installe open5gs-upf (PPA officiel open5gs/latest) et démarre l'UPF.
Accès : ssh -i ~/b6g-data/vm/id_upfvm b6g@<adresse N4>. Réalisme : ÉMULÉ.
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import subprocess
import tempfile
from pathlib import Path

import yaml
from b6g_common import scenario as scn

ROOT = Path(__file__).resolve().parents[3]
DATA = Path.home() / "b6g-data" / "vm"
BASE = DATA / "jammy-server-cloudimg-amd64.img"
KEY = DATA / "id_upfvm"
POOL, POOL_DIR = "b6g", "/var/lib/libvirt/images/b6g"
VIRSH = ["virsh", "-c", "qemu:///system"]
SLICE = "miot"


def sh(*cmd: str, check: bool = True, input: str | None = None) -> str:
    return subprocess.run(cmd, capture_output=True, text=True, check=check, input=input).stdout


def ensure_pool() -> None:
    if POOL not in sh(*VIRSH, "pool-list", "--all", "--name"):
        sh(*VIRSH, "pool-define-as", POOL, "dir", "--target", POOL_DIR)
        sh(*VIRSH, "pool-build", POOL)
    if sh(*VIRSH, "pool-info", POOL).split("State:")[1].split("\n")[0].strip() != "running":
        sh(*VIRSH, "pool-start", POOL)
    sh(*VIRSH, "pool-autostart", POOL)


def vol_exists(name: str) -> bool:
    return name in sh(*VIRSH, "vol-list", POOL, check=False)


def upload(name: str, src: Path, fmt: str) -> None:
    if vol_exists(name):
        sh(*VIRSH, "vol-delete", name, "--pool", POOL)
    sh(*VIRSH, "vol-create-as", POOL, name, str(src.stat().st_size), "--format", fmt)
    sh(*VIRSH, "vol-upload", name, str(src), "--pool", POOL)


def cloud_init(sc: dict, addr: dict, upf_cfg: str, pubkey: str) -> tuple[str, str, str]:
    s = next(x for x in sc["slices"] if x["id"] == SLICE)
    net = ipaddress.ip_network("172.22.0.0/24")
    ip = addr[s["upf"]]
    sub = ipaddress.ip_network(s["subnet"])
    gw_ue = f"{sub[1]}/{sub.prefixlen}"
    meta = f"instance-id: {s['upf']}-vm\nlocal-hostname: {s['upf']}-vm\n"
    network = yaml.safe_dump({"version": 2, "ethernets": {"nic0": {
        "match": {"name": "en*"}, "addresses": [f"{ip}/{net.prefixlen}"],
        "routes": [{"to": "default", "via": str(net[1])}],
        "nameservers": {"addresses": ["8.8.8.8", "8.8.4.4"]}}}})
    user = "#cloud-config\n" + yaml.safe_dump({
        "users": [{"name": "b6g", "groups": "sudo", "shell": "/bin/bash", "sudo": "ALL=(ALL) NOPASSWD:ALL",
                   "ssh_authorized_keys": [pubkey]}],
        "package_update": True,
        "packages": ["software-properties-common", "qemu-guest-agent", "iperf3", "iptables"],
        "write_files": [
            {"path": "/etc/open5gs/upf.yaml", "content": upf_cfg},
            # ogstun de la slice (le paquet open5gs crée ogstun en 10.45.0.1/16 par défaut : remplacé)
            {"path": "/etc/systemd/network/99-open5gs.netdev",
             "content": "[NetDev]\nName=ogstun\nKind=tun\n"},
            {"path": "/etc/systemd/network/99-open5gs.network",
             "content": f"[Match]\nName=ogstun\n\n[Network]\nAddress={gw_ue}\nConfigureWithoutCarrier=yes\n"},
            {"path": "/etc/sysctl.d/90-b6g.conf", "content": "net.ipv4.ip_forward=1\n"},
            # Réseau de l'UPF rétabli à chaque démarrage (ogstun actif, NAT N6), avant open5gs-upfd
            {"path": "/etc/systemd/system/b6g-upf-net.service", "content": (
                "[Unit]\nDescription=B6G : ogstun et NAT de l'UPF\nAfter=systemd-networkd.service\n"
                "Before=open5gs-upfd.service\n\n[Service]\nType=oneshot\nRemainAfterExit=yes\n"
                "ExecStart=/usr/sbin/ip link set ogstun up\n"
                f"ExecStart=/bin/sh -c 'iptables -t nat -C POSTROUTING -s {s['subnet']} ! -o ogstun -j MASQUERADE "
                f"|| iptables -t nat -A POSTROUTING -s {s['subnet']} ! -o ogstun -j MASQUERADE'\n\n"
                "[Install]\nWantedBy=multi-user.target\n")},
        ],
        "runcmd": [
            "sysctl --system",
            "add-apt-repository -y ppa:open5gs/latest",
            "DEBIAN_FRONTEND=noninteractive apt-get install -y open5gs-upf",
            "cp /etc/open5gs/upf.yaml.dpkg-dist /etc/open5gs/upf.yaml.orig || true",
            "systemctl restart systemd-networkd",
            "systemctl daemon-reload",
            "systemctl enable --now b6g-upf-net.service qemu-guest-agent",
            "systemctl enable open5gs-upfd",       # le paquet ne l'active pas au démarrage
            "systemctl restart open5gs-upfd",
            "touch /var/lib/b6g-upf-ready",
        ],
    }, sort_keys=False, allow_unicode=True)
    return meta, user, network


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--vcpus", type=int, default=1)
    ap.add_argument("--max-vcpus", type=int, default=4)
    ap.add_argument("--memory", type=int, default=1024, help="Mio")
    args = ap.parse_args()
    sc = scn.load()
    addr = json.loads((ROOT / "platform" / "core" / "generated" / "addresses.json").read_text())
    upf_cfg = (ROOT / "platform" / "core" / "generated" / "open5gs" / f"upf-{SLICE}.yaml").read_text()
    name = f"upf-{SLICE}-vm"
    if not BASE.exists():
        raise SystemExit(f"image de base absente : {BASE} (voir platform/vm/upf-vm/README.md)")
    if not KEY.exists():
        sh("ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-C", "b6g-upf-vm", "-f", str(KEY))
    bridge = "br-" + sh("docker", "network", "inspect", "b6g-core", "-f", "{{.Id}}").strip()[:12]
    ensure_pool()
    if not vol_exists("jammy-base.qcow2"):
        upload("jammy-base.qcow2", BASE, "qcow2")
    base_path = sh(*VIRSH, "vol-path", "jammy-base.qcow2", "--pool", POOL).strip()
    if vol_exists(f"{name}.qcow2"):
        sh(*VIRSH, "vol-delete", f"{name}.qcow2", "--pool", POOL)
    sh(*VIRSH, "vol-create-as", POOL, f"{name}.qcow2", "10G", "--format", "qcow2",
       "--backing-vol", base_path, "--backing-vol-format", "qcow2")
    meta, user, network = cloud_init(sc, addr, upf_cfg, (KEY.with_suffix(".pub")).read_text().strip())
    with tempfile.TemporaryDirectory() as tmp:
        t = Path(tmp)
        (t / "meta-data").write_text(meta)
        (t / "user-data").write_text(user)
        (t / "network-config").write_text(network)
        iso = t / "seed.iso"
        sh("xorriso", "-as", "mkisofs", "-quiet", "-o", str(iso), "-V", "cidata", "-J", "-r",
           str(t / "meta-data"), str(t / "user-data"), str(t / "network-config"))
        upload(f"{name}-seed.iso", iso, "raw")
    sh("virt-install", "--connect", "qemu:///system", "--name", name, "--memory", str(args.memory),
       "--vcpus", f"{args.vcpus},maxvcpus={args.max_vcpus}", "--cpu", "host-passthrough",
       "--osinfo", "ubuntu22.04", "--import",
       "--disk", f"vol={POOL}/{name}.qcow2,bus=virtio",
       "--disk", f"vol={POOL}/{name}-seed.iso,device=cdrom",
       "--network", f"bridge={bridge},model=virtio",
       "--channel", "unix,target_type=virtio,name=org.qemu.guest_agent.0",
       "--graphics", "none", "--noautoconsole")
    print(f"{name} créée sur {bridge} ({args.vcpus} vCPU, {args.memory} Mio) ; cloud-init en cours "
          f"(installation d'open5gs-upf, 3 à 6 min). Accès : ssh -i {KEY} b6g@{addr['upf-' + SLICE]}")


if __name__ == "__main__":
    main()
