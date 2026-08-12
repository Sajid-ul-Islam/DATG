from __future__ import annotations

import io
import logging
from typing import List, Optional, Tuple

logger = logging.getLogger(__name__)

# Heavy data-science libraries (pandas, numpy, matplotlib, seaborn) are imported
# lazily on first use so that importing this module stays cheap. This keeps
# serverless cold starts (e.g. on Vercel) fast — importing these libraries can
# take several seconds, and most requests (like /help) never touch a dataset.
_pd = _np = _plt = _sns = None


def _lazy_libs() -> tuple:
    """
    Import pandas/numpy/matplotlib/seaborn once, on first use.

    Returns (pd, np, plt, sns). Matplotlib's Agg backend and the shared
    plotting style are configured here, when the libraries are actually needed.
    """
    global _pd, _np, _plt, _sns
    if _pd is None:
        import matplotlib
        matplotlib.use('Agg')  # Non-interactive backend for server environments
        import matplotlib.pyplot as plt
        import numpy as np
        import pandas as pd
        import seaborn as sns

        # Set modern plotting style (once, when the libs first load)
        plt.style.use('ggplot')
        sns.set_theme(style="whitegrid", palette="muted")

        _pd, _np, _plt, _sns = pd, np, plt, sns
    return _pd, _np, _plt, _sns


