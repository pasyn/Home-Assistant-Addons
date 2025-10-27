# Netmaker Client Home Assistant Add-on

The Netmaker Client add-on connects your Home Assistant host to a Netmaker-managed WireGuard® network. The add-on bundles the official `netclient` daemon so that the Home Assistant supervisor can automatically join, monitor, and reconnect to your virtual network.

## Features

- Runs the upstream Netmaker `netclient` daemon with supervisor lifecycle management.
- Persists client state in the add-on data folder to survive container restarts and host reboots.
- Supports enrollment via token or key, optional post-up/post-down shell hooks, and automatic daemon restarts.
- Ships with WireGuard tooling required for Netmaker-managed interfaces.

## Requirements

- A running Netmaker server reachable from your Home Assistant environment.
- An enrollment token **or** enrollment key issued by your Netmaker administrator.
- The target Netmaker network ID you would like the Home Assistant host to join.
- Host networking and NET_ADMIN privileges (enabled automatically by the add-on). Ensure this aligns with your security policies before installing.

## Installation

1. Add this repository to your Home Assistant supervisor: **Settings → Add-ons → Add-on Store → ⋮ → Repositories** and paste `https://github.com/pasyn/Home-Assistant-Addons`.
2. Locate **Netmaker Client** in the add-on store and click **Install**.
3. Open the add-on configuration tab and supply the required Netmaker settings (described below).
4. Start the add-on. The supervisor logs will display join progress and any connection errors.

## Configuration

All options are available from the add-on configuration panel. An empty string disables optional settings.

| Option | Required | Description |
| ------ | -------- | ----------- |
| `server_url` | Yes | Base URL of your Netmaker server (for example `https://nm.example.com`). |
| `enrollment_token` | One of token/key | Enrollment token obtained from the Netmaker UI/CLI. Leave blank if using `enrollment_key`. |
| `enrollment_key` | One of token/key | Legacy enrollment key. Leave blank if using `enrollment_token`. |
| `network_id` | Yes | Identifier of the Netmaker network to join (typically the network name). |
| `log_level` | No | Log level passed to the `netclient` daemon (`trace`, `debug`, `info`, `warn`, or `error`). |
| `post_up` | No | Optional shell command executed after a successful (re)join. Useful for custom routing rules. |
| `post_down` | No | Optional shell command executed when the add-on stops. |
| `auto_reconnect` | No | When enabled, restarts the `netclient` daemon if it exits unexpectedly. |
| `reconnect_interval` | No | Seconds to wait before restarting the daemon when `auto_reconnect` is enabled. |
| `leave_on_stop` | No | Leave the Netmaker network when the add-on stops (removes peer from the network). |

### Hooks

`post_up` and `post_down` run inside the add-on container using `/bin/bash -c "<command>"`. Commands execute with root privileges—take care to validate and escape user-provided values. If a hook fails, the add-on logs a warning but continues running.

## Data Persistence

The add-on stores Netmaker configuration and the last-used enrollment signature in `/data/netmaker` inside the container, which maps to the Home Assistant data partition. This preserves WireGuard keys and connection metadata across updates and reboots.

## Security Considerations

- The add-on runs with host networking and the `NET_ADMIN` capability to manage WireGuard interfaces. Restrict access to the supervisor UI and repository to trusted administrators.
- Enrollment tokens and keys grant access to your Netmaker network. Rotate them regularly and store them in a secure location.
- Review the commands you place in `post_up`/`post_down` hooks—they execute as root on the Home Assistant host OS.

## Troubleshooting

- Check the add-on logs for join errors (invalid token, firewall issues, etc.).
- Ensure the Home Assistant host can reach your Netmaker server on HTTPS and UDP ports required by the target network.
- For persistent issues, stop the add-on, enable `leave_on_stop`, restart to remove the peer, and start again with a fresh enrollment token.

## Updating

The `NETCLIENT_VERSION` build argument controls which release of `netclient` is bundled. Rebuild the add-on or adjust the repository configuration when a new upstream version is available.
