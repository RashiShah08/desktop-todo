# Checkera for Mac — Setup

Welcome! Checkera is a floating to-do widget that lives on your desktop. It
syncs with Google Calendar, sends reminders, and hides itself from screen
sharing.

## 1. Install

1. Unzip the file you were sent — you'll get **`Checkera.app`**
2. Drag `Checkera.app` into your **Applications** folder
3. **Right-click** `Checkera.app` → **Open**
   - A dialog appears: *"macOS cannot verify the developer of Checkera"*
   - Click **Open**
   - This is one-time. Future launches: just double-click.

> If the dialog only has a "Cancel" button and no "Open" button,
> open **System Settings → Privacy & Security**, scroll to the bottom, and
> click **"Open Anyway"** next to the Checkera message. Then relaunch.

## 2. Grant permissions (one-time)

The first time Checkera tries to register global hotkeys, macOS will prompt:

> **Checkera would like to monitor input from your keyboard.**

This is for `Ctrl+Shift+N` (quick-add anywhere) and `Ctrl+Shift+H` (hide for
screen sharing). Click **Open System Settings**, find Checkera in the
**Input Monitoring** list, and toggle it on. Restart Checkera once.

You may also see a Notifications prompt — accept that so reminders work.

## 3. Connect Google Calendar (optional)

1. Click the blue **Connect Google Calendar** banner in the widget
2. Browser tab opens → sign in with your Google account
3. **You'll see**: *"Google hasn't verified this app"* → click **Advanced**
   → **Go to Checkera (unsafe)** → **Allow**
4. Browser shows "Authentication complete" — close that tab
5. Back in the widget, the blue banner disappears

> If you see "Access blocked", your email isn't on the authorized testers
> list yet. Ask Rashi to add you.

## 4. Auto-start at login (optional)

The widget doesn't auto-start by default. To turn it on:

1. Click the gear icon in the top-right of the widget
2. Toggle **"Start Checkera when your computer starts"** on
3. Next login, the widget will appear automatically

Toggle it off the same way to stop auto-starting.

## Hotkeys

| Shortcut | What it does |
|---|---|
| `Ctrl + Shift + N` | Quick-add a task from anywhere |
| `Ctrl + Shift + T` | Bring the widget to front |
| `Ctrl + Shift + H` | Hide the widget instantly (screen-sharing) |
| `/` (in widget) | Focus the search bar |

## Where your data lives

Inside the .app bundle's data folder — Checkera writes here, you back this
up to back up everything:

```
~/Library/Application Support/Checkera/data/todos.json
~/Library/Application Support/Checkera/token.json
~/Library/Application Support/Checkera/cache/
```

Nothing is stored on any server. Everything is local + (optionally) your
own Google Calendar.

## Troubleshooting

**Widget won't open / no window appears**
Check that it's not hidden behind other windows. Press `Ctrl+Shift+T` to
bring it forward. If still nothing, open **Terminal** and run:
`/Applications/Checkera.app/Contents/MacOS/Checkera`
to see any error messages.

**Hotkeys don't work**
Make sure Checkera is in **System Settings → Privacy & Security → Input
Monitoring** and the toggle is on.

**Notifications don't show up**
**System Settings → Notifications → Checkera** — turn them on. Also turn
off Focus / Do Not Disturb if it's active.

**Screen-share hiding doesn't work**
Requires macOS 10.15 or newer (you almost certainly have this).

**Anything else** — message Rashi.
