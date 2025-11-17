# better_pid.py -- Adaptive PID management with automatic tracking
import logging

# Singleton instance to ensure only one BetterPID instance exists
_better_pid_instance = None


class BetterPID:
    def __init__(self, config):
        global _better_pid_instance

        # If instance already exists, just load the current section
        if _better_pid_instance is not None:
            logger = logging.getLogger(__name__)
            logger.debug(
                f"better_pid: Reusing existing instance for section '{config.get_name()}'"
            )
            _better_pid_instance._load_single_section(config)
            return

        # First instance - initialize everything
        _better_pid_instance = self
        self.printer = config.get_printer()
        self.config = config
        self.heater_profiles = {}
        self.tracked_heaters = {}
        self.processed_sections = set()  # Track which sections we've already processed
        self.logger = logging.getLogger(__name__)
        self.logger.info("better_pid: Module initialized")

        gcode = self.printer.lookup_object("gcode")
        gcode.register_command("BETTER_PID", self.cmd_BETTER_PID)
        gcode.register_command("BETTER_PID_AUTO", self.cmd_BETTER_PID_AUTO)
        gcode.register_command(
            "BETTER_PID_STATUS",
            self.cmd_BETTER_PID_STATUS,
            desc="Show current continuous PID status",
        )

        # Parse the current section
        self._load_single_section(config)
        self.logger.info(
            f"better_pid: Loaded {len(self.heater_profiles)} heater profile(s)"
        )
        # Prepare event tracking once printer objects are ready
        self.printer.register_event_handler("klippy:ready", self._on_ready)
        self.logger.info("better_pid: Registered klippy:ready event handler")

    # --------------------------------------------------
    # Load configuration profiles
    # --------------------------------------------------
    def _load_single_section(self, config):
        """Load a single configuration section."""
        name = config.get_name()
        tokens = name.split()

        # Skip the base [better_pid] section - it's just a placeholder
        if len(tokens) == 1 and name == "better_pid":
            return

        # Check if we've already processed this section
        if name in self.processed_sections:
            return
        self.processed_sections.add(name)

        # All other sections must have format: better_pid <heater> <profile>
        if len(tokens) < 3:
            raise config.error(
                f"Invalid section name '{name}', expected 'better_pid <heater> <profile>'"
            )
        _, heater, profile = tokens
        heater = heater.lower()
        profile = profile.lower()
        hdict = self.heater_profiles.setdefault(heater, {})

        # Process the section based on profile type
        section = config
        if profile == "continuous":
            # Collect all point data for piecewise linear interpolation
            points = []
            n = 1
            while True:
                temp_key = f"p{n}_temp"
                temp = section.get(temp_key, None)
                if temp is None:
                    # No more points found
                    break
                temp = section.getfloat(temp_key)
                point_data = {"temp": temp}
                for term in ["kp", "ki", "kd"]:
                    point_data[term] = section.getfloat(f"p{n}_{term}")
                points.append(point_data)
                n += 1

            if len(points) < 2:
                raise config.error(
                    f"[{name}] continuous profile requires at least 2 points, found {len(points)}"
                )

            # Sort points by temperature to ensure proper interpolation
            points.sort(key=lambda p: p["temp"])

            # Check for duplicate temperatures
            temps = [p["temp"] for p in points]
            if len(temps) != len(set(temps)):
                raise config.error(
                    f"[{name}] Duplicate temperatures found in continuous profile"
                )

            # Store points for piecewise linear interpolation
            hdict["continuous"] = {"points": points}
        else:
            hdict[profile] = {
                "kp": section.getfloat("pid_kp"),
                "ki": section.getfloat("pid_ki"),
                "kd": section.getfloat("pid_kd"),
            }

    # --------------------------------------------------
    # Once printer objects load, attach listeners
    # --------------------------------------------------
    def _on_ready(self):
        heaters = {
            hname: self.printer.lookup_object(hname, None)
            for hname in self.heater_profiles.keys()
        }
        for hname, obj in heaters.items():
            if obj is None:
                self.logger.warning(f"better_pid: Heater '{hname}' not found")
                continue
            if "continuous" in self.heater_profiles[hname]:
                # Check if this is an extruder (has a heater attribute) or a direct heater
                heater = getattr(obj, "heater", obj)
                if heater is None:
                    self.logger.warning(
                        f"better_pid: Object '{hname}' has no heater attribute"
                    )
                    continue
                self._wrap_heater_set_temp(hname, heater)

        # Wrap G-code commands once heaters are ready
        self._wrap_gcode_commands()

    def _wrap_heater_set_temp(self, hname, heater):
        """Intercept heater target changes."""
        orig_set = getattr(heater, "set_temp", None)
        if orig_set is None:
            self.logger.warning(f"better_pid: Heater '{hname}' has no set_temp method")
            return
        self.tracked_heaters[hname] = {"orig_set": orig_set, "heater": heater}

        def wrapped_set_temp(target, *args, **kwargs):
            result = orig_set(target, *args, **kwargs)
            # Apply continuous PID if valid target (target > 0)
            if target and target > 0:
                self._apply_continuous_if_exists(hname, target)
            return result

        heater.set_temp = wrapped_set_temp
        self.logger.info(f"better_pid: Wrapped set_temp for heater '{hname}'")

    def _wrap_gcode_commands(self):
        """Intercept G-code commands that set heater temperature.

        Note: This is optional - the set_temp method wrapping will catch
        all temperature changes. This is mainly for logging purposes.
        """
        self.logger.debug(
            "better_pid: G-code command wrapping skipped (using set_temp wrapping instead)"
        )

    # --------------------------------------------------
    # PID Computation Logic
    # --------------------------------------------------
    def _calc_continuous_pid(self, heater_name, target):
        """Calculate PID values using piecewise linear interpolation."""
        prof = self.heater_profiles[heater_name]["continuous"]
        points = prof["points"]

        # Initialize defaults so static analyzers know the variables are bound
        kp = points[0]["kp"]
        ki = points[0]["ki"]
        kd = points[0]["kd"]

        # Handle temperatures outside the range
        if target <= points[0]["temp"]:
            # Below first point - use first point values
            kp = points[0]["kp"]
            ki = points[0]["ki"]
            kd = points[0]["kd"]
        elif target >= points[-1]["temp"]:
            # Above last point - use last point values
            kp = points[-1]["kp"]
            ki = points[-1]["ki"]
            kd = points[-1]["kd"]
        else:
            # Find the two points to interpolate between
            for i in range(len(points) - 1):
                if points[i]["temp"] <= target <= points[i + 1]["temp"]:
                    t1, t2 = points[i]["temp"], points[i + 1]["temp"]
                    ratio = (target - t1) / (t2 - t1)

                    kp = points[i]["kp"] + ratio * (
                        points[i + 1]["kp"] - points[i]["kp"]
                    )
                    ki = points[i]["ki"] + ratio * (
                        points[i + 1]["ki"] - points[i]["ki"]
                    )
                    kd = points[i]["kd"] + ratio * (
                        points[i + 1]["kd"] - points[i]["kd"]
                    )
                    break

        return kp, ki, kd

    def _get_heater_object(self, heater_name):
        """Get the actual heater object, handling extruders that have a heater attribute."""
        obj = self.printer.lookup_object(heater_name, None)
        if obj is None:
            return None
        # Check if this is an extruder (has a heater attribute) or a direct heater
        heater = getattr(obj, "heater", obj)
        return heater

    def _set_pid_values(self, heater, kp, ki, kd):
        """Set PID values on a heater's control object."""
        if not hasattr(heater, "control"):
            self.logger.warning("better_pid: Heater has no control object")
            return False

        control = heater.control
        if not hasattr(control, "Kp"):
            self.logger.warning("better_pid: Heater does not use PID control")
            return False

        # PID values in Klipper are stored divided by PID_PARAM_BASE (255.0)
        from extras.heaters import PID_PARAM_BASE

        control.Kp = kp / PID_PARAM_BASE
        control.Ki = ki / PID_PARAM_BASE
        control.Kd = kd / PID_PARAM_BASE

        if control.Ki:
            control.temp_integ_max = heater.get_max_power() / control.Ki
        else:
            control.temp_integ_max = 0.0

        return True

    def _apply_continuous_if_exists(self, heater_name, target):
        if heater_name not in self.heater_profiles:
            return
        prof = self.heater_profiles[heater_name].get("continuous")
        if not prof:
            return
        heater = self._get_heater_object(heater_name)
        if heater is None:
            return
        kp, ki, kd = self._calc_continuous_pid(heater_name, target)
        if self._set_pid_values(heater, kp, ki, kd):
            msg = (
                f"better_pid: Auto-applied continuous PID to '{heater_name}' "
                f"at target {target:.1f}°C: Kp={kp:.3f} Ki={ki:.3f} Kd={kd:.3f}"
            )
            self.logger.info(msg)
            try:
                gcode = self.printer.lookup_object("gcode")
                gcode.respond_raw(f"// {msg}\n")
            except Exception:
                pass  # If gcode object not available, just log to file

    # --------------------------------------------------
    # G-code Commands
    # --------------------------------------------------
    def cmd_BETTER_PID(self, gcmd):
        heater_name = gcmd.get("HEATER").lower()
        profile = gcmd.get("PROFILE").lower()
        profs = self.heater_profiles.get(heater_name, {})
        vals = profs.get(profile)
        if vals is None:
            raise gcmd.error(
                f"No profile '{profile}' for heater '{heater_name}'"
            )
        heater = self._get_heater_object(heater_name)
        if heater is None:
            raise gcmd.error(f"Heater '{heater_name}' not found")
        kp, ki, kd = vals["kp"], vals["ki"], vals["kd"]
        if not self._set_pid_values(heater, kp, ki, kd):
            raise gcmd.error(f"Heater '{heater_name}' does not use PID control")
        self.logger.info(
            f"better_pid: Applied profile '{profile}' to '{heater_name}': "
            f"Kp={kp:.3f} Ki={ki:.3f} Kd={kd:.3f}"
        )
        gcmd.respond_info(
            f"Applied PID profile '{profile}' to '{heater_name}': "
            f"Kp={kp:.3f} Ki={ki:.3f} Kd={kd:.3f}"
        )

    def cmd_BETTER_PID_AUTO(self, gcmd):
        heater_name = gcmd.get("HEATER").lower()
        target = gcmd.get_float("TARGET")
        heater = self._get_heater_object(heater_name)
        if heater is None:
            raise gcmd.error(f"Heater '{heater_name}' not found")
        kp, ki, kd = self._calc_continuous_pid(heater_name, target)
        if not self._set_pid_values(heater, kp, ki, kd):
            raise gcmd.error(f"Heater '{heater_name}' does not use PID control")
        self.logger.info(
            f"better_pid: Applied AUTO PID to '{heater_name}' at {target:.1f}°C: "
            f"Kp={kp:.3f} Ki={ki:.3f} Kd={kd:.3f}"
        )
        gcmd.respond_info(
            f"Applied AUTO PID for '{heater_name}' at {target:.1f}C:\n"
            f" Kp={kp:.3f} Ki={ki:.3f} Kd={kd:.3f}"
        )

    def cmd_BETTER_PID_STATUS(self, gcmd):
        lines = []
        for hname, hdata in self.heater_profiles.items():
            prof = hdata.get("continuous")
            if not prof:
                continue
            lines.append(f"{hname}: continuous PID active.")
        if not lines:
            gcmd.respond_info("No continuous PID entries active.")
        else:
            gcmd.respond_info("\n".join(lines))


def load_config_prefix(config):
    return BetterPID(config)

