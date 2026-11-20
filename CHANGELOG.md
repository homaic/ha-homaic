# Changelog

## 0.2.1

- Stays signed in to Homaic in a quiet house: the sign-in is renewed once a day. Homaic ends a Home Assistant connection only after 30 days unused, or on Disconnect.

## 0.2.0

- A battery low, a filter due, or water found becomes a job on that thing in Homaic. Home Assistant sends the device's number, which of the three, the percent and when; nothing else.

## 0.1.0

- Sign in with Homaic.
- Send devices to Homaic: a button and the `homaic.send_devices` action. The first send happens on its own.
