"""Progress bar components for Claude Monitor.

Provides token usage, time progress, and model usage progress bars.
"""

from __future__ import annotations

import math
from abc import ABC, abstractmethod
from typing import Any, Final, Protocol, TypedDict

from claude_monitor.utils.time_utils import percentage


# Type definitions for progress bar components
class ModelStatsDict(TypedDict, total=False):
    """Type definition for model statistics dictionary."""

    input_tokens: int
    output_tokens: int
    total_tokens: int
    cost: float


class ProgressBarStyleConfig(TypedDict, total=False):
    """Configuration for progress bar styling."""

    filled_char: str
    empty_char: str
    filled_style: str | None
    empty_style: str | None


class ThresholdConfig(TypedDict):
    """Configuration for color thresholds."""

    threshold: float
    style: str


class ProgressBarRenderer(Protocol):
    """Protocol for progress bar rendering."""

    def render(self, *args: Any, **kwargs: Any) -> str:
        """Render the progress bar."""
        ...


class BaseProgressBar(ABC):
    """Abstract base class for progress bar components."""

    # Type constants for validation
    MIN_WIDTH: Final[int] = 10
    MAX_WIDTH: Final[int] = 200
    DEFAULT_WIDTH: Final[int] = 50

    # Default styling constants
    DEFAULT_FILLED_CHAR: Final[str] = "█"
    DEFAULT_EMPTY_CHAR: Final[str] = "░"
    DEFAULT_MAX_PERCENTAGE: Final[float] = 100.0

    def __init__(self, width: int = 50) -> None:
        """Initialize base progress bar.

        Args:
            width: Width of the progress bar in characters
        """
        self.width: int = width
        self._validate_width()

    def _validate_width(self) -> None:
        """Validate width parameter."""
        if self.width < self.MIN_WIDTH:
            raise ValueError(
                f"Progress bar width must be at least {self.MIN_WIDTH} characters"
            )
        if self.width > self.MAX_WIDTH:
            raise ValueError(
                f"Progress bar width must not exceed {self.MAX_WIDTH} characters"
            )

    def _calculate_filled_segments(
        self, percentage: float, max_value: float = 100.0
    ) -> int:
        """Calculate number of filled segments based on percentage.

        Args:
            percentage: Current percentage value
            max_value: Maximum percentage value (default 100)

        Returns:
            Number of filled segments
        """
        bounded_percentage: float = max(0, min(percentage, max_value))
        return int(self.width * bounded_percentage / max_value)

    def _render_bar(
        self,
        filled: int,
        filled_char: str = "█",
        empty_char: str = "░",
        filled_style: str | None = None,
        empty_style: str | None = None,
    ) -> str:
        """Render the actual progress bar.

        Args:
            filled: Number of filled segments
            filled_char: Character for filled segments
            empty_char: Character for empty segments
            filled_style: Optional style tag for filled segments
            empty_style: Optional style tag for empty segments

        Returns:
            Formatted bar string
        """
        filled_bar: str = filled_char * filled
        empty_bar: str = empty_char * (self.width - filled)

        if filled_style:
            filled_bar = f"[{filled_style}]{filled_bar}[/]"
        if empty_style:
            empty_bar = f"[{empty_style}]{empty_bar}[/]"

        return f"{filled_bar}{empty_bar}"

    def _format_percentage(self, percentage: float, precision: int = 1) -> str:
        """Format percentage value for display.

        Args:
            percentage: Percentage value to format
            precision: Number of decimal places

        Returns:
            Formatted percentage string
        """
        return f"{percentage:.{precision}f}%"

    def _get_color_style_by_threshold(
        self, value: float, thresholds: list[tuple[float, str]]
    ) -> str:
        """Get color style based on value thresholds.

        Args:
            value: Current value to check
            thresholds: List of (threshold, style) tuples in descending order

        Returns:
            Style string for the current value
        """
        for threshold, style in thresholds:
            if value >= threshold:
                return style
        return thresholds[-1][1] if thresholds else ""

    @abstractmethod
    def render(self, *args, **kwargs) -> str:
        """Render the progress bar.

        This method must be implemented by subclasses.

        Returns:
            Formatted progress bar string
        """


