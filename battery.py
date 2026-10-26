"""Daily battery optimisation and realised settlement, with explicit physical units.

Power is measured on the grid side in MW; state of charge is in MWh. Binary
operating modes extend the brief's linear programme to prohibit simultaneous
charging and discharging, including when prices are negative.
"""

from collections.abc import Mapping, Sequence
from typing import TypedDict

import numpy as np
import pandas as pd
from numpy.typing import NDArray
from scipy.optimize import Bounds, LinearConstraint, milp

FEASIBILITY_TOLERANCE = 1e-6
PERFECT_FORESIGHT_TOLERANCE_EUR = 1e-4
SOLVER_TIME_LIMIT_SECONDS = 30
SOLVER_RELATIVE_GAP = 1e-7


class DispatchSchedule(TypedDict):
    """One grid-side power decision per interval and its boundary energy states."""

    charge_mw: NDArray[np.float64]
    discharge_mw: NDArray[np.float64]
    energy_start_mwh: NDArray[np.float64]
    energy_end_mwh: NDArray[np.float64]
    duration_hours: NDArray[np.float64]


def validate_battery_settings(settings: Mapping[str, float]) -> None:
    """Reject nonphysical or nonfinite settings before invoking the optimiser."""
    required = ("power_mw", "capacity_mwh", "round_trip_efficiency", "throughput_cost_eur_mwh")
    values = {name: float(settings[name]) for name in required}
    values["import_fee_eur_mwh"] = float(settings.get("import_fee_eur_mwh", 0))
    if not all(np.isfinite(value) for value in values.values()):
        raise ValueError("Battery settings must be finite")
    if (
        values["power_mw"] <= 0
        or values["capacity_mwh"] <= 0
        or not 0 < values["round_trip_efficiency"] <= 1
        or values["throughput_cost_eur_mwh"] < 0
        or values["import_fee_eur_mwh"] < 0
    ):
        raise ValueError("Invalid battery settings")


def dispatch(
    prices: Sequence[float], settings: Mapping[str, float], duration_hours: float = 1.0
) -> DispatchSchedule:
    """Optimise one daily schedule using planning prices, with empty start/end.

    The solver minimises purchase costs minus sale revenue plus configured
    operating costs. Forecasts determine the decisions; actual prices are used
    separately by :func:`settle`, so future outcomes cannot enter planning.
    """
    planning_prices = np.asarray(prices, dtype=float)
    if (
        planning_prices.ndim != 1
        or planning_prices.size == 0
        or not np.isfinite(planning_prices).all()
    ):
        raise ValueError("Finite nonempty one-dimensional price vector required")
    validate_battery_settings(settings)
    if not np.isfinite(duration_hours) or duration_hours <= 0:
        raise ValueError("Interval duration must be finite and positive")

    interval_count = len(planning_prices)
    power_limit_mw = float(settings["power_mw"])
    capacity_mwh = float(settings["capacity_mwh"])
    one_way_efficiency = np.sqrt(float(settings["round_trip_efficiency"]))
    throughput_cost = float(settings["throughput_cost_eur_mwh"])
    import_fee = float(settings.get("import_fee_eur_mwh", 0))

    # Decision vector: [charge(n), discharge(n), energy(n+1), charging_mode(n)].
    # A mode of 1 permits charging; 0 permits discharging. Idle is always feasible.
    variable_count = 4 * interval_count + 1
    energy_offset = 2 * interval_count
    mode_offset = 3 * interval_count + 1
    charge_slice = slice(0, interval_count)
    discharge_slice = slice(interval_count, energy_offset)
    energy_slice = slice(energy_offset, mode_offset)

    objective = np.zeros(variable_count)
    objective[charge_slice] = (planning_prices + throughput_cost + import_fee) * duration_hours
    objective[discharge_slice] = (-planning_prices + throughput_cost) * duration_hours
    lower_bounds = np.zeros(variable_count)
    upper_bounds = np.r_[
        np.full(2 * interval_count, power_limit_mw),
        np.full(interval_count + 1, capacity_mwh),
        np.ones(interval_count),
    ]
    upper_bounds[energy_offset] = 0
    upper_bounds[energy_offset + interval_count] = 0

    # e[t+1] - e[t] - eta*c[t]*dt + d[t]*dt/eta = 0.
    energy_balance = np.zeros((interval_count, variable_count))
    operating_modes = np.zeros((2 * interval_count, variable_count))
    for interval in range(interval_count):
        energy_balance[interval, energy_offset + interval + 1] = 1
        energy_balance[interval, energy_offset + interval] = -1
        energy_balance[interval, interval] = -one_way_efficiency * duration_hours
        energy_balance[interval, interval_count + interval] = duration_hours / one_way_efficiency
        # c <= P*mode and d <= P*(1-mode).
        operating_modes[interval, interval] = 1
        operating_modes[interval, mode_offset + interval] = -power_limit_mw
        operating_modes[interval_count + interval, interval_count + interval] = 1
        operating_modes[interval_count + interval, mode_offset + interval] = power_limit_mw

    integrality = np.zeros(variable_count)
    integrality[mode_offset:] = 1
    constraints = [
        LinearConstraint(energy_balance, np.zeros(interval_count), np.zeros(interval_count)),
        LinearConstraint(
            operating_modes,
            np.full(2 * interval_count, -np.inf),
            np.r_[np.zeros(interval_count), np.full(interval_count, power_limit_mw)],
        ),
    ]
    solution = milp(
        objective,
        integrality=integrality,
        bounds=Bounds(lower_bounds, upper_bounds),
        constraints=constraints,
        options={"time_limit": SOLVER_TIME_LIMIT_SECONDS, "mip_rel_gap": SOLVER_RELATIVE_GAP},
    )
    if not solution.success:
        raise RuntimeError(
            f"Battery solver did not establish optimality (status {solution.status})"
        )

    decisions = solution.x
    charge_mw = np.maximum(decisions[charge_slice], 0)
    discharge_mw = np.maximum(decisions[discharge_slice], 0)
    energy_mwh = decisions[energy_slice]
    if (
        np.max(np.abs(energy_balance @ decisions)) > FEASIBILITY_TOLERANCE
        or np.max(charge_mw * discharge_mw) > FEASIBILITY_TOLERANCE
    ):
        raise RuntimeError("Battery feasibility check failed")
    return DispatchSchedule(
        charge_mw=charge_mw,
        discharge_mw=discharge_mw,
        energy_start_mwh=energy_mwh[:-1],
        energy_end_mwh=energy_mwh[1:],
        duration_hours=np.full(interval_count, duration_hours),
    )


