"""Session display components for Claude Monitor.

Handles formatting of active session screens and session data display.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, List, Optional

import pytz

from claude_monitor.ui.components import CostIndicator, VelocityIndicator
from claude_monitor.ui.layouts import HeaderManager
from claude_monitor.ui.progress_bars import (
    ModelUsageBar,
    TimeProgressBar,
    TokenProgressBar,
)
from claude_monitor.utils.time_utils import (
    TimezoneHandler,
    format_display_time,
    get_time_format_preference,
    percentage,
)


@dataclass
class SessionDisplayData:
    """Data container for session display information.

    This replaces the 21 parameters in format_active_session_screen method.
    """

    plan: str
    timezone: str
    tokens_used: int
    token_limit: int
    usage_percentage: float
    tokens_left: int
    elapsed_session_minutes: float
    total_session_minutes: float
    burn_rate: float
    session_cost: float
    per_model_stats: dict[str, Any]
    sent_messages: int
    entries: list[dict]
    predicted_end_str: str
    reset_time_str: str
    current_time_str: str
    show_switch_notification: bool = False
    show_exceed_notification: bool = False
    show_tokens_will_run_out: bool = False
    original_limit: int = 0


class SessionDisplayComponent:
    """Main component for displaying active session information."""

    def __init__(self):
        """Initialize session display component with sub-components."""
        self.token_progress = TokenProgressBar()
        self.time_progress = TimeProgressBar()
        self.model_usage = ModelUsageBar()

    def _render_wide_progress_bar(
        self,
        percentage: float,
        projection_pct: Optional[float] = None,
    ) -> str:
        """Render a wide progress bar (50 chars) with an optional projected-depletion marker.

        Args:
            percentage: Current usage percentage (can be > 100).
            projection_pct: Optional projected percentage at session end. When provided
                and > current, a ◆ marker is drawn at that position on the empty portion.

        Returns:
            Formatted progress bar string with Rich markup.
        """
        from claude_monitor.terminal.themes import get_cost_style

        width = 50

        if percentage < 50:
            color = "🟢"
        elif percentage < 80:
            color = "🟡"
        else:
            color = "🔴"

        bar_style = get_cost_style(percentage)
        capped = min(percentage, 100.0)
        filled = int(width * capped / 100)

        if percentage >= 100:
            overflow = percentage - 100.0
            overflow_str = f" [dim]+{overflow:.1f}%[/]" if overflow > 0 else ""
            return f"{color} [[{bar_style}]{'█' * width}[/]]{overflow_str}"

        # Determine marker position (only in the empty region ahead of current fill)
        marker_pos = -1
        if projection_pct is not None and projection_pct > percentage:
            mp = int(width * min(projection_pct, 100.0) / 100)
            if mp > filled and mp < width:
                marker_pos = mp

        # Build bar section by section for efficiency
        bar_parts: list[str] = []
        if filled > 0:
            bar_parts.append(f"[{bar_style}]{'█' * filled}[/]")

        if marker_pos > filled:
            before = marker_pos - filled
            after = width - marker_pos - 1
            if before > 0:
                bar_parts.append(f"[table.border]{'░' * before}[/]")
            bar_parts.append("[warning]◆[/]")
            if after > 0:
                bar_parts.append(f"[table.border]{'░' * after}[/]")
        else:
            empty = width - filled
            if empty > 0:
                bar_parts.append(f"[table.border]{'░' * empty}[/]")

        return f"{color} [{''.join(bar_parts)}]"

    def _render_sparkline_panel(self, values: List[float]) -> Any:
        """Return a Rich Panel containing a colour-graded burn-rate sparkline.

        Returns None when fewer than 2 samples are available.
        """
        from rich.panel import Panel
        from rich.text import Text

        if len(values) < 2:
            return None

        chars = "▁▂▃▄▅▆▇█"
        lo, hi = min(values), max(values)
        avg = sum(values) / len(values)
        n = len(chars) - 1

        text = Text()
        for v in values:
            frac = (v - lo) / (hi - lo) if hi > lo else 0.5
            ch = chars[int(frac * n)]
            if frac < 0.4:
                text.append(ch, style="green")
            elif frac < 0.75:
                text.append(ch, style="yellow")
            else:
                text.append(ch, style="red")

        text.append(
            f"\n  min: {lo:.0f}  avg: {avg:.0f}  max: {hi:.0f} tokens/min",
            style="dim",
        )

        return Panel(
            text,
            title="[dim]Burn Rate History[/]",
            border_style="dim",
            padding=(0, 1),
        )

    def _render_cache_efficiency(
        self, per_model_stats: dict, session_cost: float
    ) -> str:
        """Render a cache-efficiency progress bar.

        Efficiency = cache_read_tokens / total_tokens (higher is better / cheaper).
        Returns an empty string when there is no data.
        """
        total_in = total_out = total_cache = 0
        for stats in per_model_stats.values():
            if not isinstance(stats, dict):
                continue
            total_in += stats.get("input_tokens", 0)
            total_out += stats.get("output_tokens", 0)
            total_cache += stats.get("cache_read_tokens", 0)

        total = total_in + total_out + total_cache
        if total == 0:
            return ""

        cache_pct = total_cache / total * 100

        bar = self._render_wide_progress_bar(cache_pct)
        return (
            f"⚡ [value]Cache Efficiency:[/]  {bar} {cache_pct:4.1f}%"
            f"    [dim]{total_cache:,} cached / {total:,} total tokens[/]"
        )

    def _render_session_timeline(
        self,
        blocks: List[dict],
        args: Any = None,
    ) -> List[str]:
        """Render today's session activity as a 48-segment (30 min each) timeline.

        Returns a list of lines (may be empty if no sessions today).
        """
        if not blocks:
            return []

        tz = pytz.UTC
        if args and hasattr(args, "timezone"):
            try:
                tz = pytz.timezone(args.timezone)
            except Exception:
                pass

        now = datetime.now(tz)
        today = now.date()
        th = TimezoneHandler()

        sessions: List[tuple] = []
        for block in blocks:
            if block.get("isGap"):
                continue
            start_str = block.get("startTime")
            if not start_str:
                continue
            try:
                start = th.parse_timestamp(start_str).astimezone(tz)
                if start.date() != today:
                    continue
                end_str = block.get("endTime")
                if end_str:
                    end = th.parse_timestamp(end_str).astimezone(tz)
                elif block.get("isActive"):
                    end = now
                else:
                    end = start + timedelta(hours=5)
                sessions.append((start, min(end, now)))
            except Exception:
                continue

        if not sessions:
            return []

        segments = 48  # 30 min each across 24 h
        timeline = [False] * segments
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)

        for start, end in sessions:
            seg_s = max(0, int((start - midnight).total_seconds() / 1800))
            seg_e = min(segments, int((end - midnight).total_seconds() / 1800) + 1)
            for i in range(seg_s, seg_e):
                timeline[i] = True

        now_seg = int((now - midnight).total_seconds() / 1800)

        parts: List[str] = []
        for i, active in enumerate(timeline):
            if active:
                parts.append("[green]█[/]" if i <= now_seg else "[dim green]█[/]")
            else:
                parts.append("[dim]░[/]" if i <= now_seg else "[dim]·[/]")

        bar = "".join(parts)
        count = len(sessions)
        label = f"[dim]{count} session{'s' if count != 1 else ''} today[/]"
        return [f"📅 [value]Today's Sessions:[/]  {bar}  {label}"]

    def format_active_session_screen_v2(self, data: SessionDisplayData) -> list[str]:
        """Format complete active session screen using data class.

        This is the refactored version using SessionDisplayData.

        Args:
            data: SessionDisplayData object containing all display information

        Returns:
            List of formatted lines for display
        """
        return self.format_active_session_screen(
            plan=data.plan,
            timezone=data.timezone,
            tokens_used=data.tokens_used,
            token_limit=data.token_limit,
            usage_percentage=data.usage_percentage,
            tokens_left=data.tokens_left,
            elapsed_session_minutes=data.elapsed_session_minutes,
            total_session_minutes=data.total_session_minutes,
            burn_rate=data.burn_rate,
            session_cost=data.session_cost,
            per_model_stats=data.per_model_stats,
            sent_messages=data.sent_messages,
            entries=data.entries,
            predicted_end_str=data.predicted_end_str,
            reset_time_str=data.reset_time_str,
            current_time_str=data.current_time_str,
            show_switch_notification=data.show_switch_notification,
            show_exceed_notification=data.show_exceed_notification,
            show_tokens_will_run_out=data.show_tokens_will_run_out,
            original_limit=data.original_limit,
        )

    def format_active_session_screen(
        self,
        plan: str,
        timezone: str,
        tokens_used: int,
        token_limit: int,
        usage_percentage: float,
        tokens_left: int,
        elapsed_session_minutes: float,
        total_session_minutes: float,
        burn_rate: float,
        session_cost: float,
        per_model_stats: dict[str, Any],
        sent_messages: int,
        entries: list[dict],
        predicted_end_str: str,
        reset_time_str: str,
        current_time_str: str,
        show_switch_notification: bool = False,
        show_exceed_notification: bool = False,
        show_tokens_will_run_out: bool = False,
        original_limit: int = 0,
        **kwargs,
    ) -> list[str]:
        """Format complete active session screen.

        Args:
            plan: Current plan name
            timezone: Display timezone
            tokens_used: Number of tokens used
            token_limit: Token limit for the plan
            usage_percentage: Usage percentage
            tokens_left: Remaining tokens
            elapsed_session_minutes: Minutes elapsed in session
            total_session_minutes: Total session duration
            burn_rate: Current burn rate
            session_cost: Session cost in USD
            per_model_stats: Model usage statistics
            sent_messages: Number of messages sent
            entries: Session entries
            predicted_end_str: Predicted end time string
            reset_time_str: Reset time string
            current_time_str: Current time string
            show_switch_notification: Show plan switch notification
            show_exceed_notification: Show exceed limit notification
            show_tokens_will_run_out: Show token depletion warning
            original_limit: Original plan limit

        Returns:
            List of formatted screen lines
        """

        screen_buffer: list = []

        header_manager = HeaderManager()
        screen_buffer.extend(
            header_manager.create_header(
                plan,
                timezone,
                kwargs.get("data_path"),
                kwargs.get("account_info"),
            )
        )

        # Session timeline (today's activity) — shown above metrics
        timeline_lines = self._render_session_timeline(
            kwargs.get("all_blocks", []), kwargs.get("_args")
        )
        if timeline_lines:
            screen_buffer.extend(timeline_lines)
            screen_buffer.append("")

        # Pre-compute projection percentages for depletion markers
        time_remaining = max(0, total_session_minutes - elapsed_session_minutes)
        cost_per_min = (
            session_cost / max(1, elapsed_session_minutes)
            if elapsed_session_minutes > 0
            else 0
        )

        if burn_rate > 0 and token_limit > 0:
            token_projected_pct = (
                tokens_used + burn_rate * time_remaining
            ) / token_limit * 100
        else:
            token_projected_pct = None

        if plan in ["custom", "pro", "max5", "max20"]:
            from claude_monitor.core.plans import DEFAULT_COST_LIMIT

            cost_limit_p90 = kwargs.get("cost_limit_p90", DEFAULT_COST_LIMIT)
            messages_limit_p90 = kwargs.get("messages_limit_p90", 1500)
            model_trends = kwargs.get("model_trends")

            if cost_per_min > 0 and cost_limit_p90 and cost_limit_p90 > 0:
                cost_projected_pct: Optional[float] = (
                    session_cost + cost_per_min * time_remaining
                ) / cost_limit_p90 * 100
            else:
                cost_projected_pct = None

            screen_buffer.append("")
            if plan == "custom":
                screen_buffer.append("[bold]📊 Session-Based Dynamic Limits[/bold]")
                screen_buffer.append(
                    "[dim]Based on your historical usage patterns when hitting limits (P90)[/dim]"
                )
                screen_buffer.append(f"[separator]{'─' * 60}[/]")
            else:
                screen_buffer.append("")

            cost_percentage = (
                min(100, percentage(session_cost, cost_limit_p90))
                if cost_limit_p90 > 0
                else 0
            )
            cost_bar = self._render_wide_progress_bar(cost_percentage, cost_projected_pct)
            screen_buffer.append(
                f"💰 [value]Cost Usage:[/]           {cost_bar} {cost_percentage:4.1f}%"
                f"    [value]${session_cost:.2f}[/] / [dim]${cost_limit_p90:.2f}[/]"
            )
            screen_buffer.append("")

            token_bar = self._render_wide_progress_bar(usage_percentage, token_projected_pct)
            screen_buffer.append(
                f"📊 [value]Token Usage:[/]          {token_bar} {usage_percentage:4.1f}%"
                f"    [value]{tokens_used:,}[/] / [dim]{token_limit:,}[/]"
            )
            screen_buffer.append("")

            messages_percentage = (
                min(100, percentage(sent_messages, messages_limit_p90))
                if messages_limit_p90 > 0
                else 0
            )
            messages_bar = self._render_wide_progress_bar(messages_percentage)
            screen_buffer.append(
                f"📨 [value]Messages Usage:[/]       {messages_bar} {messages_percentage:4.1f}%"
                f"    [value]{sent_messages}[/] / [dim]{messages_limit_p90:,}[/]"
            )
            screen_buffer.append(f"[separator]{'─' * 60}[/]")

            time_percentage = (
                percentage(elapsed_session_minutes, total_session_minutes)
                if total_session_minutes > 0
                else 0
            )
            time_bar = self._render_wide_progress_bar(time_percentage)
            time_remaining_display = max(0, total_session_minutes - elapsed_session_minutes)
            time_left_hours = int(time_remaining_display // 60)
            time_left_mins = int(time_remaining_display % 60)
            screen_buffer.append(
                f"⏱️  [value]Time to Reset:[/]       {time_bar} {time_left_hours}h {time_left_mins}m"
            )
            screen_buffer.append("")

            model_bar = self.model_usage.render(per_model_stats or {}, trends=model_trends)
            screen_buffer.append(f"🤖 [value]Model Distribution:[/]   {model_bar}")
            screen_buffer.append(f"[separator]{'─' * 60}[/]")

            # Cache efficiency gauge
            eff_line = self._render_cache_efficiency(per_model_stats or {}, session_cost)
            if eff_line:
                screen_buffer.append(eff_line)

            velocity_emoji = VelocityIndicator.get_velocity_emoji(burn_rate)
            screen_buffer.append(
                f"🔥 [value]Burn Rate:[/]              [warning]{burn_rate:.1f}[/] [dim]tokens/min[/] {velocity_emoji}"
            )

            cost_per_min_display = CostIndicator.render(cost_per_min)
            screen_buffer.append(
                f"💲 [value]Cost Rate:[/]              {cost_per_min_display} [dim]$/min[/]"
            )

            # Full-width sparkline chart
            sparkline_panel = self._render_sparkline_panel(
                kwargs.get("burn_rate_history", [])
            )
            if sparkline_panel is not None:
                screen_buffer.append("")
                screen_buffer.append(sparkline_panel)
        else:
            cost_display = CostIndicator.render(session_cost)
            cost_per_min_display = CostIndicator.render(cost_per_min)
            screen_buffer.append(f"💲 [value]Session Cost:[/]   {cost_display}")
            screen_buffer.append(
                f"💲 [value]Cost Rate:[/]      {cost_per_min_display} [dim]$/min[/]"
            )
            screen_buffer.append("")

            token_bar = self.token_progress.render(usage_percentage)
            screen_buffer.append(f"📊 [value]Token Usage:[/]    {token_bar}")
            screen_buffer.append("")

            screen_buffer.append(
                f"🎯 [value]Tokens:[/]         [value]{tokens_used:,}[/] / [dim]~{token_limit:,}[/] ([info]{tokens_left:,} left[/])"
            )

            velocity_emoji = VelocityIndicator.get_velocity_emoji(burn_rate)
            screen_buffer.append(
                f"🔥 [value]Burn Rate:[/]      [warning]{burn_rate:.1f}[/] [dim]tokens/min[/] {velocity_emoji}"
            )

            screen_buffer.append(
                f"📨 [value]Sent Messages:[/]  [info]{sent_messages}[/] [dim]messages[/]"
            )

            if per_model_stats:
                model_bar = self.model_usage.render(
                    per_model_stats, trends=kwargs.get("model_trends")
                )
                screen_buffer.append(f"🤖 [value]Model Usage:[/]    {model_bar}")

            screen_buffer.append("")

            time_bar = self.time_progress.render(
                elapsed_session_minutes, total_session_minutes
            )
            screen_buffer.append(f"⏱️  [value]Time to Reset:[/]  {time_bar}")
            screen_buffer.append("")

        screen_buffer.append("")
        screen_buffer.append("🔮 [value]Predictions:[/]")
        screen_buffer.append(
            f"   [info]Tokens will run out:[/] [warning]{predicted_end_str}[/]"
        )
        screen_buffer.append(
            f"   [info]Limit resets at:[/]     [success]{reset_time_str}[/]"
        )
        screen_buffer.append("")

        self._add_notifications(
            screen_buffer,
            show_switch_notification,
            show_exceed_notification,
            show_tokens_will_run_out,
            original_limit,
            token_limit,
        )

        screen_buffer.append(
            f"⏰ [dim]{current_time_str}[/] 📝 [success]Active session[/] | [dim]Ctrl+C to exit[/] 🟢"
        )

        return screen_buffer

    def _add_notifications(
        self,
        screen_buffer: list[str],
        show_switch_notification: bool,
        show_exceed_notification: bool,
        show_tokens_will_run_out: bool,
        original_limit: int,
        token_limit: int,
    ) -> None:
        """Add notification messages to screen buffer.

        Args:
            screen_buffer: Screen buffer to append to
            show_switch_notification: Show plan switch notification
            show_exceed_notification: Show exceed limit notification
            show_tokens_will_run_out: Show token depletion warning
            original_limit: Original plan limit
            token_limit: Current token limit
        """
        notifications_added = False

        if show_switch_notification and token_limit > original_limit:
            screen_buffer.append(
                f"🔄 [warning]Token limit exceeded ({token_limit:,} tokens)[/]"
            )
            notifications_added = True

        if show_exceed_notification:
            screen_buffer.append(
                "⚠️  [error]You have exceeded the maximum cost limit![/]"
            )
            notifications_added = True

        if show_tokens_will_run_out:
            screen_buffer.append(
                "⏰ [warning]Cost limit will be exceeded before reset![/]"
            )
            notifications_added = True

        if notifications_added:
            screen_buffer.append("")

    def format_no_active_session_screen(
        self,
        plan: str,
        timezone: str,
        token_limit: int,
        current_time: Optional[datetime] = None,
        args: Optional[Any] = None,
        **kwargs,
    ) -> list[str]:
        """Format screen for no active session state.

        Args:
            plan: Current plan name
            timezone: Display timezone
            token_limit: Token limit for the plan
            current_time: Current datetime
            args: Command line arguments
            **kwargs: Optional keyword arguments including data_path and account_info

        Returns:
            List of formatted screen lines
        """

        screen_buffer: list = []

        header_manager = HeaderManager()
        screen_buffer.extend(
            header_manager.create_header(
                plan,
                timezone,
                kwargs.get("data_path"),
                kwargs.get("account_info"),
            )
        )

        timeline_lines = self._render_session_timeline(
            kwargs.get("all_blocks", []), args
        )
        if timeline_lines:
            screen_buffer.extend(timeline_lines)
            screen_buffer.append("")

        empty_token_bar = self.token_progress.render(0.0)
        screen_buffer.append(f"📊 [value]Token Usage:[/]    {empty_token_bar}")
        screen_buffer.append("")

        screen_buffer.append(
            f"🎯 [value]Tokens:[/]         [value]0[/] / [dim]~{token_limit:,}[/] ([info]0 left[/])"
        )
        screen_buffer.append(
            "🔥 [value]Burn Rate:[/]      [warning]0.0[/] [dim]tokens/min[/]"
        )
        screen_buffer.append(
            "💲 [value]Cost Rate:[/]      [cost.low]$0.00[/] [dim]$/min[/]"
        )
        screen_buffer.append("📨 [value]Sent Messages:[/]  [info]0[/] [dim]messages[/]")
        screen_buffer.append("")

        if current_time and args:
            try:
                display_tz = pytz.timezone(args.timezone)
                current_time_display = current_time.astimezone(display_tz)
                current_time_str = format_display_time(
                    current_time_display,
                    get_time_format_preference(args),
                    include_seconds=True,
                )
                screen_buffer.append(
                    f"⏰ [dim]{current_time_str}[/] 📝 [info]No active session[/] | [dim]Ctrl+C to exit[/] 🟨"
                )
            except (pytz.exceptions.UnknownTimeZoneError, AttributeError):
                screen_buffer.append(
                    "⏰ [dim]--:--:--[/] 📝 [info]No active session[/] | [dim]Ctrl+C to exit[/] 🟨"
                )
        else:
            screen_buffer.append(
                "⏰ [dim]--:--:--[/] 📝 [info]No active session[/] | [dim]Ctrl+C to exit[/] 🟨"
            )

        return screen_buffer
