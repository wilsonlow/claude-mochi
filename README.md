# Claude Mochi Usage Display

A Raspberry Pi 4 desk companion with animated "mochi" eyes on a 0.96" 128x64 I2C OLED (SSD1306). The eyes react to your Claude Pro/Max plan usage, and a stats page shows your **Current session** and **This week** percentages with reset times.

> **Warning:** this project reads usage from an **unofficial, undocumented endpoint**. It may stop working at any time. It uses the login token Claude Code stores in `~/.claude/.credentials.json`; anyone with that file can use your Claude account. Never commit it, and don't run this on a shared machine.

## Hardware

| OLED pin | Raspberry Pi pin |
| --- | --- |
| VCC | Pin 1 (3.3V) |
| GND | Pin 6 (GND) |
| SDA | Pin 3 (GPIO2) |
| SCL | Pin 5 (GPIO3) |

## Quick start

```bash
# 1. Enable I2C: sudo raspi-config -> Interface Options -> I2C -> Yes, then reboot
sudo apt install -y i2c-tools python3-venv git
i2cdetect -y 1                 # should show 3c (or 3d)

# 2. Get the code
git clone https://github.com/wilsonlow/claude-mochi.git ~/mochi
cd ~/mochi
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt

# 3. Install Claude Code and log in with your Pro account
curl -fsSL https://claude.ai/install.sh | bash
claude                         # log in, then exit

# 4. Test and run
python claude_mochi_pro_v2.py --test      # raw usage JSON
python claude_mochi_pro_v2.py --preview   # cycle through all expressions
python claude_mochi_pro_v2.py             # run the display
```

Set your timezone so reset times are correct, e.g. `sudo timedatectl set-timezone Asia/Kuala_Lumpur`.

## Autostart

```bash
cp mochi.env.example mochi.env
sudo cp mochi.service /etc/systemd/system/   # edit the username first
sudo systemctl daemon-reload
sudo systemctl enable --now mochi
```

## Expressions

| Expression | Shown when |
| --- | --- |
| Sleepy | No data or login expired |
| Love | Session just reset (30 s) |
| Dizzy | Session at 100% |
| Sleeping | Night hours (default 23:00-07:00) |
| Panic | Session 95-99% |
| Stressed | Session 80-94% |
| Worried | Weekly usage 80%+ |
| Normal | Session 50-79% |
| Happy | Session under 50% |
| Wink, Curious, Squint, Surprised | Random idle quirks |

## Settings (`mochi.env`)

| Setting | Default | Effect |
| --- | --- | --- |
| `MOCHI_I2C_ADDR` | `0x3C` | OLED address |
| `MOCHI_NIGHT` | `23-7` | Sleeping hours, or `off` |
| `MOCHI_FORCE` | empty | Lock one expression |
| `MOCHI_SOURCE` | `pro` | `demo` for fake data |

## Troubleshooting

- **Login expired: run claude** - run `claude` on the Pi briefly to refresh the token.
- **Blank screen** - check wiring and the I2C address with `i2cdetect -y 1`.
- **Live log** - `journalctl -u mochi -f`.

## License

MIT