def settle(
    schedule: DispatchSchedule, actual_prices: Sequence[float], settings: Mapping[str, float]
) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.float64]]:
    """Return interval gross revenue, operating costs and net revenue in EUR.

    Throughput cost applies to both grid-side charged and discharged MWh. This
    is a research operating margin, excluding unconfigured commercial costs.
    """
    validate_battery_settings(settings)
    actual_prices = np.asarray(actual_prices, dtype=float)
    charge_mw = schedule["charge_mw"]
    discharge_mw = schedule["discharge_mw"]
    duration_hours = schedule["duration_hours"]
    if (
        actual_prices.ndim != 1
        or len(actual_prices) != len(charge_mw)
        or not np.isfinite(actual_prices).all()
    ):
        raise ValueError("Actual prices must match schedule")
    gross_revenue = actual_prices * (discharge_mw - charge_mw) * duration_hours
    operating_costs = (
        float(settings["throughput_cost_eur_mwh"]) * (charge_mw + discharge_mw)
        + float(settings.get("import_fee_eur_mwh", 0)) * charge_mw
    ) * duration_hours
    return gross_revenue, operating_costs, gross_revenue - operating_costs


def value_forecasts(
    predictions: pd.DataFrame, settings: Mapping[str, float]
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Compare identical physical policies, settling every schedule at actual prices."""
    daily_values = []
    interval_schedules = []
    for delivery_day, daily_predictions in predictions.groupby("delivery_date_local", sort=True):
        daily_predictions = daily_predictions.sort_values("delivery_start_utc")
        if len(daily_predictions) != 24:
            raise ValueError("Initial daily policy requires a complete 24-hour local day")
        perfect_foresight_value = None
        for model_name in ("perfect_foresight", "lear", "lightgbm", "naive"):
            planning_prices = daily_predictions[
                "actual" if model_name == "perfect_foresight" else model_name
            ].to_numpy()
            schedule = dispatch(planning_prices, settings)
            gross_revenue, operating_costs, net_revenue = settle(
                schedule, daily_predictions.actual.to_numpy(), settings
            )
            total_net_revenue = float(net_revenue.sum())
            if model_name == "perfect_foresight":
                perfect_foresight_value = total_net_revenue
            if total_net_revenue > perfect_foresight_value + PERFECT_FORESIGHT_TOLERANCE_EUR:
                raise RuntimeError(
                    "Forecast dispatch exceeds perfect foresight: inconsistent objective/constraints"
                )
            daily_values.append(
                {
                    "delivery_date_local": delivery_day,
                    "model": model_name,
                    "gross_eur": float(gross_revenue.sum()),
                    "cost_eur": float(operating_costs.sum()),
                    "net_eur": total_net_revenue,
                    "capture_fraction": total_net_revenue / perfect_foresight_value
                    if perfect_foresight_value > 1e-6
                    else None,
                }
            )
            for interval, (_, row) in enumerate(daily_predictions.iterrows()):
                interval_schedules.append(
                    {
                        "delivery_start_utc": row.delivery_start_utc,
                        "delivery_date_local": delivery_day,
                        "model": model_name,
                        "actual_price": float(row.actual),
                        "planning_price": float(planning_prices[interval]),
                        **{name: float(values[interval]) for name, values in schedule.items()},
                        "net_eur": float(net_revenue[interval]),
                    }
                )
    return pd.DataFrame(daily_values), pd.DataFrame(interval_schedules)
