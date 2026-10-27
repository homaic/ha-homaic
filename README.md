# Homaic for Home Assistant

Send your Home Assistant's devices to your [Homaic](https://homaic.io) house. Each one arrives with its room and floor, in a list you look over before anything is brought in.

## Install

1. In Home Assistant: Settings, Marketplace, Add from link, then `homaic/ha-homaic`.
   On a Home Assistant older than 2026.11, use HACS: Custom repositories, `homaic/ha-homaic`, type Integration.
2. Install Homaic, then restart Home Assistant.
3. Settings, Devices & services, Add integration, Homaic.
4. Sign in with Homaic.

The first send happens on its own. After that, press **Send devices to Homaic**, or call `homaic.send_devices`.

## What is sent

For each device: Home Assistant's own number for it, its name, the name you gave it, maker, model, model id, serial number, software and hardware versions, its area, the device it connects through, which integrations it belongs to, and whether Home Assistant lists it as a service or as turned off. For each device, the types of its main entities (light, lock, sensor and so on). For each area: Home Assistant's own number for it, its name and its floor. For each floor: its number, name and level. For each integration a device belongs to: Home Assistant's number for it and its kind, such as `zha` or `hue`. And the version of Home Assistant.

Never sent: entity ids or names, states, MAC addresses or other connections, the identifiers each integration gives a device, configuration URLs, integration titles, or any token or password.

Homaic takes up to 2,000 devices in one send.

## Sign out

Remove the integration in Home Assistant, and disconnect Home Assistant in Homaic under Settings, Your AI.

## License

Apache-2.0