class TokenProgressBar(BaseProgressBar):
    """Token usage progress bar component."""

    # Color threshold constants
    HIGH_USAGE_THRESHOLD: Final[float] = 90.0
    MEDIUM_USAGE_THRESHOLD: Final[float] = 50.0
    LOW_USAGE_THRESHOLD: Final[float] = 0.0

    # Style constants
    HIGH_USAGE_STYLE: Final[str] = "cost.high"
    MEDIUM_USAGE_STYLE: Final[str] = "cost.medium"
    LOW_USAGE_STYLE: Final[str] = "cost.low"
    BORDER_STYLE: Final[str] = "table.border"

    # Icon constants
    HIGH_USAGE_ICON: Final[str] = "🔴"
    MEDIUM_USAGE_ICON: Final[str] = "🟡"
    LOW_USAGE_ICON: Final[str] = "🟢"

    def render(self, percentage: float) -> str:
        """Render token usage progress bar.

        Args:
            percentage: Usage percentage (can be > 100)

        Returns:
            Formatted progress bar string
        """
        filled: int = self._calculate_filled_segments(min(percentage, 100.0))

        color_thresholds: list[tuple[float, str]] = [
            (self.HIGH_USAGE_THRESHOLD, self.HIGH_USAGE_STYLE),
            (self.MEDIUM_USAGE_THRESHOLD, self.MEDIUM_USAGE_STYLE),
            (self.LOW_USAGE_THRESHOLD, self.LOW_USAGE_STYLE),
        ]

        filled_style: str = self._get_color_style_by_threshold(
            percentage, color_thresholds
        )
        bar: str = self._render_bar(
            filled,
            filled_style=filled_style,
            empty_style=self.BORDER_STYLE
            if percentage < self.HIGH_USAGE_THRESHOLD
            else self.MEDIUM_USAGE_STYLE,
        )

        if percentage >= self.HIGH_USAGE_THRESHOLD:
            icon: str = self.HIGH_USAGE_ICON
        elif percentage >= self.MEDIUM_USAGE_THRESHOLD:
            icon = self.MEDIUM_USAGE_ICON
        else:
            icon = self.LOW_USAGE_ICON

        percentage_str: str = self._format_percentage(percentage)
        return f"{icon} [{bar}] {percentage_str}"


class TimeProgressBar(BaseProgressBar):
    """Time progress bar component for session duration."""

    def render(self, elapsed_minutes: float, total_minutes: float) -> str:
        """Render time progress bar.

        Args:
            elapsed_minutes: Minutes elapsed in session
            total_minutes: Total session duration in minutes

        Returns:
            Formatted time progress bar string
        """
        from claude_monitor.utils.time_utils import format_time

        if total_minutes <= 0:
            progress_percentage = 0
        else:
            progress_percentage = min(100, percentage(elapsed_minutes, total_minutes))

        filled = self._calculate_filled_segments(progress_percentage)
        bar = self._render_bar(
            filled, filled_style="progress.bar", empty_style="table.border"
        )

        remaining_time = format_time(max(0, total_minutes - elapsed_minutes))
        return f"⏰ [{bar}] {remaining_time}"


class ModelUsageBar(BaseProgressBar):
    """Model usage progress bar showing Sonnet vs Opus distribution."""

    def render(self, per_model_stats: dict[str, Any]) -> str:
        """Render model usage progress bar.

        Args:
            per_model_stats: Dictionary of model statistics

        Returns:
            Formatted model usage bar string
        """
        if not per_model_stats:
            empty_bar = self._render_bar(0, empty_style="table.border")
            return f"🤖 [{empty_bar}] No model data"

        model_names = list(per_model_stats.keys())
        if not model_names:
            empty_bar = self._render_bar(0, empty_style="table.border")
            return f"🤖 [{empty_bar}] Empty model stats"

        buckets: dict[str, int] = {"sonnet": 0, "opus": 0, "haiku": 0, "other": 0}
        # style and label per bucket
        bucket_style = {
            "sonnet": "info",
            "opus": "warning",
            "haiku": "success",
            "other": "dim",
        }

        for model_name, stats in per_model_stats.items():
            model_tokens = stats.get("input_tokens", 0) + stats.get("output_tokens", 0)
            lower = model_name.lower()
            if "sonnet" in lower:
                buckets["sonnet"] += model_tokens
            elif "opus" in lower:
                buckets["opus"] += model_tokens
            elif "haiku" in lower:
                buckets["haiku"] += model_tokens
            else:
                buckets["other"] += model_tokens

        total_tokens = sum(buckets.values())
        if total_tokens == 0:
            empty_bar = self._render_bar(0, empty_style="table.border")
            return f"🤖 [{empty_bar}] No tokens used"

        # Calculate filled width per bucket, distribute any rounding remainder to largest
        filled: dict[str, int] = {
            k: int(self.width * v / total_tokens) for k, v in buckets.items()
        }
        remainder = self.width - sum(filled.values())
        if remainder:
            largest = max(buckets, key=lambda k: buckets[k])
            filled[largest] += remainder

        bar_segments = []
        for key in ("sonnet", "opus", "haiku", "other"):
            if filled[key] > 0:
                bar_segments.append(
                    f"[{bucket_style[key]}]{'█' * filled[key]}[/]"
                )

        bar_display = "".join(bar_segments)

        # Build compact legend for non-zero buckets
        labels = {"sonnet": "Sonnet", "opus": "Opus", "haiku": "Haiku", "other": "Other"}
        legend_parts = [
            f"{labels[k]} {percentage(buckets[k], total_tokens):.1f}%"
            for k in ("sonnet", "opus", "haiku", "other")
            if buckets[k] > 0
        ]
        summary = " | ".join(legend_parts)

        return f"[{bar_display}] {summary}"


