# Changelog

## 0.3.0

- A water leak is no longer sent. Home Assistant stays the leak alarm, as it is for smoke and carbon monoxide. A battery low or a filter due still becomes a job, and the job closes itself when the reading is back.

## 0.2.0

- A battery low, a filter due, or water found becomes a job on that thing in Homaic. Home Assistant sends the device's number, which of the three, the percent and when; nothing else.

## 0.1.0

- Sign in with Homaic.
- Send devices to Homaic: a button and the `homaic.send_devices` action. The first send happens on its own.
