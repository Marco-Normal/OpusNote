"""Where a request came from, and what this machine can see.

Two facts the LAN deployment needs, and neither belongs to a domain:

* **Is this the piano machine?** Irreversible actions are refused from anywhere
  else (ECOSYSTEM.md D8). This is deliberately *not* authentication: there are no
  accounts in this app, and the boundary that matters is which actions cannot be
  undone, not who is asking.
* **Is ALSA's sequencer present?** Web MIDI enumerates the ALSA sequencer, so when
  ``/dev/snd/seq`` does not exist the browser reports *no MIDI devices at all* —
  which reads as a hardware fault and is a missing kernel module.
"""

from __future__ import annotations

import ipaddress
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

router = APIRouter(prefix="/api", tags=["host"])

#: Where ALSA exposes its sequencer, and a readable list of its clients.
SEQUENCER_PATH = Path("/dev/snd/seq")
SEQ_CLIENTS_PATH = Path("/proc/asound/seq/clients")


class HostInfo(BaseModel):
    #: The address this request arrived from, as the server sees it.
    host: str | None
    #: True when the request came from this machine itself.
    loopback: bool
    #: False means Web MIDI will find no devices, whatever is plugged in.
    sequencer: bool
    #: ALSA sequencer clients currently visible, e.g. ["Midi Through", "CASIO USB-MIDI"].
    clients: list[str]


def client_host(request: Request) -> str | None:
    return request.client.host if request.client else None


def is_loopback(request: Request) -> bool:
    """Whether the request came from this machine.

    ``ipaddress`` rather than a string comparison, because a dual-stack socket can
    report an IPv4 address mapped into IPv6 (``::ffff:127.0.0.1``).
    """
    host = client_host(request)
    if not host:
        return False
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return host == "localhost"


def require_loopback(request: Request) -> None:
    """FastAPI dependency: refuse an irreversible action from another machine.

    The message names the address to use, because a bare 403 on a button that looks
    ordinary is a puzzle rather than an instruction.
    """
    if not is_loopback(request):
        raise HTTPException(
            status_code=403,
            detail=(
                "This action can only be taken on the piano machine. "
                "Open http://localhost:8000 there and try again."
            ),
        )


def sequencer_available() -> bool:
    """Whether ALSA's sequencer is there.

    Checked two ways on purpose. ``/dev/snd/seq`` is the device a client opens, but
    it is absent in containers and sandboxes that do not populate ``/dev``, while
    the sequencer itself is running and its clients are listed in procfs. Trusting
    either signal avoids reporting a missing kernel module on a machine that has
    one, which is the wrong diagnosis in the most confusing possible way.
    """
    return SEQUENCER_PATH.exists() or SEQ_CLIENTS_PATH.exists()


def alsa_clients() -> list[str]:
    """Sequencer clients visible to ALSA, read from procfs.

    Reading ``/proc/asound/seq/clients`` needs no device open and no permission, so
    the server can report "the piano is attached" even when no browser is running.
    """
    try:
        lines = SEQ_CLIENTS_PATH.read_text(errors="replace").splitlines()
    except OSError:
        return []
    names: list[str] = []
    for line in lines:
        # Lines look like:  Client  24 : "CASIO USB-MIDI" [Kernel]
        if "Client" not in line or ":" not in line:
            continue
        _, _, rest = line.partition(":")
        name = rest.split('"')[1] if '"' in rest else rest.strip()
        if name and name not in names:
            names.append(name)
    return names


@router.get("/host", response_model=HostInfo)
def host_info(request: Request) -> HostInfo:
    return HostInfo(
        host=client_host(request),
        loopback=is_loopback(request),
        sequencer=sequencer_available(),
        clients=alsa_clients(),
    )