class PieChart:
    """Renders a small terminal pie chart using Unicode block characters.

    Each grid cell's (x, y) position is mapped to an angle from the centre
    and coloured to whichever slice owns that angle.  A 2:1 aspect-ratio
    correction is applied so the result looks circular in a typical terminal.
    """

    # Chart dimensions in terminal characters
    WIDTH: Final[int] = 13
    HEIGHT: Final[int] = 7

    # Styles matching the ModelUsageBar bucket colours
    _BUCKET_STYLES: Final[dict] = {
        "sonnet": "info",
        "opus": "warning",
        "haiku": "success",
        "other": "dim",
    }
    _BUCKET_LABELS: Final[dict] = {
        "sonnet": "Sonnet",
        "opus": "Opus",
        "haiku": "Haiku",
        "other": "Other",
    }

    def render(self, per_model_stats: dict[str, Any]) -> list[str]:
        """Render a pie chart plus legend from per-model token stats.

        Args:
            per_model_stats: Same format as ModelUsageBar — model name → stats dict.

        Returns:
            List of Rich-markup strings, one per terminal row.
            First rows are the chart; the final row is the colour legend.
        """
        buckets: dict[str, int] = {"sonnet": 0, "opus": 0, "haiku": 0, "other": 0}

        for model_name, stats in per_model_stats.items():
            tokens = stats.get("input_tokens", 0) + stats.get("output_tokens", 0)
            lower = model_name.lower()
            if "sonnet" in lower:
                buckets["sonnet"] += tokens
            elif "opus" in lower:
                buckets["opus"] += tokens
            elif "haiku" in lower:
                buckets["haiku"] += tokens
            else:
                buckets["other"] += tokens

        total = sum(buckets.values())
        if total == 0:
            return ["[dim](no model data)[/]"]

        # Build slice angle boundaries (clockwise from top, 0→2π)
        slices: list[tuple[float, float, str]] = []
        cumulative = 0.0
        for key in ("sonnet", "opus", "haiku", "other"):
            if buckets[key] == 0:
                continue
            start_angle = cumulative / total * 2 * math.pi
            cumulative += buckets[key]
            end_angle = cumulative / total * 2 * math.pi
            slices.append((start_angle, end_angle, self._BUCKET_STYLES[key]))

        cx = self.WIDTH / 2.0
        cy = self.HEIGHT / 2.0
        # Terminal chars are ~2x taller than wide, so divide ny by 2 so the
        # circle looks round rather than squished vertically.
        ASPECT = 2.0

        lines: list[str] = []
        for row in range(self.HEIGHT):
            parts: list[str] = []
            for col in range(self.WIDTH):
                nx = (col - cx + 0.5) / (self.WIDTH / 2.0)
                ny = (row - cy + 0.5) / (self.HEIGHT / 2.0) / ASPECT

                if math.sqrt(nx * nx + ny * ny) > 1.0:
                    parts.append(" ")
                    continue

                # atan2(x, -y) gives clockwise angle from the top (12 o'clock = 0)
                angle = math.atan2(nx, -ny) % (2 * math.pi)

                style = "dim"
                for start, end, s in slices:
                    if start <= angle < end:
                        style = s
                        break

                parts.append(f"[{style}]█[/]")

            lines.append("".join(parts))

        # Colour-coded legend beneath the chart
        legend_parts: list[str] = []
        for key in ("sonnet", "opus", "haiku", "other"):
            if buckets[key] == 0:
                continue
            pct = buckets[key] / total * 100
            style = self._BUCKET_STYLES[key]
            label = self._BUCKET_LABELS[key]
            legend_parts.append(f"[{style}]█[/] {label} {pct:.1f}%")

        lines.append("  ".join(legend_parts))
        return lines
