# Comic Book Converter — How to Use

No terminal or coding needed. Just double-click the numbered files in order.

---

## First time only

1. Double-click **`0 - First Time Setup`**
   - This installs everything the converter needs
   - It may ask for your Mac password (to install some tools)
   - You only need to do this once

---

## Every time you want to convert comics

### Step 1: Put your comics in the input folder

- Double-click **`1 - Open Input Folder`**
- A Finder window opens — drag your `.cbr`, `.cbz`, or `.cb7` files into it
- You can put as many files as you want

### Step 2: Pick a converter and double-click it

| File | What it does |
|------|-------------|
| **`2 - Convert All for Kindle`** | Makes EPUBs for Kindle Paperwhite. Full page view — use Kindle's built-in panel zoom (Aa menu → Panel View) |
| **`3 - Convert All for XTe Ink`** | Makes EPUBs for XTe Ink X4 (CrossPoint reader). Splits pages into panels, groups related panels together. Rotates wide panels with an arrow showing which way to hold the device |
| **`4 - Convert All for Both Devices`** | Runs both — gives you two EPUBs per comic |

- A black Terminal window will open and show progress
- Wait until it says **"DONE!"**
- The output folder opens automatically when it finishes

### Step 3: Grab your EPUBs

- The output folder opens automatically
- If you missed it, double-click **`6 - Open Output Folder`**
- Transfer the `.epub` files to your device

---

## Optional: Check orientation

Double-click **`5 - Analyze Orientation`** to see whether each comic is mostly landscape (sideways) or portrait (upright). This is just informational — it helps you know how the book will look on your device.

---

## What file formats work?

| Format | Extension | Works? |
|--------|-----------|--------|
| Comic Book ZIP | `.cbz` | Yes |
| Comic Book RAR | `.cbr` | Yes |
| Comic Book 7-Zip | `.cb7` | Yes |
| PDF | `.pdf` | Not yet |

---

## Manga vs Western comics

The converter automatically detects if a comic is manga (reads right-to-left) or western (reads left-to-right). It checks for Japanese metadata inside the file. You don't need to do anything — it just works.

---

## Troubleshooting

**"No comic files found in input/"**
→ You forgot to put files in the input folder. Double-click `1 - Open Input Folder` and drop your comics in.

**Terminal shows an error about Python or venv**
→ Run `0 - First Time Setup` again.

**The output EPUB looks wrong or has missing panels**
→ Some artistic comics (like Sandman) have unusual page layouts that are harder to split. The converter works best on standard panel grid layouts.

**Kindle doesn't show panel zoom**
→ Open the book → tap the screen → tap "Aa" → scroll down → enable "Panel View". This only works with the Kindle-format EPUBs (converter #2).
