# Checkera — Setup

Welcome! Checkera is a floating todo widget that lives on your desktop. It
syncs with Google Calendar, sends reminders, and stays out of your way during
screen sharing.

This document walks through one-time setup. Three minutes total.

## 1. Run it

1. Unzip the folder anywhere — Desktop or Documents both work fine.
2. Open the folder and **double-click `Checkera.exe`**.
3. The widget appears on the right edge of your screen.

That's it for "just using it." If you don't care about Google Calendar sync,
you're done — close this file and start adding tasks.

## 2. Connect Google Calendar (optional)

Letting Checkera talk to your calendar means:

- Tasks with due dates show up as events on your Google Calendar
- Your phone's Google Calendar app pings you at reminder time
- Completing a task in Checkera marks it done on the calendar
- You can invite people to a task — they get a calendar invite by email

### Steps

1. In the widget, click the blue **Connect Google Calendar** banner at the top
2. A browser tab opens
3. Sign in with your Google account
4. **You'll see a warning**: *"Google hasn't verified this app"*
   - Click **Advanced** (small link, bottom left)
   - Click **Go to Checkera (unsafe)**
   - This is normal — Checkera is a personal project, not a publicly verified
     Google app. Your data goes to your own calendar; we don't store anything
     on a server.
5. Click **Allow** to grant Calendar access
6. The browser shows "Authentication complete" — close that tab
7. Back in the widget, the blue banner disappears

> **Note**: if you see "Access blocked: this app's request is invalid", it
> means your email isn't on Rashi's authorized testers list. Ask her to add
> you, then try again.

## 3. Auto-start with Windows (optional)

The widget doesn't auto-start by default. To turn it on:

1. Click the gear icon in the top-right of the widget
2. Toggle **"Start Checkera when your computer starts"** on
3. Next reboot, the widget will appear automatically

Toggle it off the same way to stop auto-starting.

## Hotkeys

| Shortcut | What it does |
|---|---|
| `Ctrl + Shift + N` | Quick-add a task from anywhere (no need to focus the widget) |
| `Ctrl + Shift + T` | Bring the widget to front |
| `Ctrl + Shift + H` | Hide the widget instantly (useful when sharing screen) |
| `/` (when widget focused) | Jump cursor to search |

## Where your data lives

All your data stays on your computer, in the same folder as `Checkera.exe`:

| File | What's in it |
|---|---|
| `data\todos.json` | Your tasks, subtasks, notes |
| `token.json` | Your Google Calendar sign-in (created on first connect) |
| `cache\` | Cached news headlines + calendar event metadata |

Back up the folder to back up everything. Move the folder to move your install.
Nothing is stored on a server.

## Troubleshooting

**The widget doesn't open.** Try right-clicking `Checkera.exe` →
**Properties** → **Unblock** at the bottom of the General tab (Windows
sometimes flags downloaded apps). Then try again.

**Screen-capture hiding doesn't work.** Requires Windows 10 version 2004 or
newer. Update Windows.

**Notifications don't show up.** Open Settings → System → Notifications, make
sure they're enabled for Checkera. Also disable Focus Assist if it's on.

**Calendar events aren't appearing.** Check the terminal output (run from a
PowerShell window: `.\Checkera.exe`) for any line starting with `[gcal]`.

**Anything else.** Message Rashi.
