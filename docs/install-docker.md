# Installing Docker Engine

The application ships as a container, so the only prerequisite for running it is
**Docker Engine** with the **Compose plugin** (`docker compose`, not the older
standalone `docker-compose` binary).

If Docker is already installed, check that both are present and skip the rest:

```bash
docker --version
docker compose version
```

The authoritative instructions are Docker's own — they are kept up to date and
cover every supported distribution:

- Ubuntu: <https://docs.docker.com/engine/install/ubuntu/>
- Fedora: <https://docs.docker.com/engine/install/fedora/>
- All platforms: <https://docs.docker.com/engine/install/>

The steps below are a condensed version of those pages for the two targets named
in the challenge, recorded here so the evaluation can be reproduced without
leaving the repository. **If they ever disagree with the official docs, follow
the official docs.**

---

## Ubuntu 24.04 (Noble)

### 1. Remove conflicting packages

Skip this if Docker has never been installed on the machine. Otherwise, the
distribution's unofficial packages must go first, since they conflict with
Docker's own:

```bash
sudo apt remove docker.io docker-compose docker-compose-v2 docker-doc \
  docker-buildx podman-docker containerd runc
```

This does **not** delete images, containers or volumes under `/var/lib/docker` —
they survive the reinstall.

### 2. Add Docker's official APT repository

```bash
sudo apt update
sudo apt install ca-certificates curl
sudo install -m 0755 -d /etc/apt/keyrings
```

Download the repository's GPG key and make it world-readable (apt runs the
signature check as an unprivileged user):

```bash
sudo curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
  -o /etc/apt/keyrings/docker.asc
sudo chmod a+r /etc/apt/keyrings/docker.asc
```

Register the repository. The `Suites` and `Architectures` lines are resolved
from the running system, so the same block works on any Ubuntu release:

```bash
sudo tee /etc/apt/sources.list.d/docker.sources <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: $(. /etc/os-release && echo "${UBUNTU_CODENAME:-$VERSION_CODENAME}")
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF

sudo apt update
```

### 3. Install Docker Engine

```bash
sudo apt install docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
```

---

## Fedora 42

### 1. Remove conflicting packages

```bash
sudo dnf remove docker docker-client docker-client-latest docker-common \
  docker-latest docker-latest-logrotate docker-logrotate docker-selinux \
  docker-engine-selinux docker-engine
```

### 2. Add Docker's official DNF repository

```bash
sudo dnf -y install dnf-plugins-core
sudo dnf config-manager addrepo \
  --from-repofile=https://download.docker.com/linux/fedora/docker-ce.repo
```

### 3. Install Docker Engine

```bash
sudo dnf install docker-ce docker-ce-cli containerd.io \
  docker-buildx-plugin docker-compose-plugin
```

### 4. Start the service

Unlike Ubuntu's packages, Fedora's do not enable the daemon automatically:

```bash
sudo systemctl enable --now docker
```

---

## After installing (both distributions)

Confirm the daemon is running and the Compose plugin is available:

```bash
sudo docker run --rm hello-world
sudo docker compose version
```

### Optional: run Docker without `sudo`

Adding your user to the `docker` group lets you drop the `sudo` prefix from
every command in the README:

```bash
sudo usermod -aG docker $USER
newgrp docker          # or log out and back in
docker run --rm hello-world
```

Be aware of what this grants: membership in the `docker` group is equivalent to
root access on the host, because a container can be started with the host
filesystem mounted. On a shared machine, prefer keeping `sudo`, or look into
[rootless mode](https://docs.docker.com/engine/security/rootless/).

---

## Next step

Return to the [README](../README.md#run-with-docker-recommended) and bring the
stack up with `docker compose up --build`.