class DataAnalyzer:
    """
    Analyzes CSV/Excel datasets and produces text summaries and visualizations.
    """

    @staticmethod
    def load_dataframe(file_bytes: bytes, filename: str, sheet_name: Optional[str] = None) -> pd.DataFrame:
        """
        Loads bytes into a pandas DataFrame based on file extension.

        For Excel files, `sheet_name` selects a specific tab; when None the
        first sheet is used.
        """
        pd, np, plt, sns = _lazy_libs()
        buffer = io.BytesIO(file_bytes)
        filename_lower = filename.lower()

        if filename_lower.endswith('.csv'):
            # Try UTF-8 first, fallback to latin-1 if decoding fails
            try:
                df = pd.read_csv(buffer, encoding='utf-8')
            except pd.errors.EmptyDataError:
                raise ValueError("The uploaded dataset is empty.")
            except UnicodeDecodeError:
                buffer.seek(0)
                try:
                    df = pd.read_csv(buffer, encoding='latin-1')
                except pd.errors.EmptyDataError:
                    raise ValueError("The uploaded dataset is empty.")
        elif filename_lower.endswith(('.xlsx', '.xls')):
            try:
                # None means "first sheet" (passing None to read_excel would
                # return a dict of all sheets, so map it to 0 explicitly)
                df = pd.read_excel(buffer, sheet_name=sheet_name if sheet_name is not None else 0)
            except ValueError as e:
                if sheet_name is not None:
                    raise ValueError(
                        f"Sheet `{sheet_name}` not found in the workbook. "
                        "Use `/sheets` to list available tabs."
                    ) from e
                raise ValueError(f"Failed to parse Excel file: {str(e)}") from e
            except Exception as e:
                raise ValueError(f"Failed to parse Excel file: {str(e)}")
        else:
            raise ValueError(
                f"Unsupported file format for file: {filename}. "
                "Please upload a .csv, .xlsx, or .xls file."
            )

        if df.empty:
            raise ValueError("The uploaded dataset is empty.")

        return df

    @staticmethod
    def list_sheets(file_bytes: bytes, filename: str) -> List[str]:
        """
        Returns the sheet/tab names of an Excel workbook (empty for CSV).
        """
        if not filename.lower().endswith(('.xlsx', '.xls')):
            return []
        pd, np, plt, sns = _lazy_libs()
        try:
            workbook = pd.ExcelFile(io.BytesIO(file_bytes))
            return list(workbook.sheet_names)
        except Exception:
            return []

    @staticmethod
    def generate_summary(df: pd.DataFrame, filename: str) -> str:
        """
        Generates a markdown text summary of the DataFrame.
        """
        pd, np, plt, sns = _lazy_libs()
        rows, cols = df.shape
        total_cells = rows * cols
        total_nulls = int(df.isnull().sum().sum())
        null_percent = (total_nulls / total_cells * 100) if total_cells > 0 else 0.0
        memory_mb = df.memory_usage(deep=True).sum() / (1024 * 1024)

        lines = [
            f"📊 **Data Summary for `{filename}`**\n",
            f"• **Rows**: {rows:,}",
            f"• **Columns**: {cols:,}",
            f"• **Missing Values**: {total_nulls:,} ({null_percent:.1f}%)",
            f"• **Memory Footprint**: {memory_mb:.2f} MB\n",
            "📋 **Column Details:**"
        ]

        # Column info table
        col_info_rows = []
        for col in df.columns[:15]:  # Limit to first 15 columns for chat clarity
            dtype_str = str(df[col].dtype)
            null_count = int(df[col].isnull().sum())
            col_info_rows.append(f"• `{col}` ({dtype_str}): {null_count} missing")

        lines.extend(col_info_rows)

        if len(df.columns) > 15:
            lines.append(f"  *... and {len(df.columns) - 15} more columns*")

        # Numeric Statistics Summary
        numeric_df = df.select_dtypes(include=[np.number])
        if not numeric_df.empty:
            lines.append("\n📈 **Numeric Statistics (Sample):**")
            stats = numeric_df.describe().T[['mean', '50%', 'std', 'min', 'max']]
            stats.columns = ['Mean', 'Median', 'Std', 'Min', 'Max']

            # Format stats into monospaced block
            lines.append("```")
            lines.append(stats.round(2).to_string())
            lines.append("```")

        # Outlier detection summary
        outlier_text = DataAnalyzer.detect_outliers_text(df)
        if outlier_text:
            lines.append(outlier_text)

        # Time-series detection note
        date_cols = DataAnalyzer.detect_date_columns(df)
        if date_cols:
            cols_str = ", ".join(f"`{c}`" for c in date_cols)
            lines.append(f"\n📅 **Date columns detected:** {cols_str} — time-series charts generated below.")

        return "\n".join(lines)

    # ──────────────────────────────────────────────────────────────────────────
    # Outlier Detection
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def detect_outliers_text(df: pd.DataFrame) -> str:
        """
        Uses the IQR method to detect outliers in each numeric column.
        Returns a formatted markdown string, or empty string if none found.
        """
        pd, np, plt, sns = _lazy_libs()
        numeric_df = df.select_dtypes(include=[np.number])
        if numeric_df.empty:
            return ""

        outlier_lines = []
        for col in numeric_df.columns[:10]:  # Cap at 10 cols
            series = numeric_df[col].dropna()
            if len(series) < 4:
                continue
            q1 = series.quantile(0.25)
            q3 = series.quantile(0.75)
            iqr = q3 - q1
            lower = q1 - 1.5 * iqr
            upper = q3 + 1.5 * iqr
            n_outliers = int(((series < lower) | (series > upper)).sum())
            pct = n_outliers / len(series) * 100
            if n_outliers > 0:
                outlier_lines.append(f"  • `{col}`: {n_outliers:,} outliers ({pct:.1f}%)")

        if not outlier_lines:
            return ""

        return "\n⚠️ **Outlier Report (IQR method):**\n" + "\n".join(outlier_lines)

    # ──────────────────────────────────────────────────────────────────────────
    # Time-Series Detection
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def detect_date_columns(df: pd.DataFrame) -> List[str]:
        """
        Attempts to identify date/datetime columns in the DataFrame.
        Returns a list of detected column names.
        """
        pd, np, plt, sns = _lazy_libs()
        date_cols = []
        for col in df.columns:
            if pd.api.types.is_datetime64_any_dtype(df[col]):
                date_cols.append(col)
            elif pd.api.types.is_string_dtype(df[col]):
                # Try parsing a sample
                sample = df[col].dropna().head(20)
                if len(sample) == 0:
                    continue
                try:
                    parsed = pd.to_datetime(sample, errors='coerce')
                    if parsed.notna().sum() >= len(sample) * 0.8:
                        date_cols.append(col)
                except Exception:
                    pass
        return date_cols

    @staticmethod
    def generate_timeseries_charts(df: pd.DataFrame) -> List[Tuple[io.BytesIO, str]]:
        """
        Generates line charts for each detected date column vs numeric columns.
        Returns a list of (BytesIO buffer, caption) tuples.
        """
        pd, np, plt, sns = _lazy_libs()
        charts: List[Tuple[io.BytesIO, str]] = []
        date_cols = DataAnalyzer.detect_date_columns(df)
        numeric_cols = df.select_dtypes(include=[np.number]).columns[:4]  # Max 4 numeric

        if not date_cols or numeric_cols.empty:
            return charts

        date_col = date_cols[0]  # Use the first date column

        # Parse dates if not already
        try:
            date_series = pd.to_datetime(df[date_col], errors='coerce')
        except Exception:
            return charts

        plot_df = df.copy()
        plot_df['__date__'] = date_series
        plot_df = plot_df.dropna(subset=['__date__']).sort_values('__date__')

        if plot_df.empty:
            return charts

        fig, axes = plt.subplots(
            len(numeric_cols), 1,
            figsize=(10, 3 * len(numeric_cols)),
            sharex=True
        )
        if len(numeric_cols) == 1:
            axes = [axes]

        for i, num_col in enumerate(numeric_cols):
            grouped = plot_df.groupby('__date__')[num_col].mean()
            axes[i].plot(grouped.index, grouped.values, linewidth=1.8, color="#3498db")
            axes[i].fill_between(grouped.index, grouped.values, alpha=0.15, color="#3498db")
            axes[i].set_title(f"{num_col} over time", fontsize=10, fontweight='bold')
            axes[i].set_ylabel(num_col, fontsize=8)

        axes[-1].set_xlabel(date_col)
        plt.suptitle(f"Time-Series Analysis (by {date_col})", fontsize=12, fontweight='bold', y=1.01)
        plt.tight_layout()

        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=120, bbox_inches='tight')
        plt.close(fig)
        buf.seek(0)
        charts.append((buf, f"📅 Time-Series trends by `{date_col}`"))
        return charts

    # ──────────────────────────────────────────────────────────────────────────
    # AI Insight Summary
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def generate_ai_summary(df: pd.DataFrame, filename: str, openai_api_key: str) -> Optional[str]:
        """
        Uses OpenAI gpt-4o-mini to generate a plain-English data insight summary.
        Returns None if the API key is missing or the call fails.
        """
        if not openai_api_key:
            return None

        try:
            from openai import OpenAI  # Lazy import — only needed if key is present

            pd, np, plt, sns = _lazy_libs()
            rows, cols = df.shape
            numeric_df = df.select_dtypes(include=[np.number])
            col_list = ", ".join(df.columns[:20].tolist())

            stats_snippet = ""
            if not numeric_df.empty:
                stats = numeric_df.describe().T[['mean', '50%', 'std', 'min', 'max']]
                stats.columns = ['Mean', 'Median', 'Std', 'Min', 'Max']
                stats_snippet = stats.round(2).to_string()

            prompt = (
                f"You are a data analyst. Analyze the following dataset statistics and provide "
                f"3-5 concise, actionable insights in plain English. Be specific and avoid generic statements.\n\n"
                f"File: {filename}\n"
                f"Rows: {rows:,}, Columns: {cols}\n"
                f"Column names: {col_list}\n"
                f"Numeric stats:\n{stats_snippet}\n\n"
                f"Provide insights as bullet points."
            )

            client = OpenAI(api_key=openai_api_key)
            response = client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=400,
                temperature=0.4,
            )
            return response.choices[0].message.content.strip()

        except Exception:
            logger.warning("AI insight summary failed for %s", filename, exc_info=True)
            return None

    # ──────────────────────────────────────────────────────────────────────────
    # Visualizations
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def generate_visualizations(df: pd.DataFrame) -> List[Tuple[io.BytesIO, str]]:
        """
        Generates analysis charts (histograms, correlation heatmaps, bar charts).
        Returns a list of (BytesIO buffer, caption) tuples.
        """
        pd, np, plt, sns = _lazy_libs()
        charts: List[Tuple[io.BytesIO, str]] = []
        numeric_df = df.select_dtypes(include=[np.number])
        cat_df = df.select_dtypes(include=['object', 'category'])

        # 1. Numeric Distributions Grid
        if not numeric_df.empty:
            num_cols = numeric_df.columns[:9]  # Up to 9 numeric columns for grid
            n = len(num_cols)
            cols_grid = min(3, n)
            rows_grid = (n + cols_grid - 1) // cols_grid

            fig, axes = plt.subplots(rows_grid, cols_grid, figsize=(4 * cols_grid, 3 * rows_grid))
            if n == 1:
                axes_flat = [axes]
            else:
                axes_flat = axes.flatten() if hasattr(axes, 'flatten') else [axes]

            for i, col in enumerate(num_cols):
                sns.histplot(numeric_df[col].dropna(), kde=True, ax=axes_flat[i], color="#3498db")
                axes_flat[i].set_title(f"Distribution: {col}", fontsize=10, fontweight='bold')
                axes_flat[i].set_xlabel("")
                axes_flat[i].set_ylabel("")

            # Turn off unused subplots
            for j in range(i + 1, len(axes_flat)):
                fig.delaxes(axes_flat[j])

            plt.tight_layout()
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=120, bbox_inches='tight')
            plt.close(fig)
            buf.seek(0)
            charts.append((buf, "📊 Distribution of Numeric Features"))

        # 2. Correlation Heatmap (if 2+ numeric columns)
        if numeric_df.shape[1] >= 2:
            num_corr_cols = numeric_df.columns[:10]  # Max 10 columns for clean heatmap
            corr = numeric_df[num_corr_cols].corr()

            fig, ax = plt.subplots(figsize=(7, 5))
            sns.heatmap(corr, annot=True, fmt=".2f", cmap="Blues", ax=ax, cbar=True, square=True)
            ax.set_title("Correlation Heatmap", fontsize=12, fontweight='bold')

            plt.tight_layout()
            buf = io.BytesIO()
            plt.savefig(buf, format='png', dpi=120, bbox_inches='tight')
            plt.close(fig)
            buf.seek(0)
            charts.append((buf, "🔥 Correlation Heatmap"))

        # 3. Categorical Top Frequencies (if categorical columns exist)
        if not cat_df.empty:
            cat_col = cat_df.columns[0]
            top_counts = cat_df[cat_col].value_counts().head(8)

            if not top_counts.empty:
                fig, ax = plt.subplots(figsize=(7, 4))
                y_labels = top_counts.index.astype(str)
                sns.barplot(x=top_counts.values, y=y_labels, hue=y_labels, palette="viridis", legend=False, ax=ax)
                ax.set_title(f"Top Values in '{cat_col}'", fontsize=12, fontweight='bold')
                ax.set_xlabel("Count")

                plt.tight_layout()
                buf = io.BytesIO()
                plt.savefig(buf, format='png', dpi=120, bbox_inches='tight')
                plt.close(fig)
                buf.seek(0)
                charts.append((buf, f"🏷️ Value counts for '{cat_col}'"))

        # 4. Time-Series charts (if date columns detected)
        ts_charts = DataAnalyzer.generate_timeseries_charts(df)
        charts.extend(ts_charts)

        return charts

    # ──────────────────────────────────────────────────────────────────────────
    # Row Sorting
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def sort_dataframe(df: pd.DataFrame, column: str, ascending: bool = True) -> pd.DataFrame:
        """
        Returns a copy of the DataFrame sorted by `column` (original is untouched).
        Raises ValueError if the column is missing or its values can't be compared.
        """
        if column not in df.columns:
            raise ValueError(
                f"Column `{column}` not found. Use `/columns` to see available columns."
            )
        try:
            # Missing values always sort last, regardless of direction
            return df.sort_values(by=column, ascending=ascending, na_position="last")
        except TypeError as e:
            raise ValueError(
                f"Cannot sort by `{column}`: values are not comparable ({str(e)})"
            )

    # ──────────────────────────────────────────────────────────────────────────
    # DataFrame → Markdown Table Utility
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def dataframe_to_markdown(df: pd.DataFrame, max_rows: int = 10) -> str:
        """
        Converts a DataFrame to a monospaced markdown table string.
        Truncates to max_rows rows.
        """
        subset = df.head(max_rows)
        # Use pandas built-in markdown table
        try:
            return subset.to_markdown(index=False)
        except ImportError:
            # Fallback: simple pipe table
            cols = " | ".join(str(c) for c in subset.columns)
            sep = " | ".join(["---"] * len(subset.columns))
            rows_str = "\n".join(
                " | ".join(str(v) for v in row) for row in subset.values
            )
            return f"| {cols} |\n| {sep} |\n" + "\n".join(f"| {r} |" for r in rows_str.split("\n"))

    # ──────────────────────────────────────────────────────────────────────────
    # Per-Column Stats Breakdown
    # ──────────────────────────────────────────────────────────────────────────

    @staticmethod
    def generate_column_stats(df: pd.DataFrame, column: Optional[str] = None) -> str:
        """
        Generates a per-column breakdown: count/mean/std/min/median/max for
        numeric columns, unique/top for categoricals, and range for dates.
        If `column` is given, only that column is included.
        Raises ValueError if the requested column does not exist.
        """
        pd, np, plt, sns = _lazy_libs()
        cols = [column] if column else list(df.columns)
        lines = []

        def _fmt(v: float) -> str:
            """Format numbers readably: comma-grouped, no trailing zeros, sci for extremes."""
            if pd.isna(v):
                return "—"
            av = abs(v)
            if av != 0 and (av >= 1e7 or av < 1e-3):
                return f"{v:.4g}"
            return f"{v:,.2f}".rstrip("0").rstrip(".")

        for col in cols:
            if col not in df.columns:
                raise ValueError(f"Column `{col}` not found. Use `/columns` to see available columns.")

            series = df[col]
            count = int(series.notna().sum())
            lines.append(f"**`{col}`** ({series.dtype}) — {count:,} non-null / {len(df):,} rows")

            if pd.api.types.is_numeric_dtype(series):
                s = series.dropna()
                if len(s) == 0:
                    lines.append("  • No numeric values.")
                    continue
                stats = s.describe()
                lines.append(
                    f"  • Mean: {_fmt(stats['mean'])} | Std: {_fmt(stats['std'])}"
                )
                lines.append(
                    f"  • Min: {_fmt(stats['min'])} | Median: {_fmt(stats['50%'])} | Max: {_fmt(stats['max'])}"
                )
            elif pd.api.types.is_datetime64_any_dtype(series):
                s = series.dropna()
                if len(s) == 0:
                    lines.append("  • No date values.")
                    continue
                lines.append(
                    f"  • Min: {s.min():%Y-%m-%d %H:%M} | Max: {s.max():%Y-%m-%d %H:%M}"
                )
            else:
                s = series.dropna()
                if len(s) == 0:
                    lines.append("  • No values.")
                    continue
                unique = s.nunique(dropna=True)
                vc = s.value_counts()
                top = str(vc.index[0])
                top = " ".join(top.split()).replace("`", "'")
                if len(top) > 30:
                    top = top[:27] + "..."
                top_count = int(vc.iloc[0])
                top_pct = top_count / len(s) * 100
                lines.append(
                    f"  • Unique: {unique:,} | Top: `{top}` ({top_count:,} · {top_pct:.1f}%)"
                )

        return "\n".join(lines)
