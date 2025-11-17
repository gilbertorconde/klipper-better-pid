# klipper better PID

Why? I print about as much PLA as ABS, and every time I PID-tuned my hotend for one, the other got a bit less accurate. For a while I kept multiple PID sections for different temps, but constantly commenting/uncommenting and restarting firmware just to switch materials was a pain. So I built klipper-better-pid to avoid restarts when changing materials — and figured I’d share it in case anyone else is running into the same thing.

Smarter PID control for Klipper. Define as many temperature/PID points as you like, and klipper-better-pid will smoothly interpolate between them every time the heater target changes. No more “close enough” tuning—use the data you already have and let the module do the math.

## ✨ Core Features

| Feature                     | Details                                                                     |
| --------------------------- | --------------------------------------------------------------------------- |
| **Continuous PID profiles** | Piecewise linear interpolation across arbitrary `(temp, Kp, Ki, Kd)` points |
| **Static profiles**         | Named PID presets (`pla`, `abs`, …) you can apply on demand                 |
| **Automated tracking**      | Hooks into `M104`, `M140`, `SET_HEATER_TEMPERATURE`, etc., automatically    |
| **Console visibility**      | Each PID update is echoed to the Klipper console for easy debugging         |

## 🚀 Installation

```bash
cd ~
git clone https://github.com/gilbertorconde/klipper-better-pid.git
cd ~/klipper-better-pid
./install.sh                # add --copy or a custom Klipper path if needed
```

<p>
During installation you’ll be asked if you want to add a Moonraker auto-update entry. If you say yes, updates can be triggered from your web UI; uninstalling removes the entry automatically.
</p>

## ⚙️ Configuration

### Continuous (temperature-based) profiles

Provide at least two calibration points using comma-separated arrays. The points can be in any order—klipper-better-pid sorts them and interpolates in between. Outside the defined range it clamps to the nearest point (no wild extrapolation).

```ini
[better_pid extruder continuous]
temps: 90, 150, 200, 250, 270
kps: 15.452, 20.550, 20.539, 25.134, 25.088
kis: 2.146, 5.269, 5.267, 6.445, 6.195
kds: 27.813, 20.036, 20.026, 24.505, 25.401
```

All four arrays (`temps`, `kps`, `kis`, `kds`) must have the same length. Add as many values as you need—more points mean a smoother curve.

### Static PID profiles

Static presets are great for quick “apply-and-go” swaps:

```ini
[better_pid extruder pla]
pid_kp: 10.0
pid_ki: 1.0
pid_kd: 50.0

[better_pid extruder abs]
pid_kp: 12.0
pid_ki: 1.2
pid_kd: 55.0
```

### Considerations

You can mix static and continuous profiles for the same heater.

You dont have to use the G-code commands, the profiles are applyed automatically
when a heater has configured profiles and a call to start heating is made.

You have to keep the heater section with the PID values, but those will be ignored
if a heater has profiles from klipper-better-pid:

```ini
[extruder] # this will be ignored by the better_pid plugin if [better_pid extruder ...]
control: pid
pid_kp: 18.391617
pid_ki: 4.8045600
pid_kd: 19.2187650
```

## 🧾 G-code commands

| Command                                       | Description                                                  |
| --------------------------------------------- | ------------------------------------------------------------ |
| `BETTER_PID HEATER=<name> PROFILE=<name>`     | Apply a static preset                                        |
| `BETTER_PID_AUTO HEATER=<name> TARGET=<temp>` | Force a continuous PID calculation at a specific temperature |
| `BETTER_PID_STATUS`                           | List heaters currently using a continuous profile            |

Examples:

```
BETTER_PID HEATER=extruder PROFILE=pla
BETTER_PID_AUTO HEATER=extruder TARGET=220
BETTER_PID_STATUS
```

Every continuous update is logged to the console, e.g.

```
// better_pid: Auto-applied continuous PID to 'extruder' at target 220.0°C: Kp=20.125 Ki=5.320 Kd=21.004
```

## 📚 How it works

1. On `klippy:ready`, the module wraps each configured heater’s `set_temp`.
2. Whenever a new target is set, it looks up your profile, interpolates the PID values, and writes them into the heater’s controller.
3. Static profiles remain available for manual overrides via G-code.

No approximations beyond your own data and no sudden PID jumps—just smooth transitions across the temperatures you care about.

## 🔁 Updating & 🗑 Uninstalling

### Update

```bash
cd ~/klipper-better-pid
git pull
./install.sh
```

If you enabled the Moonraker entry, you can also update via the web UI.

### Uninstall

```bash
cd ~/klipper-better-pid
./install.sh --uninstall
```

The script removes the Klipper files and cleans up the Moonraker auto-update entry automatically.

## 📜 License

klipper-better-pid is released under the GNU GPL v3. See `LICENSE` for details.
