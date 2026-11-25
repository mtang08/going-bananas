# Set up private iPhone check-ins

The Mac hosts Going Bananas. The iPhone Home Screen app saves first-step ankle observations while the Mac sleeps. When you reopen it with the Mac awake, the app sends pending entries over your private Tailscale network. Entries stay on the iPhone until the app receives a matching save receipt.

## Start the Mac side

1. Install Tailscale on the Mac and iPhone. Sign in with the same user account on both devices and connect them. On the Mac, make the `tailscale` command available in Terminal. Use an ordinary user-owned device for both ends. The gateway checks the requesting user identity that Tailscale Serve supplies. Other devices signed into the same account also qualify. To limit access to just the phone, restrict the Mac's TCP port 8443 to the iPhone in your tailnet access policy. [Tailscale Serve identity and access](https://tailscale.com/docs/features/tailscale-serve)
2. Start the current real-mode Going Bananas API on its usual loopback port 8000 with the phone endpoint included. Follow the [local startup instructions](../README.md#run-on-this-mac) if it is stopped. The phone gateway reads its own static assets and needs no additional frontend build.
3. From the same release checkout, leave `make phone-access` running in a terminal. It derives the Mac's tailnet DNS name and owner from the local Tailscale client, binds only to `127.0.0.1:8765`, and prints your private HTTPS URL ending in `:8443/phone/`.
4. In a second terminal, run `tailscale serve status` and `tailscale funnel status` to check the current listeners. Reserve HTTPS port 8443 on this Mac for this feature. If another service uses it, preserve that configuration and resolve the port assignment first. Run the following once for this gateway, with MagicDNS and HTTPS certificates enabled on your tailnet. Tailscale will show a setup link if HTTPS needs enabling. [Tailscale Serve command](https://tailscale.com/docs/reference/tailscale-cli/serve)

```sh
tailscale serve --bg --https=8443 http://127.0.0.1:8765
tailscale serve status
```

The status should identify the listener as available within your tailnet and its target as port 8765. The gateway serves the phone assets and the morning check-in write route. Keep the dashboard and API on loopback. Use **Serve** for the private connection.

## Install on the iPhone

1. With the Mac awake, open the complete HTTPS URL printed by `make phone-access` in Safari on the iPhone. Keep the exact host, port, and trailing `/phone/`.
2. Open **Share → Add to Home Screen**, enable **Open as Web App** where shown, and tap **Add**. [Apple's Home Screen instructions](https://support.apple.com/guide/iphone/open-as-web-app-iphea86e5236/ios)
3. **Open the Home Screen icon once while connected and wait for “Ready offline.”** Do this inside the installed app, since its storage can be separate from the Safari tab. Use the icon for subsequent entries.
4. Record first-step pain, including on a rest day. Until you see **Synced**, that copy lives on your phone. Keep the Home Screen app and its website data in place until outstanding entries sync. To sync, reconnect Tailscale, wake the Mac, ensure the API and gateway are running, and reopen the icon.

## Verify, troubleshoot, or stop

To rehearse with synthetic records, use the [isolated demo API instructions](../README.md#verification) on port 18000. Start `python3 scripts/phone_gateway.py --demo` and run `tailscale serve --bg --https=8444 http://127.0.0.1:8766` on an unused tailnet listener. The demo URL has its own port and iPhone storage. Simulate the sleeping Mac by stopping the demo gateway, save a sample offline, close and reopen the icon, then restart the gateway and reopen the icon. Check that a single dated observation appears in the demo review after retry. Repeat with an explicit zero. Use the real URL only for actual observations.

- **Can't open the app for setup.** Check that both devices are connected to Tailscale, the Mac is awake, and the printed HTTPS URL matches the Serve listener in `tailscale serve status`. After a Mac restart, restart Going Bananas and `make phone-access`. If Tailscale asks you to reauthenticate a device, sign in again.
- **Access denied.** Check both devices' owner logins and the host and port in the installed URL. Serve identifies the signed-in user to the gateway. A tagged client device lacks this user header.
- **Entry stays on iPhone.** Check that the API on the Mac is running the same release and workspace. The real gateway expects real mode on 8000, and the demo gateway expects demo mode on 18000. Reopen the app. If delivery was interrupted after the Mac saved the entry, retrying with the same ID returns its receipt.
- **Remove access.** Sync outstanding entries, stop the gateway with Ctrl+C, then run `tailscale serve --bg --https=8443 http://127.0.0.1:8765 off`. For the demo listener use port 8444 and target port 8766. Verify with `tailscale serve status`. Entries already synced remain in the Mac database.
