# zwave-alarm-client

Async Python client (aiohttp) for the REST API of the [Z-Wave Alarm service](https://github.com/judeibe/zwave_alarm). Used by the [Home Assistant integration](https://github.com/judeibe/ha-zwave-alarm); contains no Home Assistant code.

```python
import aiohttp
from zwave_alarm_client import async_get_panel_state, InvalidAuth, CannotConnect

async with aiohttp.ClientSession() as session:
    panel = await async_get_panel_state(session, "192.168.1.50", 3000, token)
```

Errors: `CannotConnect`, `InvalidAuth` (401), `AccountLocked` (423), `CommandRejected` (409).

## Development

```sh
python -m venv .venv && . .venv/bin/activate
pip install -e '.[test]'
pytest
```

Commits follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/): `fix` releases a patch, `feat` a minor, `BREAKING CHANGE`/`!` a major. Releases are tagged and published to PyPI from `main`.
