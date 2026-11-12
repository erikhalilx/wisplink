#!/usr/bin/env bash
set -euo pipefail
umask 022

die() { printf '%s\n' "$*" >&2; exit 1; }

if [[ ${1:-} == --help ]]; then
    echo "Usage: sudo bash deploy/install-ecs.sh --check|--install CONSOLE_HOST PREVIEW_HOST PUBLIC_IPV4"
    exit 0
fi
[[ $# == 4 && ( $1 == --check || $1 == --install ) ]] || die "Run with --help for usage."
mode=$1
console=$2
preview=$3
public_ip=$4
host_pattern='^([a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z][a-z0-9-]{0,62}$'
[[ $console =~ $host_pattern && $preview =~ $host_pattern && $console != "$preview" ]] ||
    die "Use two distinct lowercase DNS hostnames without a scheme, port, or path."
[[ $public_ip =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || die "Provide the ECS public IPv4 address."
[[ $(uname -m) == x86_64 && -r /etc/os-release ]] ||
    die "Supported server: Alibaba Cloud ECS, Alibaba Cloud Linux 3.2104 LTS (x86_64)."
# shellcheck disable=SC1091
. /etc/os-release
[[ ${ID:-} == alinux && ( ${VERSION_ID:-} == 3 || ${VERSION_ID:-} == 3.2104 ) ]] ||
    die "Supported server: Alibaba Cloud ECS, Alibaba Cloud Linux 3.2104 LTS (x86_64)."
[[ $EUID == 0 ]] || die "Run this script via sudo on the ECS host."

source_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
cd "$source_dir"
app_dir=/opt/wisplink
data_dir=/var/lib/wisplink
web_dir=/var/www/wisplink
env_file=/etc/wisplink/wisplink.env
marker=/etc/wisplink/ecs-install
nginx_file=/etc/nginx/conf.d/wisplink.conf
console_tls=${WISPLINK_CONSOLE_TLS_DIR:-/etc/letsencrypt/live/$console}
preview_tls=${WISPLINK_PREVIEW_TLS_DIR:-$console_tls}
units=(wisplink-api.service wisplink-auth.service wisplink-cleanup.service wisplink-cleanup.timer)
release=$(sed -n 's/^version = "\([^"]*\)"$/\1/p' pyproject.toml)
[[ $release =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "Run from a WispLink release archive."
expected_marker=$(printf '%s\n' "$release" "$console" "$preview" "$console_tls" "$preview_tls")
[[ -f web/dist/index.html ]] || die "Build the web console first (cd web && npm ci && npm run build)."
[[ -x /usr/bin/python3.11 ]] || die "Install the system python3.11 package first."
for command in uv nginx openssl systemctl ss curl getent sudo flock; do
    command -v "$command" >/dev/null || die "Missing prerequisite: $command"
done
[[ -d /run/systemd/system ]] || die "A running systemd instance is required."
if [[ $mode == --install ]]; then
    exec 9>/run/lock/wisplink-install.lock
    flock -n 9 || die "Another WispLink installation is running."
fi

for host in "$console" "$preview"; do
    resolved=$(getent ahostsv4 "$host" || true)
    awk -v ip="$public_ip" '$1 == ip {found=1} END {exit !found}' <<< "$resolved" ||
        die "DNS for $host does not resolve to the provided public IPv4."
done
check_tls() {
    local host=$1 directory=$2
    [[ $directory =~ ^/[A-Za-z0-9_./-]+$ ]] || die "Invalid certificate directory."
    [[ -r $directory/fullchain.pem && -r $directory/privkey.pem ]] ||
        die "Prepare fullchain.pem and privkey.pem in $directory for $host."
    openssl x509 -in "$directory/fullchain.pem" -noout -checkend 0 >/dev/null ||
        die "The certificate for $host is invalid or expired."
    openssl x509 -in "$directory/fullchain.pem" -noout -checkhost "$host" |
        grep -Fq " does match certificate" || die "The certificate does not cover $host."
}
check_tls "$console" "$console_tls"
check_tls "$preview" "$preview_tls"

nginx_config=$(nginx -T 2>&1) || die "Existing Nginx configuration is invalid. Run nginx -t for details."
grep -Eq 'include[[:space:]]+(/etc/nginx/)?conf\.d/\*\.conf;' <<< "$nginx_config" ||
    die "Nginx must include /etc/nginx/conf.d/*.conf from its http block."

render_nginx() {
    /usr/bin/python3.11 - "$console" "$preview" "$console_tls" "$preview_tls" <<'PY'
import re
import sys
from pathlib import Path

console, preview, console_tls, preview_tls = sys.argv[1:]
replacements = {
    "/etc/letsencrypt/live/console.example.com": console_tls,
    "/etc/letsencrypt/live/preview.example.com": preview_tls,
    "console.example.com": console,
    "preview.example.com": preview,
}
pattern = "|".join(map(re.escape, replacements))
template = Path("deploy/wisplink.nginx.conf").read_text()
sys.stdout.write(re.sub(pattern, lambda match: replacements[match[0]], template))
PY
}
check_file() {
    local target=$1
    [[ ! -L $target && ( ! -e $target || -f $target ) ]] || die "Unsupported path: $target"
}
check_file "$marker"
check_file "$nginx_file"
check_file "$env_file"
for path in /etc/wisplink "$app_dir" "$data_dir" "$web_dir"; do
    [[ ! -L $path && ( ! -e $path || -d $path ) ]] || die "Unsupported path: $path"
done
if [[ -e $marker ]]; then
    [[ $(<"$marker") == "$expected_marker" ]] ||
        die "A different WispLink installation exists. Use the existing deployment or the upgrade guide."
    if [[ -e $nginx_file ]]; then
        render_nginx | cmp -s "$nginx_file" - || die "The WispLink Nginx file was modified. Review it manually."
    fi
    if [[ -e $env_file ]]; then
        for setting in "WISPLINK_DATA_DIR=$data_dir" "WISPLINK_CONSOLE_ORIGIN=https://$console" "WISPLINK_PREVIEW_ORIGIN=https://$preview"; do
            grep -Fxq "$setting" "$env_file" || die "The WispLink environment file was modified. Review it manually."
        done
    fi
else
    for path in /etc/wisplink "$app_dir" "$data_dir" "$web_dir" "$nginx_file"; do
        [[ ! -e $path && ! -L $path ]] || die "An unmanaged path already exists: $path"
    done
    listeners=$(ss -H -ltn '( sport = :8000 or sport = :8001 )') ||
        die "Could not check local TCP ports."
    [[ -z $listeners ]] || die "TCP port 8000 or 8001 is already in use."
    awk -v a="$console" -v b="$preview" '
        $1 == "server_name" {
            for (i=2; i<=NF; i++) {
                name=$i
                sub(/;$/, "", name)
                if (name == a || name == b) exit 1
            }
        }
    ' <<< "$nginx_config" || die "A requested hostname already appears in Nginx."
fi
for unit in "${units[@]}"; do
    target=/etc/systemd/system/$unit
    check_file "$target"
    if [[ -e $target ]]; then
        [[ -e $marker ]] && cmp -s "$target" "deploy/$unit" ||
            die "An unmanaged or modified systemd unit already exists: $target"
    fi
done
[[ $mode == --install ]] || { echo "Preflight passed. Run again with --install to deploy."; exit 0; }

if [[ ! -e $marker ]]; then
    mkdir -m 0750 /etc/wisplink
    printf '%s\n' "$expected_marker" > "$marker"
fi
if ! id wisplink >/dev/null 2>&1; then
    useradd --system --home-dir "$data_dir" --shell /sbin/nologin wisplink
fi
install -d -m 0700 -o wisplink -g wisplink "$data_dir"
chown root:wisplink /etc/wisplink
install -d -m 0755 "$app_dir" "$web_dir"
cp -R wisplink pyproject.toml uv.lock LICENSE "$app_dir/"
cp -R web/dist/. "$web_dir/"
(cd "$app_dir" && uv sync --locked --no-dev --no-managed-python --python /usr/bin/python3.11)
if [[ ! -e $env_file ]]; then
    key=$("$app_dir/.venv/bin/python" -m wisplink.manage generate-key)
    (
        umask 077
        printf 'WISPLINK_DATA_DIR=%s\nWISPLINK_CONSOLE_ORIGIN=https://%s\nWISPLINK_PREVIEW_ORIGIN=https://%s\nWISPLINK_KEY=%s\n' \
            "$data_dir" "$console" "$preview" "$key" > "$env_file.tmp"
    )
    chown root:wisplink "$env_file.tmp"
    chmod 0640 "$env_file.tmp"
    mv -f "$env_file.tmp" "$env_file"
fi
sudo -u wisplink sh -c 'umask 077; set -a; . /etc/wisplink/wisplink.env; set +a; /opt/wisplink/.venv/bin/python -m wisplink.manage migrate'
install -m 0644 "${units[@]/#/deploy/}" /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now wisplink-api wisplink-auth wisplink-cleanup.timer

if [[ ! -e $nginx_file ]]; then
    render_nginx > "$nginx_file.tmp"
    mv -f "$nginx_file.tmp" "$nginx_file"
    if ! nginx_test=$(nginx -t 2>&1) ||
        grep -Fq -e "conflicting server name \"$console\"" -e "conflicting server name \"$preview\"" <<< "$nginx_test"; then
        printf '%s\n' "$nginx_test" >&2
        unlink "$nginx_file"
        die "Nginx rejected the generated site. The existing Nginx service was not reloaded."
    fi
fi
nginx -t
systemctl enable --now nginx
systemctl reload nginx
instance=$(curl --noproxy '*' -fsS --retry 4 --max-time 10 --resolve "$console:443:127.0.0.1" "https://$console/api/v1/instance")
/usr/bin/python3.11 -c 'import json,sys; data=json.load(sys.stdin); sys.exit(data.get("product") != "wisplink" or data.get("console_origin") != sys.argv[1])' "https://$console" <<< "$instance" ||
    die "The local HTTPS response did not identify the expected instance."
printf 'WispLink is ready at https://%s. Create the first administrator using the deployment guide.\n' "$console"
