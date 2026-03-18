# VPN Library (`libs/vpn`)

Automates connecting the SealSuite / CorpLink VPN on macOS so that automation
jobs can reach Haidilao internal resources without manual intervention.

---

## Prerequisites

| Requirement | Notes |
|-------------|-------|
| **CorpLink.app** | Install from `/Applications/CorpLink.app`. Override path with `SEALSUITE_EXE`. |
| **cliclick** | `brew install cliclick` — used to send hardware-level mouse clicks |
| **Accessibility permission** | System Settings → Privacy & Security → Accessibility → grant permission to Terminal / your runner |
| **CorpLink account** | Must be pre-authenticated; the library does not handle login |

> **Why cliclick?**  Electron apps ignore `CGEvent` inputs that lack a proper
> `CGEventSource`. `cliclick` creates events with
> `kCGEventSourceStateHIDSystemState`, which Electron's renderer correctly
> processes. AppleScript `click AXButton` is also unreliable because CorpLink
> does not expose its buttons via the Accessibility API.

---

## Quick Start

```python
from vpn import ensure_vpn

ensure_vpn()          # no-op if already connected and session is fresh
                      # raises VPNAppNotFoundError or VPNConnectionError on failure
```

Call `ensure_vpn()` at the top of any automation entry point that needs
intranet access.

---

## How `ensure_vpn()` Works

```
ensure_vpn()
│
├─ _is_connected()?
│   ├─ YES → _get_connected_hours() < max_connected_hours (default 6)?
│   │           YES  → return immediately (session healthy)
│   │           NO   → fall through to reconnect (session stale)
│   └─ NO  → fall through to connect
│
├─ _launch_fresh()
│   ├─ _quit_app()           # graceful quit, force-kill after 10 s
│   ├─ open -a CorpLink.app  # Popen (detached)
│   ├─ poll until PID appears (up to 60 s)
│   └─ sleep 6 s             # let UI fully render before clicking
│
├─ _connect_vpn()
│   ├─ _normalize_window()   # AppleScript: move window to (100,100), resize to 900×560
│   ├─ _activate()           # bring CorpLink to foreground
│   ├─ cliclick m:400,215    # hover over Overview VPN Connectivity toggle
│   └─ cliclick c:400,215    # click toggle
│
├─ poll _is_connected() every 3 s (up to 60 s)
│   └─ connected → hide CorpLink window (do NOT quit)
│
└─ timeout → raise VPNConnectionError
```

### Session cycling

CorpLink's server enforces a ~7.5-hour hard session limit. `ensure_vpn()` will
proactively cycle the connection if the current session has been up for
`max_connected_hours` (default: 6 h), leaving a comfortable buffer.

### Why hide instead of quit?

Quitting CorpLink sends a `ClientClose` message to `corplink-service`, which
tears down the WireGuard tunnel. The window is hidden instead — the tunnel
stays alive as long as the process runs.

---

## Calibrated Click Offsets

The Overview VPN Connectivity toggle is clicked using fixed pixel offsets from
the **AppleScript window origin** after the window is normalized to position
`(100, 100)` with size `900 × 560`.

| Constant | Value | Meaning |
|----------|-------|---------|
| `_OVERVIEW_TOGGLE_DX` | `400` | Pixels right from window left edge |
| `_OVERVIEW_TOGGLE_DY` | `115` | Pixels down from window top edge |

These offsets were measured manually on **CorpLink v3.1.21** running on macOS
with display scaling at the default (2× Retina — cliclick takes logical pixels).

**Why the Overview toggle and not the Network tab Connect button?**

The Network tab's large Connect button has non-deterministic React
initialization time (observed 3–40 seconds after the tab mounts before it
becomes interactive). The Overview tab's VPN Connectivity toggle is immediately
interactive on a fresh app launch and responds reliably to `cliclick`.

**If the offset drifts** (after a CorpLink UI update), re-calibrate:

1. Launch CorpLink fresh.
2. Run the normalize AppleScript manually to position the window at `(100, 100)`.
3. Use a screen ruler or `cliclick p` to find the toggle's screen coordinates.
4. Subtract 100 from each to get the new `DX`/`DY` values.
5. Update `_OVERVIEW_TOGGLE_DX` and `_OVERVIEW_TOGGLE_DY` in `_darwin.py`.

---

## Status Detection

VPN status is determined by tailing
`/usr/local/corplink/logs/corplink.log` — world-readable, no special
permissions required.

The reader scans the log **in reverse** (8 KB chunks) so it finds the most
recent event quickly regardless of log size.

| Log pattern | Meaning |
|-------------|---------|
| `WireGuard Connected` | Tunnel just came up (fires within ~1 s) |
| `reportVpnStatus start map[ip:…` | Tunnel in steady state (fires a few seconds later) |
| `vpn.go:\d+: VPN Disconnected` | Tunnel torn down |

---

## Error Types

| Exception | When raised |
|-----------|-------------|
| `VPNAppNotFoundError` | CorpLink.app not found, or process didn't appear after launch |
| `VPNConnectionError` | `cliclick` not installed, timed out, or VPN didn't connect within poll window |

Both inherit from `VPNError`.

---

## Running Tests

### Unit tests (no live CorpLink needed)

```bash
uv run --project libs/vpn pytest libs/vpn/tests/test_darwin.py -v
```

### E2E tests (requires running CorpLink + Accessibility permission)

```bash
uv run --project libs/vpn pytest libs/vpn/tests/test_e2e.py -v -s
```

E2E tests exercise the real `ensure_vpn()` flow against the live CorpLink
application. They will quit, relaunch, and connect CorpLink as part of the
test run — do not run them while using VPN-dependent resources.

---

## Environment Variables

| Variable | Description |
|----------|-------------|
| `SEALSUITE_EXE` | Override the CorpLink app path (default: `/Applications/CorpLink.app`) |

---

## Module Layout

```
libs/vpn/
├── src/vpn/
│   ├── __init__.py        # re-exports ensure_vpn, VPNError hierarchy
│   ├── _darwin.py         # macOS implementation (cliclick + log parsing)
│   └── errors.py          # VPNError, VPNAppNotFoundError, VPNConnectionError
└── tests/
    ├── test_darwin.py     # 21 unit tests (mocked fs + subprocess)
    └── test_e2e.py        # 5 e2e tests (live CorpLink)
```
